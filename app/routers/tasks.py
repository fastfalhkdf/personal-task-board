"""任务接口：CRUD、筛选分页、今日待办与统计（设计方案 §5.1）。

约定：
- 列表统一返回 {items, total, truncated}（统一开发规范 §7）；
- 错误统一 {"detail": 中文原因}，越权一律 404；
- 日期入参由 pydantic 按 ISO（YYYY-MM-DD）解析，非法即 422。
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import ProjectMember, Task, TaskTag, User
from ..permissions import (
    assert_project_member,
    assert_task_deletable,
    assert_task_writable,
    is_project_member,
)
from ..schemas import TaskCreateIn, TaskPatchIn
from ..tools import execute

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

MAX_LIMIT = 500


def _now() -> dt.datetime:
    """naive UTC（统一开发规范 §7：服务端存 naive UTC）。"""
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def _visible_cond(user_id: int):
    """可见性 = 自己的任务 ∪ 自己所属项目的任务（§4.3）。"""
    member_projects = select(ProjectMember.project_id).where(
        ProjectMember.user_id == user_id
    )
    return or_(Task.owner_id == user_id, Task.project_id.in_(member_projects))


def _check_assignee(
    db: Session, assignee_id: int | None, project_id: int | None, owner_id: int
) -> None:
    """指派校验（验收 9）：项目任务→目标必须是项目成员，否则 422；私人任务→只能指派给自己。"""
    if assignee_id is None:
        return
    if db.get(User, assignee_id) is None:
        raise HTTPException(status_code=422, detail="指派对象不存在")
    if project_id is None:
        if assignee_id != owner_id:
            raise HTTPException(status_code=422, detail="私人任务只能指派给自己")
    elif not is_project_member(db, project_id, assignee_id):
        raise HTTPException(status_code=422, detail="指派对象不是该项目成员")


def _tags_map(db: Session, task_ids: list[int]) -> dict[int, list[str]]:
    if not task_ids:
        return {}
    rows = db.execute(select(TaskTag).where(TaskTag.task_id.in_(task_ids))).scalars()
    out: dict[int, list[str]] = {}
    for r in rows:
        out.setdefault(r.task_id, []).append(r.tag)
    return out


def _serialize(task: Task, tags: list[str]) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "project_id": task.project_id,
        "assignee_id": task.assignee_id,
        "sort_order": task.sort_order,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "tags": tags,
    }


@router.get("")
def list_tasks(
    status: str | None = Query(None),
    project_id: int | None = Query(None),
    priority: str | None = Query(None),
    tag: str | None = Query(None),
    assignee_id: int | None = Query(None),
    q: str | None = Query(None),
    due: str | None = Query(None, pattern="^(today|overdue|week)$"),
    limit: int = Query(100, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    today = dt.date.today()
    conds = [_visible_cond(user.id)]
    if status:
        conds.append(Task.status == status)
    if project_id is not None:
        conds.append(Task.project_id == project_id)
    if priority:
        conds.append(Task.priority == priority)
    if tag:
        conds.append(Task.id.in_(select(TaskTag.task_id).where(TaskTag.tag == tag)))
    if assignee_id is not None:
        conds.append(Task.assignee_id == assignee_id)
    if q:
        pattern = f"%{q.strip()}%"
        conds.append(or_(Task.title.like(pattern), Task.description.like(pattern)))
    if due == "today":
        conds.append(Task.due_date == today)
    elif due == "overdue":
        conds.append(Task.due_date < today)
    elif due == "week":
        conds.append(Task.due_date >= today)
        conds.append(Task.due_date <= today + dt.timedelta(days=7))

    total = db.execute(select(func.count(Task.id)).where(*conds)).scalar_one()
    rows = (
        db.execute(
            select(Task)
            .where(*conds)
            .order_by(Task.sort_order, Task.id)
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    tags = _tags_map(db, [r.id for r in rows])
    items = [_serialize(r, tags.get(r.id, [])) for r in rows]
    return {"items": items, "total": total, "truncated": offset + len(items) < total}


@router.get("/today")
def today_tasks(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    """首页三件套：今日到期、逾期、完成率（需求 4.1，缺口 5）。"""
    day = dt.date.today()
    base = [_visible_cond(user.id), Task.due_date.is_not(None)]

    def _rows(cond):
        rows = (
            db.execute(select(Task).where(*base, cond).order_by(Task.due_date, Task.id))
            .scalars()
            .all()
        )
        tags = _tags_map(db, [r.id for r in rows])
        return [_serialize(r, tags.get(r.id, [])) for r in rows]

    todo_today = _rows((Task.due_date == day) & (Task.status != "done"))
    overdue = _rows((Task.due_date < day) & (Task.status != "done"))
    total = db.execute(
        select(func.count(Task.id)).where(_visible_cond(user.id))
    ).scalar_one()
    done = db.execute(
        select(func.count(Task.id)).where(_visible_cond(user.id), Task.status == "done")
    ).scalar_one()
    done_rate = round(done / total, 2) if total else 0.0
    return {"today": todo_today, "overdue": overdue, "done_rate": done_rate}


@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_session)):
    # 统计口径与 Agent 侧共用同一工具，保证页面与 Agent 结果一致（验收 1）
    return execute("get_task_stats", {}, db, user.id)


@router.post("", status_code=201)
def create_task(
    body: TaskCreateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    if body.project_id is not None:
        # 非成员/项目不存在 → 404（防探测）；REST 只强制 title，三件套是 Agent 侧规则
        assert_project_member(db, body.project_id, user)
    _check_assignee(db, body.assignee_id, body.project_id, owner_id=user.id)

    task = Task(
        owner_id=user.id,
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_date=body.due_date,
        assignee_id=body.assignee_id,
    )
    db.add(task)
    db.flush()
    for t in body.tags:
        db.add(TaskTag(task_id=task.id, tag=t))
    db.commit()
    db.refresh(task)
    return _serialize(task, body.tags)


@router.patch("/{task_id}")
def patch_task(
    task_id: int,
    body: TaskPatchIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    task = db.get(Task, task_id)
    assert_task_writable(db, task, user)  # 不存在或越权 → 404

    provided = body.model_fields_set
    new_project = task.project_id

    # 1) 项目先判：换了项目要重新过成员校验
    if "project_id" in provided:
        new_project = body.project_id
        if new_project is not None:
            assert_project_member(db, new_project, user)

    # 2) 指派校验（基于目标项目）
    if "assignee_id" in provided:
        _check_assignee(db, body.assignee_id, new_project, owner_id=task.owner_id)

    # 3) 应用字段（只动显式传入的，null 表示清空）
    if "title" in provided:
        task.title = body.title
    if "description" in provided:
        task.description = body.description
    if "status" in provided and body.status != task.status:
        task.status = body.status
        # 置 done 记完成时间，撤 done 清空（供按周统计）
        task.completed_at = _now() if body.status == "done" else None
    if "priority" in provided:
        task.priority = body.priority
    if "due_date" in provided:
        task.due_date = body.due_date
    if "sort_order" in provided:
        task.sort_order = body.sort_order
    if "project_id" in provided:
        task.project_id = new_project
        # 换项目后原指派对象若不在新项目成员里 → 自动清空指派，避免脏数据
        if task.assignee_id is not None and not _assignee_still_valid(db, task):
            task.assignee_id = None
    if "assignee_id" in provided:
        task.assignee_id = body.assignee_id

    db.commit()
    db.refresh(task)
    tags = _tags_map(db, [task.id])
    return _serialize(task, tags.get(task.id, []))


def _assignee_still_valid(db: Session, task: Task) -> bool:
    if task.project_id is None:
        return task.assignee_id == task.owner_id
    return is_project_member(db, task.project_id, task.assignee_id)


@router.delete("/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    task = db.get(Task, task_id)
    assert_task_deletable(db, task, user)  # 私人=创建者；项目=owner 角色，否则 404
    db.delete(task)  # task_tags 由 FK CASCADE 级联删除
    db.commit()
