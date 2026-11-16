"""ReAct Agent 循环：决策 → 工具 → 观察 → 收敛（郑伟健 · 设计方案 §6.2）。

相对原版的三处改动：
1. 支持前端带上最近 N 轮对话（history），解决「再把它移到进行中」这类指代；
   服务端保持无状态，裁剪到最近 10 轮，不引入会话表。
2. 写工具拦截时先取 before 快照写进 pending_actions.before_json，
   响应里带 before/after，前端据此渲染「字段：旧值 → 新值」。
3. SYSTEM 增加两条硬规则：只碰当前用户可见的项目资源；定位不唯一必须反问。
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass, field

from .models import PendingAction
from .tools import SPECS, WRITE_TOOLS, execute, precheck, snapshot, validate

#: 前端最多带 10 轮，服务端只认最近 10 轮（20 条消息），防止 prompt 被刷爆
MAX_HISTORY_ROUNDS = 10

SYSTEM = """你是「个人任务与项目看板」的助手，能查询和修改用户的真实任务数据。

硬规则（违反即视为错误）：
1. 只操作当前登录用户有权访问的资源。私人任务只有创建者能看；项目任务只有项目成员能看。
   不要尝试猜测别人的 project_id 或 task_id。
2. 改任务前必须先用 list_tasks 或 get_task 唯一定位到那一条。
   如果匹配到多条或一条都没有，直接反问用户（例如「你说的『那个任务』是指哪一条？」），
   绝对不要猜一个 task_id 去改。

工作方式：
- 数量、完成率、逾期、今日待办这类问题，一律调用工具查真实数据库，不许凭空回答；
- 一次可以并行调用多个互不依赖的工具；
- 新建和修改任务会被系统拦截成「待确认单」，用户点确认后才真正写库——这是正常流程。
  顺序必须是：先调用工具（先 list_tasks 定位，再 update_task/create_task 生成待确认单），
  工具调用之后才回复用户「我已准备好，请确认」；没有调用过工具时禁止说这句话；
- 工具返回空结果时如实说「没找到」，不要编造；
- 回答用简洁中文，不要复述整段 JSON。

示例：
用户：把「写周报」移到进行中
你：调用 list_tasks 找到「写周报」→ 调用 update_task(status=in_progress)
    → 系统生成待确认单后回复：已准备把「写周报」改为进行中，请确认。
用户：今天要做什么
你：调用 list_tasks 查今天到期的待办 → 用一句话汇总真实结果。"""


@dataclass
class Step:
    kind: str  # thought / tool_call / tool_result / answer / error
    content: str
    tool: str | None = None
    args: dict | None = None
    ms: int = 0


@dataclass
class Result:
    answer: str
    steps: list[Step] = field(default_factory=list)
    tool_calls: int = 0
    total_ms: int = 0
    stopped_by: str = "answer"  # answer / max_steps / error
    pending: list[dict] = field(default_factory=list)

    @property
    def pending_writes(self) -> list[dict]:
        return self.pending


def after_preview(name: str, args: dict, before: dict) -> dict:
    """把「模型想改成什么」合并成一条可读的目标状态，供前端 diff。"""
    if name == "create_task":
        return {
            "title": str(args.get("title") or "").strip(),
            "description": str(args.get("description") or ""),
            "status": "todo",
            "priority": str(args.get("priority") or "medium"),
            "due_date": args.get("due_date"),
            "project_id": args.get("project_id"),
            "assignee_id": args.get("assignee_id"),
            "tags": args.get("tags") or [],
        }
    merged = dict(before or {})
    for key in (
        "title",
        "description",
        "status",
        "priority",
        "due_date",
        "project_id",
        "assignee_id",
        "tags",
    ):
        if key in args:
            merged[key] = args[key]
    return merged


def _trim_history(history: list[dict] | None) -> list[dict]:
    """只保留 user/assistant 的纯文本消息，最多最近 10 轮。"""
    if not history:
        return []
    cleaned: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            cleaned.append({"role": role, "content": content[:4000]})
    return cleaned[-MAX_HISTORY_ROUNDS * 2 :]


async def run_agent(
    llm,
    db,
    uid: int,
    question: str,
    s,
    max_steps: int | None = None,
    history: list[dict] | None = None,
    confirm_write: bool | None = None,
) -> Result:
    """跑一轮 ReAct。所有决策来自真实模型，工具执行查真实数据库。"""
    confirm = s.agent_confirm_write if confirm_write is None else confirm_write
    limit = max(1, min(max_steps or s.agent_max_steps, s.agent_max_steps))

    messages: list[dict] = [{"role": "system", "content": SYSTEM}]
    messages.extend(_trim_history(history))
    messages.append({"role": "user", "content": question})

    steps: list[Step] = []
    pending: list[dict] = []
    started = time.perf_counter()
    calls = 0
    nudged = False

    for _ in range(limit):
        msg, _meta = await llm.with_tools(messages, SPECS, temperature=0.2)
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            text = msg.content or ""
            # 护栏：小模型常见失误——没调工具就直接说确认话术，纠正一次再给机会
            if not pending and not nudged and ("请确认" in text or "准备好" in text):
                nudged = True
                steps.append(Step("thought", "模型未调用工具就回复了确认话术，自动纠正重试"))
                messages.append({"role": "assistant", "content": text})
                messages.append(
                    {
                        "role": "user",
                        "content": "系统提示：你还没有调用任何工具。必须先调用 list_tasks 定位任务，"
                        "再调用 update_task 生成待确认单；调用工具之前不要说确认话术。",
                    }
                )
                continue
            steps.append(Step("answer", text))
            return Result(
                text, steps, calls, int((time.perf_counter() - started) * 1000), "answer", pending
            )

        messages.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        for tc in tool_calls:
            calls += 1
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            steps.append(
                Step("tool_call", json.dumps(args, ensure_ascii=False), tool=name, args=args)
            )

            if name in WRITE_TOOLS and confirm:
                error = validate(name, args) or precheck(db, name, args, uid)
                if error:
                    result = {"error": error}
                    steps.append(
                        Step("tool_result", json.dumps(result, ensure_ascii=False), tool=name)
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue

                before = snapshot(db, name, args, uid)
                if name == "update_task" and not before:
                    result = {
                        "error": "任务不存在或无权修改。你必须先调用 list_tasks（可用标题关键字）"
                        "拿到真实的 task_id 再重试 update_task；task_id 只能来自工具返回，禁止编造。"
                    }
                    steps.append(
                        Step("tool_result", json.dumps(result, ensure_ascii=False), tool=name)
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    continue

                after = after_preview(name, args, before)
                now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
                action = PendingAction(
                    id=uuid.uuid4().hex,
                    owner_id=uid,
                    tool=name,
                    args_json=json.dumps(args, ensure_ascii=False),
                    before_json=json.dumps(before, ensure_ascii=False),
                    expires_at=now + dt.timedelta(minutes=s.agent_confirm_ttl_minutes),
                )
                db.add(action)
                db.commit()
                pending.append(
                    {
                        "id": action.id,
                        "tool": name,
                        "args": args,
                        "before": before,
                        "after": after,
                        "expires_at": action.expires_at,
                    }
                )
                result = {
                    "action_id": action.id,
                    "status": "pending_confirmation",
                    "message": "该操作会写入数据库，已生成待确认记录，需要用户确认后执行。",
                    "before": before,
                    "after": after,
                }
            else:
                try:
                    result = execute(name, args, db, uid)
                except Exception as exc:  # noqa: BLE001 工具异常不该打崩整轮
                    result = {"error": str(exc)}

            steps.append(Step("tool_result", json.dumps(result, ensure_ascii=False), tool=name))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    steps.append(Step("error", f"达到步数上限 {limit}，已强制停止"))
    return Result(
        f"已达到最大步数 {limit}，请把问题拆小一点再试。",
        steps,
        calls,
        int((time.perf_counter() - started) * 1000),
        "max_steps",
        pending,
    )
