# 文件开发记录：`docker-compose.yml`

> 目标文件：`docker-compose.yml`

## 开发者想法

负责个人任务看板业务，写操作必须确认并隔离用户。

## 完整代码

````yaml
services:
  task-board:
    build:
      context: .
      args:
        PYTHON_BASE_IMAGE: "${PYTHON_BASE_IMAGE:-docker.m.daocloud.io/library/python:3.11-slim}"
    ports: ["8000:8000"]
    environment:
      SILICONFLOW_API_KEY: "${SILICONFLOW_API_KEY:-}"
      OPENAI_BASE_URL: "${OPENAI_BASE_URL:-https://api.siliconflow.cn/v1}"
      MODEL_CHAT: "${MODEL_CHAT:-Qwen/Qwen2.5-7B-Instruct}"
      JWT_SECRET: "${JWT_SECRET:-change-this-in-production}"
      COOKIE_SECURE: "${COOKIE_SECURE:-false}"
      APP_ENV: production
      DATABASE_URL: sqlite:////app/data/task_board.db
      AGENT_MAX_STEPS: "6"
      AGENT_CONFIRM_WRITE: "true"
    volumes: ["task-data:/app/data"]
    restart: unless-stopped
volumes:
  task-data:
````

验证：3 个测试通过。
