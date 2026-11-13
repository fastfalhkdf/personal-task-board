import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterIn(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=8, max_length=72)


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    created_at: dt.datetime


class AgentRequest(BaseModel):
    question: str = Field(min_length=2, max_length=20000)
    max_steps: int | None = Field(None, ge=1, le=10)


class PendingOut(BaseModel):
    id: str
    tool: str
    args: dict
    expires_at: dt.datetime


class AgentResponse(BaseModel):
    ok: bool
    answer: str
    steps: list[dict]
    tool_calls: int
    total_ms: int
    stopped_by: str
    pending_writes: list[PendingOut] = []


class ConfirmIn(BaseModel):
    action_id: str


class ConfirmOut(BaseModel):
    ok: bool
    tool: str
    result: dict


ConfirmWriteIn = ConfirmIn
ConfirmWriteOut = ConfirmOut
PendingWriteOut = PendingOut

# ---- 任务接口（D1 · 程熙）：REST 侧校验，设计方案 §5.1 ----
# 与 app/tools.py 里 Agent 侧的 validate 分轨：REST 只强制 title，
# "标题+项目+截止日期"三件套仅对 Agent 强制（需求 4.2），避免页面建私人任务被卡死。

TASK_STATUSES = {"todo", "in_progress", "blocked", "done"}
TASK_PRIORITIES = {"low", "medium", "high"}


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    project_id: int | None = None
    priority: str = "medium"
    due_date: dt.date | None = None
    assignee_id: int | None = None
    tags: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("title")
    @classmethod
    def _title_non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("priority")
    @classmethod
    def _priority_enum(cls, v: str) -> str:
        if v not in TASK_PRIORITIES:
            raise ValueError("优先级非法")
        return v

    @field_validator("tags")
    @classmethod
    def _tags_normalize(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            t = raw.strip()[:30]
            if t and t not in out:
                out.append(t)
        return out


class TaskPatchIn(BaseModel):
    """全部字段可选；用 model_fields_set 区分"没传"与"显式置 null"。"""

    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    status: str | None = None
    priority: str | None = None
    due_date: dt.date | None = None
    project_id: int | None = None
    assignee_id: int | None = None
    sort_order: float | None = Field(default=None, ge=-1e9, le=1e9)

    @field_validator("title")
    @classmethod
    def _title_non_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("标题不能为空")
        return v

    @field_validator("status")
    @classmethod
    def _status_enum(cls, v: str | None) -> str | None:
        if v is not None and v not in TASK_STATUSES:
            raise ValueError("状态非法")
        return v

    @field_validator("priority")
    @classmethod
    def _priority_enum(cls, v: str | None) -> str | None:
        if v is not None and v not in TASK_PRIORITIES:
            raise ValueError("优先级非法")
        return v
