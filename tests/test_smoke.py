"""端到端冒烟（付佳宝 D3 卡 · 程熙代补 2026-11-15）：

登录 → 页面建任务 → 拖拽 → Agent 创建（Fake LLM）→ 确认写入 → 新会话刷新后数据仍在。

全离线：Fake LLM 注入，不联网、不消耗 API 额度（统一开发规范 §8）。
"""

import datetime as dt
import json
import os
import unittest
import uuid
from types import SimpleNamespace

# 模块顶部先设 DATABASE_URL 再 import app，自带临时库（规范 §8）
_tmp = os.path.join(".pytest_cache", "smoke-tests", uuid.uuid4().hex[:8])
os.makedirs(_tmp, exist_ok=True)
os.environ.update(
    DATABASE_URL=f"sqlite:///{_tmp}/t.db",
    SILICONFLOW_API_KEY="test-key",
    JWT_SECRET="test-secret",
)

from fastapi.testclient import TestClient

import app.routers.agent as agent_router
from app.main import app

DEMO = {"email": "demo@tasks.dev", "password": "demo1234"}
DUE = (dt.date.today() + dt.timedelta(days=2)).isoformat()


def _call(name: str, args: dict):
    fn = SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))
    return SimpleNamespace(
        content=None, tool_calls=[SimpleNamespace(id="c1", function=fn)]
    )


def _say(text: str):
    return SimpleNamespace(content=text, tool_calls=None)


class FakeLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def with_tools(self, messages, tools, temperature=0.2):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return item, {}


class SmokeFlowTest(unittest.TestCase):
    def test_full_flow(self):
        with TestClient(app) as c:
            # 1) 登录
            r = c.post("/api/auth/login", json=DEMO)
            self.assertEqual(r.status_code, 200, r.text)

            # 2) 页面建任务（等价看板「+」表单提交）
            r = c.post(
                "/api/tasks",
                json={
                    "title": "冒烟-页面建任务",
                    "project_id": 1,
                    "due_date": DUE,
                    "priority": "medium",
                },
            )
            self.assertIn(r.status_code, (200, 201), r.text)
            page_task_id = r.json()["id"]

            # 3) 拖拽（等价 PATCH：todo → in_progress）
            r = c.patch(f"/api/tasks/{page_task_id}", json={"status": "in_progress"})
            self.assertEqual(r.status_code, 200, r.text)

            # 4) Agent 创建（Fake LLM 注入，离线）
            fake = FakeLLM(
                [
                    _call(
                        "create_task",
                        {
                            "project_id": 1,
                            "title": "冒烟-Agent建任务",
                            "due_date": DUE,
                            "priority": "high",
                        },
                    ),
                    _say("已准备，请确认"),
                ]
            )
            original = agent_router._llm
            agent_router._llm = lambda: fake
            try:
                r = c.post("/api/agent/run", json={"question": "新建一个任务"})
            finally:
                agent_router._llm = original
            self.assertEqual(r.status_code, 200, r.text)
            pending = r.json()["pending_writes"]
            self.assertEqual(len(pending), 1, r.text)
            self.assertEqual(pending[0]["tool"], "create_task")
            # 确认前不写业务表
            titles = [t["title"] for t in c.get("/api/tasks").json()["items"]]
            self.assertNotIn("冒烟-Agent建任务", titles)

            # 5) 确认写入
            r = c.post("/api/agent/confirm", json={"action_id": pending[0]["id"]})
            self.assertEqual(r.status_code, 200, r.text)

            # 6) 模拟刷新：新会话重新登录拉取，两条任务与拖拽状态仍在
            with TestClient(app) as c2:
                self.assertEqual(c2.post("/api/auth/login", json=DEMO).status_code, 200)
                items = c2.get("/api/tasks").json()["items"]
                by_id = {t["id"]: t for t in items}
                self.assertEqual(by_id[page_task_id]["status"], "in_progress")
                self.assertIn(
                    "冒烟-Agent建任务",
                    [t["title"] for t in items],
                    "确认后的任务刷新后应仍在",
                )
