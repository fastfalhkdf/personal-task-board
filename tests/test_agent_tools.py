"""Agent 工具与写确认用例（郑伟健 · 设计方案 §6）。

全部离线：用 Fake LLM 注入脚本化的工具调用，不联网、不消耗额度。
覆盖：三件套强制、before 快照、pending 可列出、cancel 后不可确认、
未定位任务的更新不执行、重复确认幂等、项目可见性、history 透传。
"""

import json
import os
import unittest
import uuid
from types import SimpleNamespace

# 本机 TEMP 路径含中文时 tempfile 会回退到 cwd，把临时库丢进仓库根；
# 这里显式建在用户本地目录下，既不进仓库也不依赖 TEMP。
# 本机 TEMP / LocalAppData 不可写、且 tempfile 会因中文路径回退到 cwd；
# 统一放到 .pytest_cache 下（已 gitignore），既不污染工作区也不越界写盘。
_tmp = os.path.join(".pytest_cache", "agent-tests", uuid.uuid4().hex[:8])
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


def call(name: str, args: dict, call_id: str = "c1"):
    """构造一条「模型要调工具」的返回。"""
    fn = SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False))
    return SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id=call_id, function=fn)])


def say(text: str):
    """构造一条「模型直接回答」的返回。"""
    return SimpleNamespace(content=text, tool_calls=None)


class FakeLLM:
    """按脚本顺序返回；用完后一直返回最后一条。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def with_tools(self, messages, tools, temperature=0.2):
        item = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return item, {}


class AgentToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def setUp(self):
        self.client.post("/api/auth/logout")
        resp = self.client.post("/api/auth/login", json=DEMO)
        self.assertEqual(resp.status_code, 200)
        # 用例共用一个库，先把上一条留下的待确认清掉，保证断言从 0 开始
        for item in self.client.get("/api/agent/pending").json()["items"]:
            self.client.post("/api/agent/cancel", json={"action_id": item["id"]})

    def _run(self, script, question="测试问题", **body):
        fake = FakeLLM(script)
        original = agent_router._llm
        agent_router._llm = lambda: fake
        try:
            resp = self.client.post("/api/agent/run", json={"question": question, **body})
        finally:
            agent_router._llm = original
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def _task_total(self) -> int:
        return self.client.get("/api/tasks").json()["total"]

    def _tool_results(self, payload) -> list[dict]:
        return [
            json.loads(step["content"])
            for step in payload["steps"]
            if step["kind"] == "tool_result"
        ]

    # ---- 1. 三件套缺一即被拒 ----
    def test_01_create_requires_title_project_due(self):
        before = self._task_total()
        payload = self._run([call("create_task", {"project_id": 1, "title": "缺日期"}), say("好")])
        results = self._tool_results(payload)
        self.assertTrue(results[0].get("error"), results)
        self.assertIn("截止日期", results[0]["error"])
        self.assertEqual(payload["pending_writes"], [])
        self.assertEqual(self._task_total(), before)
        self.assertEqual(self.client.get("/api/agent/pending").json()["total"], 0)

    # ---- 2. 三件套齐全：只落待确认，不写业务表 ----
    def test_02_create_pending_without_writing_task(self):
        before = self._task_total()
        payload = self._run(
            [
                call(
                    "create_task",
                    {
                        "project_id": 1,
                        "title": "写 Agent 用例",
                        "due_date": "2026-12-01",
                        "priority": "high",
                    },
                ),
                say("已准备，请确认"),
            ]
        )
        pending = payload["pending_writes"]
        self.assertEqual(len(pending), 1, payload)
        self.assertEqual(pending[0]["tool"], "create_task")
        self.assertEqual(pending[0]["before"], {})
        self.assertEqual(pending[0]["after"]["title"], "写 Agent 用例")
        self.assertEqual(self._task_total(), before, "确认前不允许写业务表")

    # ---- 3. update_task 拦截时带 before 快照 ----
    def test_03_update_carries_before_snapshot(self):
        tasks = self.client.get("/api/tasks").json()["items"]
        task = tasks[0]
        payload = self._run(
            [
                call("update_task", {"task_id": task["id"], "status": "in_progress"}),
                say("已准备，请确认"),
            ]
        )
        pending = payload["pending_writes"][0]
        self.assertEqual(pending["before"]["id"], task["id"])
        self.assertEqual(pending["before"]["status"], task["status"])
        self.assertEqual(pending["after"]["status"], "in_progress")
        self.assertNotEqual(pending["before"]["status"], pending["after"]["status"])

        listed = self.client.get("/api/agent/pending").json()
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["items"][0]["id"], pending["id"])

    # ---- 4. cancel 之后不能再 confirm ----
    def test_04_cancel_blocks_confirm(self):
        payload = self._run(
            [
                call("create_task", {"project_id": 1, "title": "要被取消", "due_date": "2026-12-02"}),
                say("请确认"),
            ]
        )
        action_id = payload["pending_writes"][0]["id"]
        cancel = self.client.post("/api/agent/cancel", json={"action_id": action_id})
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(cancel.json()["status"], "cancelled")
        again = self.client.post("/api/agent/cancel", json={"action_id": action_id})
        self.assertEqual(again.json()["status"], "cancelled")
        confirm = self.client.post("/api/agent/confirm", json={"action_id": action_id})
        self.assertEqual(confirm.status_code, 409)
        self.assertEqual(self.client.get("/api/agent/pending").json()["total"], 0)

    # ---- 5. 未定位到任务时不执行、不产生待确认 ----
    def test_05_update_unknown_task_is_rejected(self):
        payload = self._run(
            [call("update_task", {"task_id": 999999, "status": "done"}), say("没找到")]
        )
        results = self._tool_results(payload)
        self.assertTrue(results[0].get("error"), results)
        self.assertEqual(payload["pending_writes"], [])

    # ---- 6. 重复确认幂等，且结果带 diff ----
    def test_06_confirm_is_idempotent_with_diff(self):
        payload = self._run(
            [
                call("create_task", {"project_id": 1, "title": "幂等任务", "due_date": "2026-12-03"}),
                say("请确认"),
            ]
        )
        action_id = payload["pending_writes"][0]["id"]
        first = self.client.post("/api/agent/confirm", json={"action_id": action_id})
        second = self.client.post("/api/agent/confirm", json={"action_id": action_id})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertIn("diff", first.json()["result"])
        # 用例跑在共享库里，确认产生的任务用完即删，避免影响其他模块的计数断言
        task_id = first.json()["result"].get("task_id")
        if task_id:
            self.client.delete(f"/api/tasks/{task_id}")

    # ---- 7. 项目可见性：别人的项目不可见 ----
    def test_07_project_visibility_is_scoped(self):
        other = f"u{uuid.uuid4().hex[:8]}@example.com"
        self.client.post(
            "/api/auth/register", json={"email": other, "name": "旁人", "password": "password1"}
        )
        self.client.post("/api/auth/login", json={"email": other, "password": "password1"})

        payload = self._run([call("list_projects", {}), say("列表")])
        projects = self._tool_results(payload)[0]["items"]
        self.assertEqual(projects, [], "新用户不该看到别人的项目")

        payload = self._run([call("list_members", {"project_id": 1}), say("成员")])
        result = self._tool_results(payload)[0]
        self.assertTrue(result.get("error"), "非成员查成员列表必须报错")

    # ---- 8. history 被接受且不影响收敛 ----
    def test_08_history_is_accepted(self):
        history = [
            {"role": "user", "content": "帮我建个任务"},
            {"role": "assistant", "content": "好的，标题和截止日期是什么？"},
        ]
        payload = self._run([say("收到")], question="那就明天", history=history)
        self.assertEqual(payload["answer"], "收到")
        self.assertEqual(payload["stopped_by"], "answer")

    # ---- 9. 越权项目在生成待确认前就被兜底 ----
    def test_09_foreign_project_rejected_before_pending(self):
        payload = self._run(
            [
                call(
                    "create_task",
                    {"project_id": 999999, "title": "越权任务", "due_date": "2026-12-05"},
                ),
                say("好"),
            ]
        )
        results = self._tool_results(payload)
        self.assertTrue(results[0].get("error"), results)
        self.assertIn("项目", results[0]["error"])
        self.assertEqual(payload["pending_writes"], [], "越权项目不该生成待确认")



if __name__ == "__main__":
    unittest.main(verbosity=2)






