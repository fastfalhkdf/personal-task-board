import datetime as dt
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import hash_password
from .models import Project, ProjectMember, Task, User


def seed(db: Session):
    u = db.execute(select(User).where(User.email == "demo@tasks.dev")).scalar_one_or_none()
    if not u:
        u = User(
            email="demo@tasks.dev",
            name="演示用户",
            password_hash=hash_password("demo1234"),
        )
        db.add(u)
        db.flush()
    # 用户可能已经从 API 创建了多个项目；seed 只保证演示项目存在，
    # 不能假设“一人只有一个项目”，否则启动时 MultipleResultsFound。
    p = (
        db.execute(select(Project).where(Project.owner_id == u.id).order_by(Project.id))
        .scalars()
        .first()
    )
    if not p:
        p = Project(owner_id=u.id, name="AI 学习", color="#4f7")
        db.add(p)
        db.flush()
        db.add(
            Task(
                owner_id=u.id,
                project_id=p.id,
                title="完成 Agent 练习",
                priority="high",
                due_date=dt.date.today() + dt.timedelta(days=1),
            )
        )
    # 新增 ProjectMember 后，演示项目也必须补上 owner 成员关系，
    # 否则 /api/projects 与看板接口按成员过滤时会看不到 seed 项目。
    member = db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == p.id,
            ProjectMember.user_id == u.id,
        )
    ).scalar_one_or_none()
    if not member:
        db.add(ProjectMember(project_id=p.id, user_id=u.id, role="owner"))
    db.commit()
    return {"tasks": 1}
