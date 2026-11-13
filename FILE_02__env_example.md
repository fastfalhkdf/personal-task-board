# 文件开发记录：`.env.example`

> 目标文件：`.env.example`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````dotenv
SILICONFLOW_API_KEY=
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
MODEL_CHAT=Qwen/Qwen2.5-7B-Instruct
APP_ENV=local
PORT=8000
DATABASE_URL=sqlite:///./data/task_board.db
JWT_SECRET=replace-with-a-long-random-secret
JWT_EXPIRE_HOURS=12
COOKIE_SECURE=false
AGENT_MAX_STEPS=6
AGENT_CONFIRM_WRITE=true
AGENT_CONFIRM_TTL_MINUTES=10
````

验证：3 个测试通过。
