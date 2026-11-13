# 文件开发记录：`app/routers/tasks.py`

> 目标文件：`app/routers/tasks.py`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````python
from fastapi import APIRouter,Depends
from ..auth import current_user
from ..db import get_session
from ..models import User
from ..tools import execute
from sqlalchemy.orm import Session
router=APIRouter(prefix="/api/tasks",tags=["tasks"])
@router.get("")
def list_all(user:User=Depends(current_user),db:Session=Depends(get_session)):return execute("list_tasks",{},db,user.id)
@router.get("/stats")
def stats(user:User=Depends(current_user),db:Session=Depends(get_session)):return execute("get_task_stats",{},db,user.id)
````

验证：3 个测试通过。
