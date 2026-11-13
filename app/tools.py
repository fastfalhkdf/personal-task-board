"""Agent 工具契约与真实执行（郑伟健 · 设计方案 §6.1）。

设计要点：
1. 工具返回的每一项数据都来自真实数据库，且强制按「当前用户可见」过滤：
   私人任务仅创建者，项目任务仅项目成员（复用 app.permissions 的判定口径）。
2. 写工具只做参数校验与落库动作，是否允许执行由 agent.py 的确认流程决定；
   update_task 在拦截前先取 before 快照，供前端渲染「旧值 → 新值」。
3. 列表类工具一律带 truncated 标记，limit 由服务端夹取，模型传多大都不会拖库。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import and_, func, or_, select

from .llm import tool_spec
from .models import Project, ProjectMember, Task, TaskTag, User

STATUSES = ("todo", "in_progress", "blocked", "done")
PRIORITIES = ("low", "medium", "high")
DUE_RANGES = ("today", "overdue", "week")

MAX_LIST = 50
DEFAULT_LIST = 20

UPDATABLE = (
    "title",
    "description",
    "status",
    "priority",
    "due_date",
    "project_id",
    "assignee_id",
    "tags",
)

# ---------------- 工具规格（发给模型的「表格」） ----------------

SPECS = [
    tool_spec(
        "list_tasks",
        "列出当前用户可见的任务。问「我有哪些任务」「这周要做什么」「XX 项目的待办」时用。"
        "可按状态/项目/优先级/标签/指派人/截止区间过滤；结果含项目名与成员名。"
        "limit 默认 20、最大 50，超出返回 truncated=true。",
        {
            "status": {"type": "string", "enum": list(STATUSES)},
            "project_id": {"type": "integer"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "tag": {"type": "string", "description": "单个标签名"},
            "assignee_id": {"type": "integer"},
            "due_from": {"type": "string", "description": "YYYY-MM-DD，含当天"},
            "due_to": {"type": "string", "description": "YYYY-MM-DD，含当天"},
            "limit": {"type": "integer", "description": "默认 20，最大 50"},
        },
        [],
    ),
    tool_spec(
        "get_task",
        "按 id 取单条任务的全部字段（状态、优先级、截止日、项目、指派人、标签）。"
        "更新任务前先用它唯一定位。",
        {"task_id": {"type": "integer"}},
        ["task_id"],
    ),
    tool_spec(
        "count_tasks",
        "统计任务数量。问「还有几个没做」「逾期几件」「今天到期几个」时用。"
        "支持状态、项目、优先级、指派人、due 范围过滤。不要用 list_tasks 数条数。",
        {
            "status": {"type": "string", "enum": list(STATUSES)},
            "project_id": {"type": "integer"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "assignee_id": {"type": "integer"},
            "due": {"type": "string", "enum": list(DUE_RANGES)},
        },
        [],
    ),
    tool_spec(
        "get_task_stats",
        "获取任务总览：总数、已完成、逾期、今日到期、完成率，以及按状态/项目/成员的分布。"
        "问「整体进度」「完成率」时用，一次返回全部，不要循环调用。",
        {},
        [],
    ),
    tool_spec(
        "create_task",
        "新建任务。仅当用户明确说「帮我建」「记一下要做 XX」时使用；推测或含糊表达不要调用。"
        "标题、所属项目、截止日期三者缺一不可，缺了要被拒绝。",
        {
            "title": {"type": "string", "description": "任务标题，必填"},
            "project_id": {"type": "integer", "description": "所属项目，必填"},
            "due_date": {"type": "string", "description": "截止日期 YYYY-MM-DD，必填"},
            "description": {"type": "string"},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "assignee_id": {"type": "integer", "description": "指派人，必须已是项目成员"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        ["title", "project_id", "due_date"],
    ),
    tool_spec(
        "update_task",
        "修改已有任务。改动前必须先 list_tasks/get_task 唯一定位；定位不唯一就反问用户，不要猜。"
        "只传需要改的字段。",
        {
            "task_id": {"type": "integer"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string", "enum": list(STATUSES)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "due_date": {"type": "string", "description": "YYYY-MM-DD；空字符串表示清空"},
            "project_id": {"type": "integer"},
            "assignee_id": {"type": "integer", "description": "空值表示取消指派"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        ["task_id"],
    ),
    tool_spec(
        "list_projects",
        "列出当前用户参与的项目（含角色与任务数）。问「我在哪些项目里」「有哪些项目」时用。",
        {},
        [],
    ),
    tool_spec(
        "list_members",
        "列出某个项目的成员（姓名、邮箱、角色）。问「这个项目里有谁」「指派给谁」时用。",
        {"project_id": {"type": "integer", "description": "不传则汇总我所有项目的成员"}},
        [],
    ),
]

WRITE_TOOLS = {"create_task", "update_task"}
WRITE = WRITE_TOOLS  # 兼容旧引用
READ_TOOLS = {s["function"]["name"] for s in SPECS} - WRITE_TOOLS


# ---------------- 校验（服务端二次校验，模型绕不过） ----------------


def _parse_date(value: object) -> dt.date | None:
    """把 YYYY-MM-DD 解析成日期；空值返回 None，格式错误抛 ValueError。"""
    text = str(value or "").strip()
    if not text:
        return None
    return dt.date.fromisoformat(text)


def _is_date(value: object) -> bool:
    try:
        _parse_date(value)
    except ValueError:
        return False
    return True


def validate(name: str, args: dict) -> str | None:
    """返回错误文案；None 表示可进入待确认或执行阶段。"""
    if name == "create_task":
        if not str(args.get("title") or "").strip():
            return "标题不能为空"
        if not args.get("project_id"):
            return "创建任务必须指定所属项目（project_id）"
        if not str(args.get("due_date") or "").strip():
            return "创建任务必须指定截止日期（due_date）"
        if not _is_date(args.get("due_date")):
            return "截止日期格式应为 YYYY-MM-DD"
        if str(args.get("priority") or "medium") not in PRIORITIES:
            return "优先级非法"
        return None

    if name == "update_task":
        if not args.get("task_id"):
            return "必须提供 task_id"
        if not any(key in args for key in UPDATABLE):
            return "没有需要更新的字段"
        if "status" in args and args["status"] not in STATUSES:
            return "状态非法"
        if "priority" in args and args["priority"] not in PRIORITIES:
            return "优先级非法"
        if "due_date" in args and not _is_date(args["due_date"]):
            return "截止日期格式应为 YYYY-MM-DD"
        if "title" in args and not str(args["title"] or "").strip():
            return "标题不能为空"
        return None

    if "status" in args and args["status"] not in STATUSES:
        return "状态非法"
    if "priority" in args and args["priority"] not in PRIORITIES:
        return "优先级非法"
    if "due" in args and args["due"] not in DUE_RANGES:
        return "due 只能是 today / overdue / week"
    return None


# ---------------- 可见性与序列化 ----------------


def _member_project_ids(uid: int):
    return select(ProjectMember.project_id).where(ProjectMember.user_id == uid)


def visible_task_filter(uid: int):
    """私人任务看 owner，项目任务看成员关系，与 app.permissions 口径一致。"""
    return or_(
        Task.project_id.in_(_member_project_ids(uid)),
        and_(Task.project_id.is_(None), Task.owner_id == uid),
    )


def _tags_of(db, task_id: int) -> list[str]:
    rows = db.execute(select(TaskTag.tag).where(TaskTag.task_id == task_id)).scalars()
    return sorted(rows)


def _task_dict(db, task: Task, project_name: str | None, assignee_name: str | None) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "project_id": task.project_id,
        "project_name": project_name,
        "assignee_id": task.assignee_id,
        "assignee_name": assignee_name,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "tags": _tags_of(db, task.id),
    }


def _task_query(uid: int):
    return (
        select(Task, Project.name, User.name)
        .outerjoin(Project, Project.id == Task.project_id)
        .outerjoin(User, User.id == Task.assignee_id)
        .where(visible_task_filter(uid))
    )


def _apply_filters(q, args: dict):
    if args.get("status"):
        q = q.where(Task.status == args["status"])
    if args.get("project_id"):
        q = q.where(Task.project_id == int(args["project_id"]))
    if args.get("priority"):
        q = q.where(Task.priority == args["priority"])
    if args.get("assignee_id"):
        q = q.where(Task.assignee_id == int(args["assignee_id"]))
    if args.get("tag"):
        q = q.where(
            Task.id.in_(select(TaskTag.task_id).where(TaskTag.tag == str(args["tag"]).strip()))
        )
    due_from = args.get("due_from")
    if due_from and _is_date(due_from):
        q = q.where(Task.due_date >= _parse_date(due_from))
    due_to = args.get("due_to")
    if due_to and _is_date(due_to):
        q = q.where(Task.due_date <= _parse_date(due_to))
    today = dt.date.today()
    if args.get("due") == "today":
        q = q.where(Task.due_date == today)
    elif args.get("due") == "overdue":
        q = q.where(Task.due_date < today, Task.status != "done")
    elif args.get("due") == "week":
        q = q.where(Task.due_date >= today, Task.due_date <= today + dt.timedelta(days=7))
    return q


def snapshot(db, name: str, args: dict, uid: int) -> dict:
    """写操作执行前的改前快照；update_task 才有，用于前端 diff。"""
    if name != "update_task":
        return {}
    task_id = args.get("task_id")
    if not task_id:
        return {}
    row = db.execute(
        select(Task, Project.name, User.name)
        .outerjoin(Project, Project.id == Task.project_id)
        .outerjoin(User, User.id == Task.assignee_id)
        .where(Task.id == int(task_id), visible_task_filter(uid))
    ).first()
    if not row:
        return {}
    return _task_dict(db, row[0], row[1], row[2])


# ---------------- 真实执行 ----------------


def execute(name: str, args: dict, db, uid: int, commit: bool = True) -> dict:
    """执行模型选中的工具。所有查询强制带可见性过滤。"""

    if name == "list_tasks":
        limit = max(1, min(int(args.get("limit") or DEFAULT_LIST), MAX_LIST))
        q = _apply_filters(_task_query(uid), args).order_by(
            Task.due_date.is_(None), Task.due_date, Task.id
        )
        rows = db.execute(q.limit(limit + 1)).all()
        truncated = len(rows) > limit
        items = [_task_dict(db, t, pname, aname) for t, pname, aname in rows[:limit]]
        return {"items": items, "returned": len(items), "truncated": truncated}

    if name == "get_task":
        task_id = args.get("task_id")
        if not task_id:
            return {"error": "必须提供 task_id"}
        row = db.execute(_task_query(uid).where(Task.id == int(task_id))).first()
        if not row:
            return {"error": "任务不存在"}
        return _task_dict(db, row[0], row[1], row[2])

    if name == "count_tasks":
        q = _apply_filters(select(func.count(Task.id)).where(visible_task_filter(uid)), args)
        return {"count": db.execute(q).scalar_one()}

    if name == "get_task_stats":
        rows = db.execute(
            select(Task, Project.name, User.name)
            .outerjoin(Project, Project.id == Task.project_id)
            .outerjoin(User, User.id == Task.assignee_id)
            .where(visible_task_filter(uid))
        ).all()
        today = dt.date.today()
        total = len(rows)
        done = sum(1 for r in rows if r[0].status == "done")
        overdue = sum(
            1
            for r in rows
            if r[0].due_date and r[0].due_date < today and r[0].status != "done"
        )
        due_today = sum(1 for r in rows if r[0].due_date == today and r[0].status != "done")
        by_status = {s: 0 for s in STATUSES}
        by_project: dict[str, int] = {}
        by_member: dict[str, int] = {}
        for task, pname, aname in rows:
            by_status[task.status] = by_status.get(task.status, 0) + 1
            project_key = pname or "未归属项目"
            by_project[project_key] = by_project.get(project_key, 0) + 1
            member_key = aname or "未指派"
            by_member[member_key] = by_member.get(member_key, 0) + 1
        return {
            "total": total,
            "done": done,
            "overdue": overdue,
            "due_today": due_today,
            "done_rate": round(done / total, 3) if total else 0.0,
            "by_status": by_status,
            "by_project": by_project,
            "by_member": by_member,
        }

    if name == "list_projects":
        member_ids = db.execute(select(ProjectMember.project_id).where(
            ProjectMember.user_id == uid
        )).scalars().all()
        if not member_ids:
            return {"items": [], "returned": 0, "truncated": False}
        rows = db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == uid)
            .order_by(Project.id)
        ).all()
        items = []
        for project, role in rows:
            task_count = db.execute(
                select(func.count(Task.id)).where(Task.project_id == project.id)
            ).scalar_one()
            items.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "role": role,
                    "task_count": task_count,
                }
            )
        return {"items": items, "returned": len(items), "truncated": False}

    if name == "list_members":
        project_id = args.get("project_id")
        q = (
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .order_by(ProjectMember.id)
        )
        if project_id:
            allowed = db.execute(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == int(project_id),
                    ProjectMember.user_id == uid,
                )
            ).first()
            if not allowed:
                return {"error": "项目不存在或无权限"}
            q = q.where(ProjectMember.project_id == int(project_id))
        else:
            q = q.where(ProjectMember.project_id.in_(_member_project_ids(uid)))
        rows = db.execute(q).all()
        items = [
            {
                "project_id": m.project_id,
                "user_id": u.id,
                "name": u.name,
                "email": u.email,
                "role": m.role,
            }
            for m, u in rows
        ]
        return {"items": items, "returned": len(items), "truncated": False}

    if name in WRITE_TOOLS:
        error = validate(name, args)
        if error:
            return {"error": error}

    if name == "create_task":
        project_id = int(args["project_id"])
        allowed = db.execute(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == uid
            )
        ).first()
        if not allowed:
            return {"error": "项目不存在或无权限"}
        assignee_id = args.get("assignee_id")
        if assignee_id:
            member = db.execute(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == int(assignee_id),
                )
            ).first()
            if not member:
                return {"error": "指派人不是该项目成员"}
        task = Task(
            owner_id=uid,
            project_id=project_id,
            title=str(args["title"]).strip(),
            description=str(args.get("description") or ""),
            status="todo",
            priority=str(args.get("priority") or "medium"),
            due_date=_parse_date(args["due_date"]),
            assignee_id=int(assignee_id) if assignee_id else None,
        )
        db.add(task)
        db.flush()
        for tag in _normalize_tags(args.get("tags")):
            db.add(TaskTag(task_id=task.id, tag=tag))
        if commit:
            db.commit()
        return {"ok": True, "task_id": task.id, "title": task.title}

    if name == "update_task":
        task_id = int(args["task_id"])
        row = db.execute(_task_query(uid).where(Task.id == task_id)).first()
        if not row:
            return {"error": "任务不存在"}
        task = row[0]
        for key in ("title", "description", "status", "priority", "assignee_id"):
            if key in args:
                value = args[key]
                if key in {"title", "description"}:
                    value = str(value or "").strip()
                elif key == "assignee_id":
                    value = int(value) if value else None
                setattr(task, key, value)
        if "project_id" in args:
            new_project = args["project_id"]
            if new_project:
                allowed = db.execute(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == int(new_project),
                        ProjectMember.user_id == uid,
                    )
                ).first()
                if not allowed:
                    return {"error": "目标项目不存在或无权限"}
                task.project_id = int(new_project)
            else:
                task.project_id = None
        if "due_date" in args:
            task.due_date = _parse_date(args["due_date"])
        if "status" in args:
            task.completed_at = (
                dt.datetime.now(dt.UTC).replace(tzinfo=None)
                if args["status"] == "done"
                else None
            )
        if "tags" in args:
            db.execute(TaskTag.__table__.delete().where(TaskTag.task_id == task.id))
            for tag in _normalize_tags(args.get("tags")):
                db.add(TaskTag(task_id=task.id, tag=tag))
        db.flush()
        if commit:
            db.commit()
        return {"ok": True, "task_id": task.id}

    return {"error": "未知工具"}


def _normalize_tags(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        tag = str(item or "").strip()[:30]
        if tag and tag not in out:
            out.append(tag)
    return out[:10]
