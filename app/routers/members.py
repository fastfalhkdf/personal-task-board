"""项目成员接口：邀请、列表、改角色、移除（设计方案 §5.2，戴罗轩）。

权限：
- 列表：项目成员可见（非成员 404，防探测）；
- 邀请 / 改角色 / 移除：仅 owner；
- 角色只有 owner/member 两种；任何时刻至少保留一名 owner；
- 越权统一 404（统一开发规范 §7）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_session
from ..models import Project, ProjectMember, User
from ..permissions import assert_project_member, assert_project_owner

router = APIRouter(prefix="/api/projects", tags=["members"])
Role = Literal["owner", "member"]


class MemberInviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)


class MemberPatchIn(BaseModel):
    role: Role


def _project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return project


def _member_row(db: Session, project_id: int, user_id: int) -> ProjectMember:
    row = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="记录不存在")
    return row


def _member_out(row: ProjectMember, user: User) -> dict:
    return {
        "id": row.id,
        "user_id": user.id,
        "email": user.email,
        "name": user.name,
        "role": row.role,
    }


@router.get("/{project_id}/members")
def list_members(
    project_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    _project_or_404(db, project_id)
    assert_project_member(db, project_id, user)
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id)
    ).all()
    items = [_member_out(member, member_user) for member, member_user in rows]
    return {"items": items, "total": len(items), "truncated": False}


@router.post("/{project_id}/members", status_code=201)
def invite_member(
    project_id: int,
    body: MemberInviteIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    _project_or_404(db, project_id)
    assert_project_owner(db, project_id, user)

    email = body.email.strip().lower()
    target = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="该邮箱尚未注册")
    existing = db.execute(
        select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == target.id,
        )
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="该用户已是项目成员")
    row = ProjectMember(project_id=project_id, user_id=target.id, role="member")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _member_out(row, target)


@router.patch("/{project_id}/members/{user_id}")
def change_member_role(
    project_id: int,
    user_id: int,
    body: MemberPatchIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    _project_or_404(db, project_id)
    assert_project_owner(db, project_id, user)
    row = _member_row(db, project_id, user_id)
    if row.role == "owner" and body.role == "member":
        owners = db.execute(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        ).scalar_one()
        if owners <= 1:
            raise HTTPException(status_code=400, detail="项目至少保留一名 owner")
    row.role = body.role
    db.commit()
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _member_out(row, target)


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: int,
    user_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
):
    _project_or_404(db, project_id)
    assert_project_owner(db, project_id, user)
    row = _member_row(db, project_id, user_id)
    if row.role == "owner":
        raise HTTPException(status_code=400, detail="不能移除项目 owner")
    db.delete(row)
    db.commit()
    return None
