"""Agent HTTP 接口（郑伟健 · 设计方案 §5.3 / §6.3）。

相对原版的改动：
- /run 接受 history（最近 10 轮），并把错误分级成 503/502/500，不再回显上游原文；
- 新增 /pending（刷新页面不丢待确认）与 /cancel（拒绝待确认，状态置 cancelled）；
- /confirm 执行前读 before_json，结果里带 diff，写回 result_json。

注意：请求/响应模型就近定义在本文件，避免动 schemas.py（归属程熙，见规范 §5.2）。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent import run_agent
from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..llm import LLM
from ..models import PendingAction, User
from ..schemas import AgentRequest
from ..tools import SPECS, WRITE_TOOLS, execute

router = APIRouter(prefix="/api/agent", tags=["agent"])
log = logging.getLogger("document.api")

CurrentUser = Annotated[User, Depends(current_user)]
DbSession = Annotated[Session, Depends(get_session)]


class AgentRunIn(AgentRequest):
    """在既有请求体上加 history；不改 schemas.py 里程熙维护的 AgentRequest。"""

    history: list[dict] = Field(default_factory=list)


class PendingItemOut(BaseModel):
    id: str
    tool: str
    args: dict
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    expires_at: dt.datetime
    status: str = "pending"


class AgentRunOut(BaseModel):
    ok: bool
    answer: str
    steps: list[dict]
    tool_calls: int
    total_ms: int
    stopped_by: str
    pending_writes: list[PendingItemOut] = Field(default_factory=list)


class PendingListOut(BaseModel):
    items: list[PendingItemOut]
    total: int
    truncated: bool = False


class ActionIn(BaseModel):
    action_id: str


class ConfirmOut(BaseModel):
    ok: bool
    tool: str
    result: dict
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)


def _llm() -> LLM:
    return LLM(get_settings())


def _parse(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _pending_item(row: PendingAction) -> PendingItemOut:
    args = _parse(row.args_json)
    before = _parse(row.before_json)
    after = dict(before)
    for key, value in args.items():
        after[key] = value
    return PendingItemOut(
        id=row.id,
        tool=row.tool,
        args=args,
        before=before,
        after=after,
        expires_at=row.expires_at,
        status=row.status,
    )


def _grade_error(exc: Exception) -> HTTPException:
    """把上游异常翻译成对外可读的状态码，避免泄露内部细节（§6.3）。"""
    text = str(exc)
    if isinstance(exc, RuntimeError) and "SILICONFLOW_API_KEY" in text:
        return HTTPException(503, "未配置 LLM 密钥，请联系管理员")
    name = type(exc).__name__
    if name in {"APITimeoutError", "APIConnectionError", "RateLimitError", "APIStatusError"}:
        log.warning("LLM 上游异常：%s", name)
        return HTTPException(502, "模型服务暂不可用，请稍后重试")
    log.exception("agent failed")
    return HTTPException(500, "Agent 执行失败")


@router.get("/tools")
def tools():
    return {
        "ok": True,
        "tools": [
            {
                "name": spec["function"]["name"],
                "description": spec["function"]["description"],
                "required": spec["function"]["parameters"].get("required", []),
            }
            for spec in SPECS
        ],
    }


@router.post("/run", response_model=AgentRunOut)
async def run(
    body: AgentRunIn,
    user: CurrentUser,
    db: DbSession,
):
    settings = get_settings()
    limit = min(body.max_steps or settings.agent_max_steps, settings.agent_max_steps)
    try:
        result = await run_agent(
            _llm(),
            db,
            user.id,
            body.question,
            settings,
            max_steps=limit,
            history=body.history,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _grade_error(exc) from exc

    return AgentRunOut(
        ok=True,
        answer=result.answer,
        steps=[
            {"kind": s.kind, "content": s.content, "tool": s.tool, "args": s.args, "ms": s.ms}
            for s in result.steps
        ],
        tool_calls=result.tool_calls,
        total_ms=result.total_ms,
        stopped_by=result.stopped_by,
        pending_writes=[
            PendingItemOut(
                id=item["id"],
                tool=item["tool"],
                args=item["args"],
                before=item.get("before") or {},
                after=item.get("after") or {},
                expires_at=item["expires_at"],
            )
            for item in result.pending_writes
        ],
    )


@router.get("/pending", response_model=PendingListOut)
def pending(user: CurrentUser, db: DbSession):
    """我的待确认列表；顺带把已过期的标成 expired，避免前端点了才报错。"""
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    rows = (
        db.execute(
            select(PendingAction)
            .where(PendingAction.owner_id == user.id, PendingAction.status == "pending")
            .order_by(PendingAction.expires_at.desc())
        )
        .scalars()
        .all()
    )
    items: list[PendingItemOut] = []
    for row in rows:
        if row.expires_at < now:
            row.status = "expired"
            db.commit()
            continue
        items.append(_pending_item(row))
    return PendingListOut(items=items, total=len(items), truncated=False)


@router.post("/cancel", response_model=PendingItemOut)
def cancel(
    body: ActionIn,
    user: CurrentUser,
    db: DbSession,
):
    """拒绝一条待确认操作；已执行的不能再取消。"""
    row = db.execute(
        select(PendingAction).where(
            PendingAction.id == body.action_id, PendingAction.owner_id == user.id
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "待确认操作不存在")
    if row.status == "executed":
        raise HTTPException(409, "该操作已执行，不能取消")
    if row.status == "cancelled":
        return _pending_item(row)
    row.status = "cancelled"
    db.commit()
    return _pending_item(row)


@router.post("/confirm", response_model=ConfirmOut)
def confirm(
    body: ActionIn,
    user: CurrentUser,
    db: DbSession,
):
    row = db.execute(
        select(PendingAction).where(
            PendingAction.id == body.action_id, PendingAction.owner_id == user.id
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "待确认操作不存在")
    if row.tool not in WRITE_TOOLS:
        raise HTTPException(400, "该操作不在写工具白名单")

    before = _parse(row.before_json)
    if row.status == "executed":
        stored = _parse(row.result_json)
        diff = stored.get("diff") or {}
        return ConfirmOut(
            ok=True,
            tool=row.tool,
            result=stored,
            before=diff.get("before", before),
            after=diff.get("after", {}),
        )
    if row.status == "cancelled":
        raise HTTPException(409, "该操作已被取消")
    if row.status != "pending":
        raise HTTPException(409, f"当前状态 {row.status} 不能执行")

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    if row.expires_at < now:
        row.status = "expired"
        db.commit()
        raise HTTPException(409, "确认已过期，请重新发起操作")

    row.status = "executing"
    db.commit()
    try:
        result = execute(row.tool, _parse(row.args_json), db, user.id, commit=False)
        if result.get("error"):
            raise RuntimeError(result["error"])
    except Exception as exc:
        db.rollback()
        failed = db.get(PendingAction, row.id)
        if failed is not None and failed.status == "executing":
            failed.status = "pending"
            db.commit()
        log.exception("confirmed action %s failed", row.id)
        raise HTTPException(500, "写操作执行失败，请重试") from exc

    done = db.get(PendingAction, row.id)
    if done is None:
        raise HTTPException(500, "写操作已完成，但确认记录丢失")
    after = _parse(done.args_json)
    merged = dict(before)
    for key, value in after.items():
        merged[key] = value
    diff = {
        "before": before,
        "after": merged,
        "changed": {
            key: {"from": before.get(key), "to": value}
            for key, value in after.items()
            if before.get(key) != value
        },
    }
    payload = {**result, "diff": diff}
    done.status = "executed"
    done.result_json = json.dumps(payload, ensure_ascii=False)
    done.confirmed_at = now
    db.commit()
    return ConfirmOut(ok=True, tool=done.tool, result=payload, before=before, after=merged)
