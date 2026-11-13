from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from .config import get_settings
from .db import Base, db_note, get_engine, get_sessionmaker, init_db
from .routers import agent, auth, members, projects, tasks
from .seed import seed

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
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
