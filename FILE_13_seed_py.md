# 文件开发记录：`app/seed.py`

> 目标文件：`app/seed.py`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````python
import datetime as dt
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import hash_password
from .models import Project,Task,User
def seed(db:Session):
 u=db.execute(select(User).where(User.email=="demo@tasks.dev")).scalar_one_or_none()
 if not u:u=User(email="demo@tasks.dev",name="演示用户",password_hash=hash_password("demo1234"));db.add(u);db.flush()
 p=db.execute(select(Project).where(Project.owner_id==u.id)).scalar_one_or_none()
 if not p:p=Project(owner_id=u.id,name="AI 学习",color="#4f7");db.add(p);db.flush();db.add(Task(owner_id=u.id,project_id=p.id,title="完成 Agent 练习",priority="high",due_date=dt.date.today()+dt.timedelta(days=1)))
 db.commit();return{"tasks":1}
````

验证：3 个测试通过。
