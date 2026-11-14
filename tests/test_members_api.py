"""项目/成员接口测试（戴罗轩 / D1）：≥5 例，覆盖设计验收 8、9 与项目 CRUD。

约定（统一开发规范 §8）：
- 模块顶部先设 DATABASE_URL 再 import app，自带临时库；
- 全部用相对数据，不依赖 data/task_board.db；
- 身份用 Bearer 头显式携带，避免多用户 Cookie 互相覆盖。
"""

import datetime as dt
import os
import tempfile
import unittest

_td = tempfile.mkdtemp(prefix="member-api-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{_td}/t.db",
    SILICONFLOW_API_KEY="test",
    JWT_SECRET="test",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class MemberApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.c = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def _login(self, tag: str) -> tuple[str, int, str]:
        email = f"{tag}{os.urandom(3).hex()}@t.dev"
        r = self.c.post(
            "/api/auth/register",
            json={"email": email, "name": tag, "password": "password1"},
        )
        self.assertEqual(r.status_code, 201, r.text)
        r = self.c.post("/api/auth/login", json={"email": email, "password": "password1"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"], r.json()["user"]["id"], email

    @staticmethod
    def _h(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _project(self, token: str, name: str = "项目") -> dict:
        r = self.c.post(
            "/api/projects",
            json={"name": name, "color": "#4f7", "description": "测试项目"},
            headers=self._h(token),
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def _invite(self, token: str, project_id: int, email: str):
        return self.c.post(
            f"/api/projects/{project_id}/members",
            json={"email": email},
            headers=self._h(token),
        )

    # ---------- 项目 ----------
    def test_01_create_project_auto_owner(self):
        tok, _uid, _ = self._login("owner")
        project = self._project(tok, "自动 owner 项目")
        self.assertEqual(project["role"], "owner")
        self.assertEqual(project["member_count"], 1)
        self.assertEqual(project["task_count"], 0)

        r = self.c.get("/api/projects", headers=self._h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(any(x["id"] == project["id"] for x in data["items"]))
        self.assertFalse(data["truncated"])

    def test_02_non_member_cannot_list_members(self):
        tok_o, _, _ = self._login("list-o")
        tok_x, _, _ = self._login("list-x")
        project = self._project(tok_o, "成员列表项目")
        r = self.c.get(f"/api/projects/{project['id']}/members", headers=self._h(tok_x))
        self.assertEqual(r.status_code, 404, r.text)

    def test_03_invite_unregistered_returns_404(self):
        tok, _, _ = self._login("invite-o")
        project = self._project(tok, "邀请未注册项目")
        r = self._invite(tok, project["id"], "missing-user@t.dev")
        self.assertEqual(r.status_code, 404, r.text)

    def test_04_duplicate_invite_returns_409(self):
        tok, _, _ = self._login("dup-o")
        _, _, member_email = self._login("dup-m")
        project = self._project(tok, "重复邀请项目")
        r = self._invite(tok, project["id"], member_email)
        self.assertEqual(r.status_code, 201, r.text)
        r = self._invite(tok, project["id"], member_email)
        self.assertEqual(r.status_code, 409, r.text)
        r = self.c.get(f"/api/projects/{project['id']}/members", headers=self._h(tok))
        self.assertEqual(r.json()["total"], 2, r.text)

    def test_05_non_owner_cannot_remove_member(self):
        tok_o, uid_o, _ = self._login("rm-o")
        tok_m, uid_m, email_m = self._login("rm-m")
        project = self._project(tok_o, "移除权限项目")
        self.assertEqual(self._invite(tok_o, project["id"], email_m).status_code, 201)

        # 普通成员移除 owner：404（权限判定不泄露存在性）
        r = self.c.delete(f"/api/projects/{project['id']}/members/{uid_o}", headers=self._h(tok_m))
        self.assertEqual(r.status_code, 404, r.text)
        # 普通成员邀请新人：404
        _, _, other_email = self._login("rm-x")
        r = self._invite(tok_m, project["id"], other_email)
        self.assertEqual(r.status_code, 404, r.text)
        self.assertNotEqual(uid_m, uid_o)

    def test_06_owner_manages_members(self):
        tok, _, _ = self._login("manage-o")
        _tok_m, uid_m, email_m = self._login("manage-m")
        project = self._project(tok, "成员管理项目")
        self.assertEqual(self._invite(tok, project["id"], email_m).status_code, 201)

        r = self.c.get(f"/api/projects/{project['id']}/members", headers=self._h(tok))
        self.assertEqual(r.json()["total"], 2)
        self.assertTrue(any(x["user_id"] == uid_m for x in r.json()["items"]))

        # owner 提升成员为 owner，再降回 member；最后移除
        r = self.c.patch(
            f"/api/projects/{project['id']}/members/{uid_m}",
            json={"role": "owner"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["role"], "owner")
        r = self.c.patch(
            f"/api/projects/{project['id']}/members/{uid_m}",
            json={"role": "member"},
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 200, r.text)
        r = self.c.delete(f"/api/projects/{project['id']}/members/{uid_m}", headers=self._h(tok))
        self.assertEqual(r.status_code, 204, r.text)
        r = self.c.get(f"/api/projects/{project['id']}/members", headers=self._h(tok))
        self.assertEqual(r.json()["total"], 1)

    def test_07_project_patch_owner_only_and_delete_confirm(self):
        tok_o, _, _ = self._login("patch-o")
        tok_m, _, email_m = self._login("patch-m")
        project = self._project(tok_o, "待改名项目")
        self.assertEqual(self._invite(tok_o, project["id"], email_m).status_code, 201)

        r = self.c.patch(
            f"/api/projects/{project['id']}",
            json={"name": "改名后项目", "description": "新简介"},
            headers=self._h(tok_m),
        )
        self.assertEqual(r.status_code, 404, r.text)

        r = self.c.patch(
            f"/api/projects/{project['id']}",
            json={"name": "改名后项目", "description": "新简介"},
            headers=self._h(tok_o),
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["name"], "改名后项目")

        r = self.c.delete(f"/api/projects/{project['id']}", headers=self._h(tok_o))
        self.assertEqual(r.status_code, 400, r.text)  # 未确认，拒绝级联删
        r = self.c.delete(f"/api/projects/{project['id']}?confirm=true", headers=self._h(tok_o))
        self.assertEqual(r.status_code, 204, r.text)
        r = self.c.get("/api/projects", headers=self._h(tok_o))
        self.assertFalse(any(x["id"] == project["id"] for x in r.json()["items"]))

    def test_08_project_stats_and_board(self):
        tok, _, _ = self._login("board-o")
        _tok_m, uid_m, email_m = self._login("board-m")
        project = self._project(tok, "看板项目")
        self.assertEqual(self._invite(tok, project["id"], email_m).status_code, 201)

        # 指派下拉的数据源：成员列表必须同时给成员关系 id 和业务 user_id，
        # 前端 PATCH assignee_id 只能用 user_id，不能用 members.id。
        r = self.c.get(f"/api/projects/{project['id']}/members", headers=self._h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        members = r.json()["items"]
        target = next(item for item in members if item["user_id"] == uid_m)
        self.assertEqual(target["email"], email_m)
        self.assertEqual(target["role"], "member")
        self.assertIn("id", target)

        r = self.c.post(
            "/api/tasks",
            json={
                "title": "看板任务",
                "project_id": project["id"],
                "priority": "high",
                "due_date": (dt.date.today() + dt.timedelta(days=1)).isoformat(),
                "assignee_id": uid_m,
                "tags": ["test"],
            },
            headers=self._h(tok),
        )
        self.assertEqual(r.status_code, 201, r.text)
        task_id = r.json()["id"]

        r = self.c.get(f"/api/projects/{project['id']}/stats", headers=self._h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["by_status"]["todo"], 1)
        self.assertEqual(data["by_priority"]["high"], 1)

        r = self.c.get(f"/api/board?project_id={project['id']}", headers=self._h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        board = r.json()
        self.assertEqual(board["project"]["id"], project["id"])
        self.assertEqual(set(board["columns"]), {"todo", "in_progress", "blocked", "done"})
        card = next(x for x in board["columns"]["todo"] if x["id"] == task_id)
        self.assertEqual(card["assignee_id"], uid_m)
        self.assertEqual(card["assignee_name"], "board-m")
        self.assertEqual(card["tags"], ["test"])


if __name__ == "__main__":
    unittest.main()
