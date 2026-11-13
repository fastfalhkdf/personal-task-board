# 个人任务与项目看板开发手册

## 功能业务

- 任务查询、统计和状态管理。
- Agent 工具与确认写操作。
- 用户隔离、测试与 Docker。

## 完整源码

### 3.1 `requirements.txt`

````text
fastapi==0.115.6
uvicorn[standard]==0.34.0
openai==1.59.6
sqlalchemy==2.0.36
bcrypt==4.2.0
pyjwt==2.10.1
pydantic==2.10.4
pydantic-settings==2.7.0
python-dotenv==1.0.1
httpx==0.28.1
````

### 3.2 `.env.example`

````dotenv
SILICONFLOW_API_KEY=
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
MODEL_CHAT=Qwen/Qwen2.5-7B-Instruct
APP_ENV=local
PORT=8000
DATABASE_URL=sqlite:///./data/task_board.db
JWT_SECRET=replace-with-a-long-random-secret
JWT_EXPIRE_HOURS=12
COOKIE_SECURE=false
AGENT_MAX_STEPS=6
AGENT_CONFIRM_WRITE=true
AGENT_CONFIRM_TTL_MINUTES=10
````

### 3.3 `.gitignore`

````text
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
data/*.db
data/*.db-*
*.log
.DS_Store
````

### 3.4 `.dockerignore`

````text
.git
.gitignore
.env
.venv
__pycache__
*.pyc
*.db
data/*.db
data/*.db-*
tests/__pycache__
.DS_Store
````

### 3.5 `Dockerfile`

````dockerfile
ARG PYTHON_BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PORT=8000 APP_ENV=production DATABASE_URL=sqlite:////app/data/content_assistant.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /app/data && useradd --create-home --shell /usr/sbin/nologin appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
````

### 3.6 `docker-compose.yml`

````yaml
services:
  task-board:
    build:
      context: .
      args:
        PYTHON_BASE_IMAGE: "${PYTHON_BASE_IMAGE:-docker.m.daocloud.io/library/python:3.11-slim}"
    ports: ["8000:8000"]
    environment:
      SILICONFLOW_API_KEY: "${SILICONFLOW_API_KEY:-}"
      OPENAI_BASE_URL: "${OPENAI_BASE_URL:-https://api.siliconflow.cn/v1}"
      MODEL_CHAT: "${MODEL_CHAT:-Qwen/Qwen2.5-7B-Instruct}"
      JWT_SECRET: "${JWT_SECRET:-change-this-in-production}"
      COOKIE_SECURE: "${COOKIE_SECURE:-false}"
      APP_ENV: production
      DATABASE_URL: sqlite:////app/data/task_board.db
      AGENT_MAX_STEPS: "6"
      AGENT_CONFIRM_WRITE: "true"
    volumes: ["task-data:/app/data"]
    restart: unless-stopped
volumes:
  task-data:
````

### 3.7 `app/__init__.py`

````python
"""新媒体内容生产智能体。"""
````

### 3.8 `app/config.py`

````python
"""邮件与公文助手配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    siliconflow_api_key: str = ""
    openai_base_url: str = "https://api.siliconflow.cn/v1"
    model_chat: str = "Qwen/Qwen2.5-7B-Instruct"
    app_env: str = "local"
    port: int = 8000
    database_url: str = "sqlite:///./data/task_board.db"
    jwt_secret: str = "task-secret"
    jwt_expire_hours: int = 12
    cookie_secure: bool = False
    agent_max_steps: int = 6
    agent_confirm_write: bool = True
    agent_confirm_ttl_minutes: int = 10

    def require_key(self) -> str:
        if not self.siliconflow_api_key:
            raise RuntimeError("缺少 SILICONFLOW_API_KEY。请复制 .env.example 为 .env 并填写密钥。")
        return self.siliconflow_api_key

    def mask_key(self) -> str:
        key = self.siliconflow_api_key
        return "(empty)" if not key else f"{key[:6]}***{key[-4:]}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
````

### 3.9 `app/db.py`

````python
"""SQLAlchemy 2.0 数据库初始化与会话依赖。"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
SessionLocal: sessionmaker | None = None
_db_note = ""


def _prepare_sqlite(url: str) -> str:
    global _db_note
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        return url
    raw_path = url.removeprefix("sqlite:///")
    path = Path(raw_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _db_note = f"数据库目录创建失败：{exc}"
        raise RuntimeError(_db_note) from exc
    return url


def init_db(settings: Settings) -> Engine:
    global _engine, SessionLocal
    if _engine is not None:
        return _engine

    url = _prepare_sqlite(settings.database_url)
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, echo=False, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = engine
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化")
    return _engine


def get_sessionmaker() -> sessionmaker:
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化")
    return SessionLocal


def get_session():
    """FastAPI 依赖：每个请求使用独立 Session。"""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def db_note() -> str:
    return _db_note
````

### 3.10 `app/models.py`

````python
from __future__ import annotations
import datetime as dt
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(20), default="")


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result_json: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
````

### 3.11 `app/schemas.py`

````python
import datetime as dt
from pydantic import BaseModel, ConfigDict, Field


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
````

### 3.12 `app/auth.py`

````python
"""bcrypt 密码、JWT、Cookie/Bearer 双通道认证与资源归属校验。"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_session
from .models import User

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, AttributeError):
        return False


def create_token(user: User, settings: Settings) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的登录凭证") from exc


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_session),
) -> User:
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")

    payload = decode_token(token, get_settings())
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证中的用户标识无效") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_hours * 3600,
        path="/",
    )


def assert_owner(row, user: User) -> None:
    if row is None or getattr(row, "owner_id", None) != user.id:
        # 返回 404，避免泄露资源是否存在。
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
````

### 3.13 `app/seed.py`

````python
import datetime as dt
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import hash_password
from .models import Project, Task, User


def seed(db: Session):
    u = db.execute(select(User).where(User.email == "demo@tasks.dev")).scalar_one_or_none()
    if not u:
        u = User(email="demo@tasks.dev", name="演示用户", password_hash=hash_password("demo1234"))
        db.add(u)
        db.flush()
    p = db.execute(select(Project).where(Project.owner_id == u.id)).scalar_one_or_none()
    if not p:
        p = Project(owner_id=u.id, name="AI 学习", color="#4f7")
        db.add(p)
        db.flush()
        db.add(
            Task(
                owner_id=u.id,
                project_id=p.id,
                title="完成 Agent 练习",
                priority="high",
                due_date=dt.date.today() + dt.timedelta(days=1),
            )
        )
    db.commit()
    return {"tasks": 1}
````

### 3.14 `app/llm.py`

````python
"""OpenAI 兼容模型调用与 Function Calling 工具定义。"""

from __future__ import annotations

import time
from typing import AsyncIterator

from openai import AsyncOpenAI

from .config import Settings


class LLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.require_key(),
            base_url=settings.openai_base_url,
        )

    async def stream(
        self,
        system: str,
        user: str,
        temperature: float = 0.8,
    ) -> AsyncIterator[tuple[str, dict]]:
        started = time.perf_counter()
        first_chunk = True
        stream = await self.client.chat.completions.create(
            model=self.settings.model_chat,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if not delta:
                continue
            if first_chunk:
                first_chunk = False
                yield "ttft", {"ms": int((time.perf_counter() - started) * 1000)}
            yield "delta", {"text": delta}
        yield "done", {"total_ms": int((time.perf_counter() - started) * 1000)}

    async def with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        temperature: float = 0.3,
    ):
        started = time.perf_counter()
        response = await self.client.chat.completions.create(
            model=self.settings.model_chat,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=temperature,
        )
        usage = getattr(response, "usage", None)
        return response.choices[0].message, {
            "total_ms": int((time.perf_counter() - started) * 1000),
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }


def tool_spec(
    name: str,
    description: str,
    properties: dict,
    required: list[str],
) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
````

### 3.15 `app/tools.py`

````python
import datetime as dt
from sqlalchemy import func, select
from .llm import tool_spec
from .models import Project, Task

SPECS = [
    tool_spec(
        "list_tasks",
        "查询任务。",
        {"status": {"type": "string"}, "project_id": {"type": "integer"}},
        [],
    ),
    tool_spec("get_task", "获取任务。", {"task_id": {"type": "integer"}}, ["task_id"]),
    tool_spec("count_tasks", "统计任务。", {"status": {"type": "string"}}, []),
    tool_spec("get_task_stats", "统计完成率和逾期。", {}, []),
    tool_spec(
        "create_task",
        "创建任务。",
        {
            "project_id": {"type": "integer"},
            "title": {"type": "string"},
            "priority": {"type": "string"},
            "due_date": {"type": "string"},
        },
        ["title"],
    ),
    tool_spec(
        "update_task",
        "更新任务。",
        {
            "task_id": {"type": "integer"},
            "status": {"type": "string"},
            "priority": {"type": "string"},
            "due_date": {"type": "string"},
        },
        ["task_id"],
    ),
]
WRITE = {"create_task", "update_task"}
WRITE_TOOLS = WRITE
READ_TOOLS = {"list_tasks", "get_task", "count_tasks", "get_task_stats"}


def validate(n, a):
    if n == "create_task":
        if not str(a.get("title") or "").strip():
            return "标题不能为空"
        if a.get("priority", "medium") not in {"low", "medium", "high"}:
            return "优先级非法"
    if (
        n == "update_task"
        and "status" in a
        and a["status"] not in {"todo", "in_progress", "blocked", "done"}
    ):
        return "状态非法"


def execute(n, a, db, uid, commit=True):
    if n == "list_tasks":
        q = select(Task).where(Task.owner_id == uid)
        if a.get("status"):
            q = q.where(Task.status == a["status"])
        if a.get("project_id"):
            q = q.where(Task.project_id == int(a["project_id"]))
        return {
            "items": [
                {
                    "id": x.id,
                    "title": x.title,
                    "status": x.status,
                    "priority": x.priority,
                    "due_date": x.due_date.isoformat() if x.due_date else None,
                }
                for x in db.execute(q).scalars()
            ]
        }
    if n == "get_task":
        x = db.execute(
            select(Task).where(Task.id == int(a["task_id"]), Task.owner_id == uid)
        ).scalar_one_or_none()
        return (
            {"error": "任务不存在"} if not x else {"id": x.id, "title": x.title, "status": x.status}
        )
    if n == "count_tasks":
        q = select(func.count(Task.id)).where(Task.owner_id == uid)
        if a.get("status"):
            q = q.where(Task.status == a["status"])
        return {"count": db.execute(q).scalar_one()}
    if n == "get_task_stats":
        rows = db.execute(select(Task).where(Task.owner_id == uid)).scalars().all()
        return {
            "total": len(rows),
            "done": sum(x.status == "done" for x in rows),
            "overdue": sum(
                bool(x.due_date and x.due_date < dt.date.today() and x.status != "done")
                for x in rows
            ),
        }
    if n in WRITE:
        e = validate(n, a)
        if e:
            return {"error": e}
    if n == "create_task":
        due = dt.date.fromisoformat(a["due_date"]) if a.get("due_date") else None
        x = Task(
            owner_id=uid,
            project_id=int(a["project_id"]) if a.get("project_id") else None,
            title=a["title"],
            priority=a.get("priority", "medium"),
            due_date=due,
        )
        db.add(x)
        db.flush()
        return {"ok": True, "task_id": x.id}
    if n == "update_task":
        x = db.execute(
            select(Task).where(Task.id == int(a["task_id"]), Task.owner_id == uid)
        ).scalar_one_or_none()
        if not x:
            return {"error": "任务不存在"}
        if "status" in a:
            x.status = a["status"]
        if "priority" in a:
            x.priority = a["priority"]
        if "due_date" in a:
            x.due_date = dt.date.fromisoformat(a["due_date"]) if a["due_date"] else None
        db.flush()
        return {"ok": True, "task_id": x.id}
    return {"error": "未知工具"}
````

### 3.16 `app/agent.py`

````python
from __future__ import annotations
import datetime as dt, json, time, uuid
from dataclasses import dataclass, field
from .models import PendingAction
from .tools import SPECS, WRITE, execute, validate

SYSTEM = "你是个人任务管理 Agent。数量、完成率和逾期必须查询真实数据库；更新任务前必须确定唯一任务。创建和更新任务必须等待用户确认。"


@dataclass
class Step:
    kind: str
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
    stopped_by: str = "answer"
    pending: list[PendingAction] = field(default_factory=list)

    @property
    def pending_writes(self):
        return self.pending


async def run_agent(llm, db, uid, q, s, max_steps=None):
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}]
    steps = []
    pending = []
    start = time.perf_counter()
    calls = 0
    limit = max(1, min(max_steps or s.agent_max_steps, s.agent_max_steps))
    for _ in range(limit):
        msg, _ = await llm.with_tools(msgs, SPECS, temperature=0.2)
        tcs = getattr(msg, "tool_calls", None) or []
        if not tcs:
            return Result(
                msg.content or "",
                steps + [Step("answer", msg.content or "")],
                calls,
                int((time.perf_counter() - start) * 1000),
                "answer",
                pending,
            )
        msgs.append(
            {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in tcs
                ],
            }
        )
        for c in tcs:
            calls += 1
            n = c.function.name
            try:
                a = json.loads(c.function.arguments or "{}")
            except:
                a = {}
            if n in WRITE and s.agent_confirm_write:
                e = validate(n, a)
                r = {"error": e} if e else None
                if not e:
                    x = PendingAction(
                        id=uuid.uuid4().hex,
                        owner_id=uid,
                        tool=n,
                        args_json=json.dumps(a, ensure_ascii=False),
                        expires_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                        + dt.timedelta(minutes=s.agent_confirm_ttl_minutes),
                    )
                    db.add(x)
                    db.commit()
                    pending.append(x)
                    r = {"action_id": x.id, "status": "pending_confirmation"}
            else:
                r = execute(n, a, db, uid)
            steps.append(Step("tool_result", json.dumps(r, ensure_ascii=False), n))
            msgs.append(
                {"role": "tool", "tool_call_id": c.id, "content": json.dumps(r, ensure_ascii=False)}
            )
    return Result(
        "达到最大步数",
        steps,
        calls,
        int((time.perf_counter() - start) * 1000),
        "max_steps",
        pending,
    )
````

### 3.17 `app/main.py`

````python
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from .config import get_settings
from .db import Base, db_note, get_engine, get_sessionmaker, init_db
from .routers import agent, auth, tasks
from .seed import seed

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    e = init_db(s)
    Base.metadata.create_all(bind=e)
    with get_sessionmaker()() as db:
        logging.info("演示数据：%s", seed(db))
    yield


app = FastAPI(title="个人任务与项目看板", version="1.0.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(tasks.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    s = get_settings()
    e = get_engine()
    return {"ok": True, "tables": sorted(inspect(e).get_table_names()), "db_note": db_note()}
````

### 3.18 `app/routers/__init__.py`

````python
"""API 路由。"""
````

### 3.19 `app/routers/auth.py`

````python
"""注册、登录、退出和当前用户。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import (
    create_token,
    current_user,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from ..config import get_settings
from ..db import get_session
from ..models import User
from ..schemas import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_session)):
    email = body.email.strip().lower()
    exists = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册")
    user = User(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_session)):
    email = body.email.strip().lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "邮箱或密码错误")
    settings = get_settings()
    token = create_token(user, settings)
    set_auth_cookie(response, token, settings)
    return {"ok": True, "token": token, "user": UserOut.model_validate(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("access_token", path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return UserOut.model_validate(user)
````

### 3.20 `app/routers/agent.py`

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

### 3.21 `app/routers/tasks.py`

````python
from fastapi import APIRouter, Depends
from ..auth import current_user
from ..db import get_session
from ..models import User
from ..tools import execute
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_all(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return execute("list_tasks", {}, db, user.id)


@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return execute("get_task_stats", {}, db, user.id)
````

### 3.22 `app/static/request.js`

````javascript
const API_BASE = '';
const DEFAULT_TIMEOUT = 30000;

export class ApiError extends Error {
  constructor(message, { kind = 'http', status = 0, retryable = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.retryable = retryable;
  }
}

export async function request(path, options = {}) {
  const {
    method = 'GET',
    body = null,
    headers = {},
    timeout = DEFAULT_TIMEOUT,
    retries = 0,
    signal = null,
  } = options;

  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const onAbort = () => controller.abort();
    if (signal?.aborted) controller.abort();
    else signal?.addEventListener('abort', onAbort, { once: true });

    try {
      const response = await fetch(API_BASE + path, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: body == null ? null : JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const payload = await response.json();
          const detail = payload.detail || payload.error || payload.message;
          message = typeof detail === 'string' ? detail : JSON.stringify(detail);
        } catch {
          // 保留状态码错误。
        }
        throw new ApiError(message, {
          status: response.status,
          retryable: response.status >= 500,
        });
      }

      if (response.status === 204) return null;
      return await response.json();
    } catch (error) {
      if (error instanceof ApiError) {
        lastError = error;
      } else if (error.name === 'AbortError') {
        lastError = new ApiError('请求已取消或超时', { kind: 'abort' });
      } else {
        lastError = new ApiError('网络异常，请检查服务是否启动', {
          kind: 'network',
          retryable: true,
        });
      }

      if (attempt < retries && lastError.retryable) {
        await new Promise(resolve => setTimeout(resolve, 400 * 2 ** attempt));
        continue;
      }
      throw lastError;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
    }
  }
  throw lastError;
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char]);
}
````

### 3.23 `app/static/index.html`

````html
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>个人任务与项目看板</title><style>body{margin:0;background:linear-gradient(135deg,#f5f0e8,#eaf2ec);font-family:"PingFang SC","Microsoft YaHei",sans-serif;color:#1d2a23}.wrap{width:min(1000px,calc(100% - 24px));margin:24px auto}.card{background:#fffdf8;border:1px solid #ddd6c9;border-radius:18px;box-shadow:0 16px 45px #26342c16;padding:18px;margin-bottom:15px}.top{display:flex;justify-content:space-between;align-items:center}.brand{font:700 23px Georgia,"Songti SC",serif}.muted{color:#6b766e;font-size:13px}.hidden{display:none}.chat{height:300px;overflow:auto;background:#f7f4ed;border-radius:11px;padding:8px}.msg{max-width:88%;padding:10px 12px;border-radius:12px;white-space:pre-wrap;line-height:1.6;margin:8px 0}.user{margin-left:auto;background:#3f755b;color:#fff}.assistant{background:#fff;border:1px solid #ddd6c9}textarea,input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #ddd6c9;border-radius:10px;font:inherit}textarea{min-height:90px}.btn{border:0;border-radius:10px;padding:10px 14px;background:#3f755b;color:#fff;font-weight:700;cursor:pointer}.pending{margin-top:10px;padding:10px;border:1px solid #ddc49c;border-radius:10px;background:#fff8e9}.pending pre{white-space:pre-wrap;max-height:150px;overflow:auto;font-size:11px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}.toast{position:fixed;right:18px;bottom:18px;padding:11px 14px;background:#243027;color:#fff;border-radius:10px}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style></head><body><main id="auth" class="wrap"><section class="card"><div class="brand">个人任务与项目看板</div><p class="muted">课程资料 · 学习计划 · 练习与错题</p><p>邮箱 <input id="email" value="demo@course.dev"></p><p>密码 <input id="password" type="password" value="demo1234"></p><button id="login" class="btn">登录</button><p class="muted">demo@course.dev / demo1234</p></section></main><main id="app" class="wrap hidden"><div class="card top"><div><div class="brand">个人任务与项目看板</div><div class="muted">Agent 基于真实课程资料回答</div></div><button id="logout" class="btn">退出</button></div><div class="grid"><section class="card"><h2>学习与练习</h2><div id="messages" class="chat"><div class="msg assistant">你可以查询课程资料、学习进度、错题，也能保存学习计划或练习结果。写操作会先请你确认。</div></div><textarea id="question" placeholder="例如：查询 Python 基础，并解释缩进规则"></textarea><button id="send" class="btn">发送</button><div id="pending"></div><details id="trace"></details></section><section class="card"><h2>学习进度</h2><div id="progress" class="muted"></div></section></div></main><div id="toast" class="toast hidden"></div><script type="module">import{request}from'/static/request.js';const $=s=>document.querySelector(s);function toast(m){$('#toast').textContent=m;$('#toast').classList.remove('hidden');setTimeout(()=>$('#toast').classList.add('hidden'),2500)}async function load(){let p=await request('/api/tasks/stats');$('#progress').innerHTML=`任务 ${p.total} · 完成 ${p.done} · 逾期 ${p.overdue}`}async function login(){try{await request('/api/auth/login',{method:'POST',body:{email:$('#email').value,password:$('#password').value}});$('#auth').classList.add('hidden');$('#app').classList.remove('hidden');await load()}catch(e){toast(e.message)}}function msg(r,t){let n=document.createElement('div');n.className='msg '+r;n.textContent=t;$('#messages').appendChild(n);$('#messages').scrollTop=$('#messages').scrollHeight}function renderPending(rows){$('#pending').innerHTML=(rows||[]).map(x=>`<div class="pending"><strong>${x.tool}</strong> ${x.id}<pre>${JSON.stringify(x.args,null,2)}</pre><button class="btn" data-id="${x.id}">确认写入</button></div>`).join('');$('#pending').querySelectorAll('[data-id]').forEach(b=>b.onclick=async()=>{try{await request('/api/agent/confirm',{method:'POST',body:{action_id:b.dataset.id}});toast('写入完成');$('#pending').innerHTML='';await load()}catch(e){toast(e.message)}})}async function send(){let q=$('#question').value.trim();if(!q)return;msg('user',q);$('#question').value='';try{let r=await request('/api/agent/run',{method:'POST',body:{question:q,max_steps:6},timeout:60000});msg('assistant',r.answer);$('#trace').innerHTML=`<summary>调用轨迹 ${r.tool_calls} 次</summary>${r.steps.map(s=>`<div>${s.kind} ${s.tool||''}<br>${s.content}</div>`).join('')}`;renderPending(r.pending_writes)}catch(e){msg('assistant','失败：'+e.message)}}$('#login').onclick=login;$('#send').onclick=send;$('#logout').onclick=async()=>{await request('/api/auth/logout',{method:'POST'});location.reload()};request('/api/auth/me').then(async()=>{$('#auth').classList.add('hidden');$('#app').classList.remove('hidden');await load()}).catch(()=>{});</script></body></html>
````

### 3.24 `tests/__init__.py`

````python
"""测试包。"""
````

### 3.25 `tests/test_app.py`

````python
import json, os, tempfile, unittest
from types import SimpleNamespace

td = tempfile.mkdtemp(prefix="task-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{td}/t.db", SILICONFLOW_API_KEY="test", JWT_SECRET="test"
)
from fastapi.testclient import TestClient
import app.routers.agent as ar
from app.main import app


class Fake:
    def __init__(self):
        self.n = 0

    async def with_tools(self, messages, tools, temperature=0.2):
        self.n += 1
        if self.n == 1:
            c = SimpleNamespace(
                id="c",
                function=SimpleNamespace(
                    name="create_task",
                    arguments=json.dumps(
                        {"project_id": 1, "title": "复习 Agent", "priority": "high"},
                        ensure_ascii=False,
                    ),
                ),
            )
            return SimpleNamespace(content=None, tool_calls=[c]), {}
        return SimpleNamespace(content="任务待确认", tool_calls=None), {}


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def login(self):
        r = self.c.post("/api/auth/login", json={"email": "demo@tasks.dev", "password": "demo1234"})
        self.assertEqual(r.status_code, 200)

    def test_01_auth_stats(self):
        self.assertEqual(self.c.get("/api/tasks/stats").status_code, 401)
        self.login()
        self.assertEqual(self.c.get("/api/tasks/stats").json()["total"], 1)

    def test_02_task_confirmation(self):
        self.login()
        f = Fake()
        old = ar._llm
        ar._llm = lambda: f
        try:
            r = self.c.post("/api/agent/run", json={"question": "创建复习任务"})
        finally:
            ar._llm = old
        p = r.json()["pending_writes"]
        self.assertEqual(len(p), 1)
        a = self.c.post("/api/agent/confirm", json={"action_id": p[0]["id"]})
        b = self.c.post("/api/agent/confirm", json={"action_id": p[0]["id"]})
        self.assertEqual(a.json(), b.json())

    def test_03_cross_user(self):
        self.login()
        s = os.urandom(3).hex()
        self.c.post(
            "/api/auth/register",
            json={"email": f"x{s}@x.com", "name": "X", "password": "password1"},
        )
        self.c.post("/api/auth/login", json={"email": f"x{s}@x.com", "password": "password1"})
        self.assertEqual(self.c.get("/api/tasks/stats").json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
````

## 逐文件文档

| # | 源码 | 文档 |
|---|---|---|
| 01 | `requirements.txt` | [FILE_01_requirements_txt.md](./FILE_01_requirements_txt.md) |
| 02 | `.env.example` | [FILE_02__env_example.md](./FILE_02__env_example.md) |
| 03 | `.gitignore` | [FILE_03__gitignore.md](./FILE_03__gitignore.md) |
| 04 | `.dockerignore` | [FILE_04__dockerignore.md](./FILE_04__dockerignore.md) |
| 05 | `Dockerfile` | [FILE_05_Dockerfile.md](./FILE_05_Dockerfile.md) |
| 06 | `docker-compose.yml` | [FILE_06_docker-compose_yml.md](./FILE_06_docker-compose_yml.md) |
| 07 | `app/__init__.py` | [FILE_07___init___py.md](./FILE_07___init___py.md) |
| 08 | `app/config.py` | [FILE_08_config_py.md](./FILE_08_config_py.md) |
| 09 | `app/db.py` | [FILE_09_db_py.md](./FILE_09_db_py.md) |
| 10 | `app/models.py` | [FILE_10_models_py.md](./FILE_10_models_py.md) |
| 11 | `app/schemas.py` | [FILE_11_schemas_py.md](./FILE_11_schemas_py.md) |
| 12 | `app/auth.py` | [FILE_12_auth_py.md](./FILE_12_auth_py.md) |
| 13 | `app/seed.py` | [FILE_13_seed_py.md](./FILE_13_seed_py.md) |
| 14 | `app/llm.py` | [FILE_14_llm_py.md](./FILE_14_llm_py.md) |
| 15 | `app/tools.py` | [FILE_15_tools_py.md](./FILE_15_tools_py.md) |
| 16 | `app/agent.py` | [FILE_16_agent_py.md](./FILE_16_agent_py.md) |
| 17 | `app/main.py` | [FILE_17_main_py.md](./FILE_17_main_py.md) |
| 18 | `app/routers/__init__.py` | [FILE_18___init___py.md](./FILE_18___init___py.md) |
| 19 | `app/routers/auth.py` | [FILE_19_auth_py.md](./FILE_19_auth_py.md) |
| 20 | `app/routers/agent.py` | [FILE_20_agent_py.md](./FILE_20_agent_py.md) |
| 21 | `app/routers/tasks.py` | [FILE_21_tasks_py.md](./FILE_21_tasks_py.md) |
| 22 | `app/static/request.js` | [FILE_22_request_js.md](./FILE_22_request_js.md) |
| 23 | `app/static/index.html` | [FILE_23_index_html.md](./FILE_23_index_html.md) |
| 24 | `tests/__init__.py` | [FILE_24___init___py.md](./FILE_24___init___py.md) |
| 25 | `tests/test_app.py` | [FILE_25_test_app_py.md](./FILE_25_test_app_py.md) |
