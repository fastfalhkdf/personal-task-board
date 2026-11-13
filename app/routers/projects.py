"""项目接口：项目 CRUD、统计与看板快照（设计方案 §5.1 / §5.2，戴罗轩）。

边界说明：
- 本项目模型当前没有 archived 字段（models.py 由程熙单点维护），
  因此 PATCH 暂只支持 name/color/description；归档待 models 增加字段后再补。
- 列表统一返回 {items, total, truncated}（统一开发规范 §7）。
- 所有项目级操作都经 app.permissions 的统一权限函数，越权一律 404。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import Project, ProjectMember, Task, TaskTag, User
from ..permissions import (
    assert_project_member,
    assert_project_owner,
    project_role,
)

router = APIRouter(prefix="/api", tags=["projects"])
STATUSES = ("todo", "in_progress", "blocked", "done")


class ProjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(default="", max_length=20)
    description: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def _name_non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value


class ProjectPatchIn(BaseModel):
    """只改显式传入的字段；null 不作为清空语义，避免误伤。"""

    name: str | None = Field(default=None, max_length=120)
    color: str | None = Field(default=None, max_length=20)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _name_non_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("项目名称不能为空")
        return value


def _count(db: Session, model, *conditions) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(*conditions)
    ).scalar_one()


def _project_out(db: Session, project: Project, role: str) -> dict:
    member_count = _count(db, ProjectMember, ProjectMember.project_id == project.id)
    task_count = _count(db, Task, Task.project_id == project.id)
    return {
        "id": project.id,
        "name": project.name,
        "color": project.color,
        "description": project.description,
        "role": role,
        "member_count": member_count,
        "task_count": task_count,
    }


def _task_card(db: Session, task: Task) -> dict:
    tags = (
        db.execute(select(TaskTag.tag).where(TaskTag.task_id == task.id))
        .scalars()
        .all()
    )
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "assignee_id": task.assignee_id,
        "sort_order": task.sort_order,
        "tags": list(tags),
    }


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return project


@router.get("/projects")
def list_projects(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    rows = db.execute(
        select(Project, ProjectMember.role)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(ProjectMember.user_id == user.id)
        .order_by(Project.id)
    ).all()
    items = [_project_out(db, project, role) for project, role in rows]
    return {"items": items, "total": len(items), "truncated": False}


@router.post("/projects", status_code=201)
def create_project(
    body: ProjectCreateIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    project = Project(
        owner_id=user.id,
        name=body.name,
        color=body.color,
        description=body.description,
    )
    db.add(project)
    db.flush()
    # 创建者自动成为 owner，避免出现“有项目但没有成员”的孤儿数据。
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(project)
    return _project_out(db, project, "owner")


@router.patch("/projects/{project_id}")
def patch_project(
    project_id: int,
    body: ProjectPatchIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    project = _project_or_404(db, project_id)
    assert_project_owner(db, project_id, user)
    provided = body.model_fields_set
    if "name" in provided:
        if body.name is None:
            raise HTTPException(status_code=422, detail="项目名称不能为空")
        project.name = body.name
    if "color" in provided:
        project.color = body.color or ""
    if "description" in provided:
        project.description = body.description or ""
    db.commit()
    db.refresh(project)
    return _project_out(db, project, project_role(db, project_id, user.id) or "member")


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    confirm: bool = Query(False),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    project = _project_or_404(db, project_id)
    assert_project_owner(db, project_id, user)
    if not confirm:
        # 项目删除会级联删任务，必须显式确认；默认 false 防误删。
        raise HTTPException(
            status_code=400, detail="删除项目会级联删除任务，需 confirm=true"
        )
    tasks = (
        db.execute(select(Task).where(Task.project_id == project_id)).scalars().all()
    )
    for task in tasks:
        db.delete(task)
    db.delete(project)
    db.commit()
    return None


@router.get("/projects/{project_id}/stats")
def project_stats(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    _project_or_404(db, project_id)
    assert_project_member(db, project_id, user)
    tasks = (
        db.execute(select(Task).where(Task.project_id == project_id)).scalars().all()
    )
    by_status = {status: 0 for status in STATUSES}
    by_priority = {"low": 0, "medium": 0, "high": 0}
    for task in tasks:
        if task.status in by_status:
            by_status[task.status] += 1
        if task.priority in by_priority:
            by_priority[task.priority] += 1
    total = len(tasks)
    done = by_status["done"]
    return {
        "project_id": project_id,
        "total": total,
        "done_rate": round(done / total, 2) if total else 0.0,
        "by_status": by_status,
        "by_priority": by_priority,
        "member_count": _count(
            db, ProjectMember, ProjectMember.project_id == project_id
        ),
    }


@router.get("/board")
def board(
    project_id: int = Query(..., description="项目 id"),
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    """看板快照：一次返回四列卡片，减少首屏请求（设计方案 §5.2）。"""
    project = _project_or_404(db, project_id)
    assert_project_member(db, project_id, user)
    tasks = (
        db.execute(
            select(Task)
            .where(Task.project_id == project_id)
            .order_by(Task.sort_order, Task.id)
        )
        .scalars()
        .all()
    )
    columns = {status: [] for status in STATUSES}
    for task in tasks:
        if task.status in columns:
            columns[task.status].append(_task_card(db, task))
    return {
        "project": _project_out(
            db, project, project_role(db, project_id, user.id) or "member"
        ),
        "columns": columns,
    }
