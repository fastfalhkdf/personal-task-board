# 文件开发记录：`requirements.txt`

> 目标文件：`requirements.txt`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````text
fastapi==0.115.6
uvicorn[standard]==0.34.0
openai==1.59.6
sqlalchemy==2.0.36
bcrypt==4.2.0
pyjwt==2.10.1
pydantic==2.10.4
pydantic-settings==2.7.0
python-dotenv==1.0.1
httpx==0.28.1
````

验证：3 个测试通过。
