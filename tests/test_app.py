"""原 3 例收编 pytest（设计方案 §2.4 决定三 / §10，付佳宝 D1 上午）。

沿用既有两条约定（规范 §8）：
1. 必须在 import app 之前设好 DATABASE_URL 等 env，各测试自带临时库，不依赖本地 data/task_board.db；
2. Agent 用例用 Fake LLM 注入 ar._llm，全程离线、不消耗 API 额度。
"""

import json
import os
import tempfile
from types import SimpleNamespace

# ---- 环境必须先于 app 导入设置（规范 §8 第 1 条）----
_tmpdir = tempfile.mkdtemp(prefix="task-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmpdir}/t.db", SILICONFLOW_API_KEY="test", JWT_SECRET="test"
)

import pytest
from fastapi.testclient import TestClient

import app.routers.agent as ar
from app.main import app


class FakeLLM:
    """第一次调用返回 create_task 的 tool_calls，其余返回普通回答。"""

    def __init__(self):
        self.calls = 0

    async def with_tools(self, messages, tools, temperature=0.2):
        self.calls += 1
        if self.calls == 1:
            call = SimpleNamespace(
                id="c",
                function=SimpleNamespace(
                    name="create_task",
                    arguments=json.dumps(
                        {
                            "project_id": 1,
                            "title": "复习 Agent",
                            "priority": "high",
                            "due_date": "2026-12-31",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            return SimpleNamespace(content=None, tool_calls=[call]), {}
        return SimpleNamespace(content="任务待确认", tool_calls=None), {}


@pytest.fixture()
def client():
    with TestClient(app) as session:
        yield session


@pytest.fixture()
def login(client):
    def _login():
        response = client.post(
            "/api/auth/login", json={"email": "demo@tasks.dev", "password": "demo1234"}
        )
        assert response.status_code == 200

    return _login


@pytest.fixture()
def fake_llm():
    fake = FakeLLM()
    original = ar._llm
    ar._llm = lambda: fake
    yield fake
    ar._llm = original


def test_auth_required_then_demo_login(client, login):
    """未登录 401；demo 登录后统计条可见（用例顺序敏感：本例定义在最前）。"""
    assert client.get("/api/tasks/stats").status_code == 401
    login()
    assert client.get("/api/tasks/stats").json()["total"] == 1


def test_agent_write_confirmation_idempotent(client, login, fake_llm):
    """创建请求只进 pending；同一 action_id 重复确认结果一致（验收第 5 条）。"""
    login()
    response = client.post("/api/agent/run", json={"question": "创建复习任务"})
    pending = response.json()["pending_writes"]
    assert len(pending) == 1
    first = client.post("/api/agent/confirm", json={"action_id": pending[0]["id"]})
    second = client.post("/api/agent/confirm", json={"action_id": pending[0]["id"]})
    assert first.json() == second.json()


def test_cross_user_isolation(client, login):
    """他人任务对自己不可见：新注册用户统计为 0（验收第 6 条）。"""
    login()
    suffix = os.urandom(3).hex()
    email = f"x{suffix}@x.com"
    client.post("/api/auth/register", json={"email": email, "name": "X", "password": "password1"})
    client.post("/api/auth/login", json={"email": email, "password": "password1"})
    assert client.get("/api/tasks/stats").json()["total"] == 0
