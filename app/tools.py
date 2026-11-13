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
