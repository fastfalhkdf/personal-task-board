# 文件开发记录：`app/routers/agent.py`

> 目标文件：`app/routers/agent.py`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````python
from __future__ import annotations
import datetime as dt, json, logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..agent import run_agent
from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..llm import LLM
from ..models import PendingAction, User
from ..schemas import AgentRequest, AgentResponse, ConfirmWriteIn, ConfirmWriteOut, PendingWriteOut
from ..tools import SPECS, WRITE_TOOLS, execute

router = APIRouter(prefix="/api/agent", tags=["agent"])
log = logging.getLogger("document.api")


def _llm():
    return LLM(get_settings())


def _pending(row):
    return PendingWriteOut(
        id=row.id, tool=row.tool, args=json.loads(row.args_json), expires_at=row.expires_at
    )


@router.get("/tools")
def tools():
    return {
        "ok": True,
        "tools": [
            {
                "name": x["function"]["name"],
                "description": x["function"]["description"],
                "required": x["function"]["parameters"].get("required", []),
            }
            for x in SPECS
        ],
    }


@router.post("/run", response_model=AgentResponse)
async def run(
    body: AgentRequest, user: User = Depends(current_user), db: Session = Depends(get_session)
):
    s = get_settings()
    try:
        r = await run_agent(
            _llm(),
            db,
            user.id,
            body.question,
            s,
            max_steps=min(body.max_steps or s.agent_max_steps, s.agent_max_steps),
        )
    except Exception as exc:
        log.exception("agent failed")
        raise HTTPException(500, str(exc)) from exc
    return AgentResponse(
        ok=True,
        answer=r.answer,
        steps=[
            {"kind": x.kind, "content": x.content, "tool": x.tool, "args": x.args, "ms": x.ms}
            for x in r.steps
        ],
        tool_calls=r.tool_calls,
        total_ms=r.total_ms,
        stopped_by=r.stopped_by,
        pending_writes=[_pending(x) for x in r.pending_writes],
    )


@router.post("/confirm", response_model=ConfirmWriteOut)
def confirm(
    body: ConfirmWriteIn, user: User = Depends(current_user), db: Session = Depends(get_session)
):
    action = db.execute(
        select(PendingAction).where(
            PendingAction.id == body.action_id, PendingAction.owner_id == user.id
        )
    ).scalar_one_or_none()
    if not action:
        raise HTTPException(404, "待确认操作不存在")
    if action.tool not in WRITE_TOOLS:
        raise HTTPException(400, "该操作不在写工具白名单")
    if action.status == "executed":
        return ConfirmWriteOut(
            ok=True, tool=action.tool, result=json.loads(action.result_json or "{}")
        )
    if action.status != "pending":
        raise HTTPException(409, f"当前状态 {action.status} 不能执行")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    if action.expires_at < now:
        action.status = "expired"
        db.commit()
        raise HTTPException(409, "确认已过期")
    action.status = "executing"
    db.commit()
    try:
        result = execute(action.tool, json.loads(action.args_json), db, user.id, commit=False)
        if result.get("error"):
            raise RuntimeError(result["error"])
    except Exception as exc:
        db.rollback()
        failed = db.get(PendingAction, action.id)
        if failed and failed.status == "executing":
            failed.status = "pending"
            db.commit()
        raise HTTPException(500, f"写操作执行失败：{exc}") from exc
    done = db.get(PendingAction, action.id)
    done.status = "executed"
    done.result_json = json.dumps(result, ensure_ascii=False)
    done.confirmed_at = now
    db.commit()
    return ConfirmWriteOut(ok=True, tool=done.tool, result=result)
````

验证：3 个测试通过。
