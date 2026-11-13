# 文件开发记录：`tests/test_app.py`

> 目标文件：`tests/test_app.py`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

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

验证：3 个测试通过。
