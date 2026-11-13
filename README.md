# 个人任务与项目看板

管理个人任务状态、优先级和截止日期，Agent 查询统计并经确认创建或更新任务。

- Cookie/JWT 用户隔离。
- 任务 CRUD 统计和 Agent 写确认。
- pytest 离线测试（Fake LLM 注入，不联网、不消耗 API 额度）、Docker 国内镜像。

演示账号：`demo@tasks.dev / demo1234`（由 `seed.py` 启动时幂等注入，五人开箱即有）。

## 环境要求

- Python **3.11.x**（3.12+ 一律不许，见《统一开发规范》§2）
- 无需 Node/前端构建链（原生 ES modules）

## 快速开始（规范 §2.1）

```bash
git clone https://gitcode.com/hxqx/personal-task-board.git
cd personal-task-board
python -m venv .venv

# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env    # 然后生成自己的 JWT_SECRET（规范 §3，禁止沿用默认值）
#   python -c "import secrets;print(secrets.token_hex(32))"   # 结果写入 .env 的 JWT_SECRET=

uvicorn app.main:app --reload --port 8000
```

浏览器打开 <http://localhost:8000>，用上面的演示账号登录。

## 测试与 DoD（合并前四项全绿，规范 §8）

```bash
python -m ruff format --check .
python -m ruff check .
python -m pytest -q                       # 期望全绿
curl -s localhost:8000/api/health          # {"ok":true,...}
```

首次开工前的六步环境自检见《统一开发规范》§2.2。
