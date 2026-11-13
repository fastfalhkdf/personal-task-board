"""统一权限判定（设计方案 §4.3），全组唯一实现，其他模块只调用不自建。

规则：
- 私人任务（project_id 为空）：仅创建者本人可见 / 可改 / 可删；
- 项目任务：项目成员可见可改，owner 角色可删；
- 一切越权返回 404 而非 403（沿用原 assert_owner 的防泄露策略，不暴露资源是否存在）。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ProjectMember, Task, User

_NOT_FOUND = "记录不存在"


def is_project_member(db: Session, project_id: int, user_id: int) -> bool:
    row = db.execute(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    return row is not None


def project_role(db: Session, project_id: int, user_id: int) -> str | None:
    row = db.execute(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).first()
    return row[0] if row else None


def assert_project_member(db: Session, project_id: int, user: User) -> None:
    """项目级资源入口：非成员或项目不存在一律 404（防探测）。"""
    if not is_project_member(db, project_id, user.id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


def assert_project_owner(db: Session, project_id: int, user: User) -> None:
    """仅项目 owner 角色可执行的操作（删项目、删项目任务、管成员）。"""
    if project_role(db, project_id, user.id) != "owner":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


def assert_task_visible(db: Session, task: Task | None, user: User) -> None:
    if task is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if task.project_id is None:
        if task.owner_id != user.id:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
    elif not is_project_member(db, task.project_id, user.id):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)


def assert_task_writable(db: Session, task: Task | None, user: User) -> None:
    """可见即可改：项目任务对全体成员可改（设计方案 §4.3）。"""
    assert_task_visible(db, task, user)


def assert_task_deletable(db: Session, task: Task | None, user: User) -> None:
    """删除最严：私人任务仅创建者；项目任务仅 owner 角色（§4.3 可删列）。"""
    assert_task_visible(db, task, user)
    if task.project_id is not None and project_role(db, task.project_id, user.id) != "owner":
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
