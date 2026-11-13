"""任务接口测试（程熙 / D1）：≥8 例，覆盖需求 10.7 的四类——
日期格式错误、非法状态、越权（跨用户/跨项目）、指派校验与分页截断。

约定（统一开发规范 §8）：
- 模块顶部先设 DATABASE_URL 再 import app，自带临时库；
- 全部用相对日期构造，禁止写死绝对日期；
- 身份用 Bearer 头显式携带，避免多用户共用 Cookie 互相覆盖。
"""

import datetime as dt
import os
import tempfile
import unittest

_td = tempfile.mkdtemp(prefix="task-api-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_td}/t.db",
    SILICONFLOW_API_KEY="test",
    JWT_SECRET="test",
)

from fastapi.testclient import TestClient

from app.db import get_sessionmaker
from app.main import app
from app.models import Project, ProjectMember


class TaskApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    # ---------- helpers ----------
    def _login(self, tag: str) -> tuple[str, int]:
        """注册+登录，返回 (token, user_id)。"""
        email = f"{tag}{os.urandom(3).hex()}@t.dev"
        r = self.c.post(
            "/api/auth/register",
            json={"email": email, "name": tag, "password": "password1"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        r = self.c.post(
            "/api/auth/login", json={"email": email, "password": "password1"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"], r.json()["user"]["id"]

    @staticmethod
    def _h(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _make_project(self, token: str, uid: int, name: str = "P") -> int:
        """项目接口属戴罗轩，尚未交付——测试里直插 DB 建项目+owner 成员。"""
        with get_sessionmaker()() as db:
            p = Project(owner_id=uid, name=name, color="#4f7")
            db.add(p)
            db.flush()
            db.add(ProjectMember(project_id=p.id, user_id=uid, role="owner"))
            db.commit()
            return p.id

    @staticmethod
    def _add_member(project_id: int, uid: int, role: str = "member") -> None:
        with get_sessionmaker()() as db:
            db.add(ProjectMember(project_id=project_id, user_id=uid, role=role))
            db.commit()

    def _create(self, token: str, **kw) -> dict:
        body = {"title": kw.pop("title", "测试任务")}
        body.update(kw)
        r = self.c.post("/api/tasks", json=body, headers=self._h(token))
        self.assertIn(r.status_code, (201,), r.text)
        return r.json()

    # ---------- 用例 ----------
    def test_01_list_requires_auth(self):
        self.assertEqual(self.c.get("/api/tasks").status_code, 401)

    def test_02_create_missing_title(self):
        tok, _ = self._login("a")
        r = self.c.post("/api/tasks", json={"priority": "high"}, headers=self._h(tok))
        self.assertEqual(r.status_code, 422)

    def test_03_create_bad_priority(self):
        tok, _ = self._login("b")
        r = self.c.post(
            "/api/tasks",
            json={"title": "x", "priority": "urgent"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 422)

    def test_04_create_bad_due_date(self):
        """日期格式错误（需求 10.7）：非 ISO 字符串必须被服务端拒绝。"""
        tok, _ = self._login("c")
        r = self.c.post(
            "/api/tasks",
            json={"title": "x", "due_date": "not-a-date"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 422)
        r = self.c.post(
            "/api/tasks",
            json={"title": "x", "due_date": "2026-13-99"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 422)

    def test_05_create_and_list_with_filters(self):
        tok, _ = self._login("d")
        marker = f"筛选-{os.urandom(2).hex()}"
        created = self._create(
            tok,
            title=marker,
            priority="high",
            due_date=(dt.date.today() + dt.timedelta(days=1)).isoformat(),
            tags=["python", "python", "  测试  "],
        )
        self.assertEqual(created["priority"], "high")
        self.assertEqual(created["tags"], ["python", "测试"])  # 去重+去空白

        r = self.c.get(f"/api/tasks?q={marker}", headers=self._h(tok))
        data = r.json()
        self.assertEqual(data["total"], 1)
        self.assertFalse(data["truncated"])
        self.assertEqual(data["items"][0]["id"], created["id"])

        r = self.c.get("/api/tasks?priority=high&due=week", headers=self._h(tok))
        self.assertTrue(any(x["id"] == created["id"] for x in r.json()["items"]))

    def test_06_pagination_truncated(self):
        tok, _ = self._login("e")
        marker = f"分页-{os.urandom(2).hex()}"
        for i in range(3):
            self._create(tok, title=f"{marker}-{i}")
        r = self.c.get(f"/api/tasks?q={marker}&limit=1", headers=self._h(tok))
        data = r.json()
        self.assertEqual(data["total"], 3)
        self.assertEqual(len(data["items"]), 1)
        self.assertTrue(data["truncated"])  # 超出 limit 必须说明截断（需求 4.2）

    def test_07_cross_user_isolation(self):
        """越权（需求 10.7 / 验收 6）：他人任务不可见、不可改、不可删，一律 404。"""
        tok_a, _ = self._login("owner-a")
        tok_b, _ = self._login("intruder-b")
        created = self._create(tok_a, title=f"私密-{os.urandom(2).hex()}")

        r = self.c.get(f"/api/tasks?q={created['title']}", headers=self._h(tok_b))
        self.assertEqual(r.json()["total"], 0)
        self.assertEqual(
            self.c.patch(
                f"/api/tasks/{created['id']}",
                json={"status": "done"},
                headers=self._h(tok_b),
            ).status_code,
            404,
        )
        self.assertEqual(
            self.c.delete(
                f"/api/tasks/{created['id']}", headers=self._h(tok_b)
            ).status_code,
            404,
        )

    def test_08_project_visibility(self):
        """非成员访问项目任务 404/空（验收 8），成员可见。"""
        tok_o, uid_o = self._login("proj-o")
        tok_m, uid_m = self._login("proj-m")
        tok_x, _ = self._login("proj-x")
        pid = self._make_project(tok_o, uid_o, name="可见性项目")
        self._add_member(pid, uid_m)
        created = self._create(
            tok_o, title=f"项目任务-{os.urandom(2).hex()}", project_id=pid
        )

        # 成员能看到
        r = self.c.get(f"/api/tasks?project_id={pid}", headers=self._h(tok_m))
        self.assertTrue(any(x["id"] == created["id"] for x in r.json()["items"]))
        # 非成员：列表为空，直接写 404
        r = self.c.get(f"/api/tasks?project_id={pid}", headers=self._h(tok_x))
        self.assertEqual(r.json()["total"], 0)
        self.assertEqual(
            self.c.patch(
                f"/api/tasks/{created['id']}",
                json={"priority": "low"},
                headers=self._h(tok_x),
            ).status_code,
            404,
        )
        # 非成员往该项目塞任务 → 404
        r = self.c.post(
            "/api/tasks",
            json={"title": "偷塞", "project_id": pid},
            headers=self._h(tok_x),
        )
        self.assertEqual(r.status_code, 404)

    def test_09_assign_validation(self):
        """指派非项目成员被拒 422（验收 9）；成员指派成功。"""
        tok_o, uid_o = self._login("asg-o")
        _tok_m, uid_m = self._login("asg-m")
        _tok_x, uid_x = self._login("asg-x")
        pid = self._make_project(tok_o, uid_o, name="指派项目")
        self._add_member(pid, uid_m)
        created = self._create(
            tok_o, title=f"指派-{os.urandom(2).hex()}", project_id=pid
        )

        r = self.c.patch(
            f"/api/tasks/{created['id']}",
            json={"assignee_id": uid_x},
            headers=self._h(tok_o),
        )
        self.assertEqual(r.status_code, 422, r.text)
        r = self.c.patch(
            f"/api/tasks/{created['id']}",
            json={"assignee_id": uid_m},
            headers=self._h(tok_o),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["assignee_id"], uid_m)

    def test_10_today_overdue_done_rate(self):
        """今日待办/逾期/完成率（缺口 5），全部相对日期。"""
        tok, _ = self._login("today-u")
        today = dt.date.today()
        t1 = self._create(
            tok, title=f"今到期-{os.urandom(2).hex()}", due_date=today.isoformat()
        )
        t2 = self._create(
            tok,
            title=f"已逾期-{os.urandom(2).hex()}",
            due_date=(today - dt.timedelta(days=1)).isoformat(),
        )

        r = self.c.get("/api/tasks/today", headers=self._h(tok)).json()
        self.assertIn(t1["id"], [x["id"] for x in r["today"]])
        self.assertIn(t2["id"], [x["id"] for x in r["overdue"]])
        self.assertGreaterEqual(r["done_rate"], 0.0)
        self.assertLessEqual(r["done_rate"], 1.0)

        # 状态改 done：进完成计数、清出今日/逾期、写完成时间
        resp = self.c.patch(
            f"/api/tasks/{t1['id']}", json={"status": "done"}, headers=self._h(tok)
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.json()["completed_at"])
        r = self.c.get("/api/tasks/today", headers=self._h(tok)).json()
        self.assertNotIn(t1["id"], [x["id"] for x in r["today"]])

    def test_11_invalid_status_rejected(self):
        """非法状态（需求 10.7）。"""
        tok, _ = self._login("st-u")
        created = self._create(tok)
        r = self.c.patch(
            f"/api/tasks/{created['id']}",
            json={"status": "doing"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 422)

    def test_12_delete_rules(self):
        """删除最严：项目任务成员（含创建者）404，owner 角色 204（§4.3）。"""
        tok_o, uid_o = self._login("del-o")
        tok_m, uid_m = self._login("del-m")
        pid = self._make_project(tok_o, uid_o, name="删除项目")
        self._add_member(pid, uid_m)
        created = self._create(
            tok_m, title=f"成员建-{os.urandom(2).hex()}", project_id=pid
        )

        r = self.c.delete(f"/api/tasks/{created['id']}", headers=self._h(tok_m))
        self.assertEqual(r.status_code, 404)  # member 不可删项目任务
        r = self.c.delete(f"/api/tasks/{created['id']}", headers=self._h(tok_o))
        self.assertEqual(r.status_code, 204)  # owner 角色可删
        r = self.c.get(f"/api/tasks?q={created['title']}", headers=self._h(tok_o))
        self.assertEqual(r.json()["total"], 0)


if __name__ == "__main__":
    unittest.main()
