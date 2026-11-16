from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from .config import Settings, get_settings
from .db import Base, db_note, get_engine, get_sessionmaker, init_db
from .routers import agent, auth, members, projects, tasks
from .seed import seed

BASE_DIR = Path(__file__).resolve().parent

_DEV_ENVS = {"local", "dev", "development", "test"}
_DEFAULT_SECRETS = {"task-secret", "change-this-in-production", ""}


def require_strong_secret(s: Settings) -> None:
    """D3 收尾项（设计方案 §10）：非开发环境禁用默认密钥，否则拒绝启动。"""
    if s.app_env.strip().lower() in _DEV_ENVS:
        return
    if s.jwt_secret in _DEFAULT_SECRETS:
        raise RuntimeError(
            f"APP_ENV={s.app_env} 下 JWT_SECRET 仍是默认值，拒绝启动。"
            "请在 .env 或 compose 环境变量中设置强随机密钥。"
        )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    require_strong_secret(s)
    e = init_db(s)
    Base.metadata.create_all(bind=e)
    with get_sessionmaker()() as db:
        logging.info("演示数据：%s", seed(db))
    yield


app = FastAPI(title="个人任务与项目看板", version="1.0.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(agent.router)
app.include_router(tasks.router)
app.include_router(projects.router)
app.include_router(members.router)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
def health():
    s = get_settings()
    e = get_engine()
    return {"ok": True, "tables": sorted(inspect(e).get_table_names()), "db_note": db_note()}


@app.middleware("http")
async def no_cache_static(request, call_next):
    """静态资源与首页不走浏览器缓存（否则旧版 JS 会让新功能"点了没反应"）。"""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response
