"""SQLAlchemy 2.0 数据库初始化与会话依赖。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
SessionLocal: sessionmaker | None = None
_db_note = ""


def _prepare_sqlite(url: str) -> str:
    global _db_note
    if not url.startswith("sqlite:///") or url.endswith(":memory:"):
        return url
    raw_path = url.removeprefix("sqlite:///")
    path = Path(raw_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _db_note = f"数据库目录创建失败：{exc}"
        raise RuntimeError(_db_note) from exc
    return url


def init_db(settings: Settings) -> Engine:
    global _engine, SessionLocal
    if _engine is not None:
        return _engine

    url = _prepare_sqlite(settings.database_url)
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, echo=False, **kwargs)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = engine
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化")
    return _engine


def get_sessionmaker() -> sessionmaker:
    if SessionLocal is None:
        raise RuntimeError("数据库尚未初始化")
    return SessionLocal


def get_session():
    """FastAPI 依赖：每个请求使用独立 Session。"""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()


def db_note() -> str:
    return _db_note
