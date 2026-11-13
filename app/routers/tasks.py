from fastapi import APIRouter, Depends
from ..auth import current_user
from ..db import get_session
from ..models import User
from ..tools import execute
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def list_all(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return execute("list_tasks", {}, db, user.id)


@router.get("/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_session)):
    return execute("get_task_stats", {}, db, user.id)
