"""数据模型：用户、项目、项目成员、任务、任务标签、待确认操作。

原版四张表（users/projects/tasks/pending_actions）的列名与类型完全保留，
二次开发只追加字段、新增 project_members 与 task_tags 两张表，
保证既有代码（tools/agent/seed/tests）与旧数据继续可用（设计方案 §4）。
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(60))
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    color: Mapped[str] = mapped_column(String(20), default="")
    # 追加字段：项目简介（设计方案 §4.2）
    description: Mapped[str] = mapped_column(Text, default="")


class ProjectMember(Base):
    """项目成员关系：role ∈ {owner, member}。

    owner 负责删项目、删项目任务、管理成员（设计方案 §4.3）。
    (project_id, user_id) 唯一，防止重复邀请产生脏行。
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_members_project_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="member")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # owner_id 语义：创建者（原版即如此，协作化后继续沿用）
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    # 追加字段（设计方案 §4.2）
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TaskTag(Base):
    """任务标签：复合主键 (task_id, tag)，一个任务可挂多个标签。

    外键 ondelete=CASCADE，删任务时标签行随之删除（SQLite 已开 PRAGMA foreign_keys）。
    """

    __tablename__ = "task_tags"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(String(30), primary_key=True)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result_json: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    # 追加字段：update 类操作的改前快照，字段级 diff 的数据来源（设计方案 §4.2，郑伟健写入）
    before_json: Mapped[str] = mapped_column(Text, default="")
