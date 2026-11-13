"""bcrypt 密码、JWT、Cookie/Bearer 双通道认证与资源归属校验。"""
from __future__ import annotations

import datetime as dt
from typing import Annotated

import bcrypt
import jwt
from fastapi import Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_session
from .models import User

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(rounds=10)
    ).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, AttributeError):
        return False


def create_token(user: User, settings: Settings) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "iat": now,
        "exp": now + dt.timedelta(hours=settings.jwt_expire_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的登录凭证") from exc


def current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
    access_token: Annotated[str | None, Cookie()] = None,
    db: Session = Depends(get_session),
) -> User:
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")

    payload = decode_token(token, get_settings())
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "凭证中的用户标识无效") from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def set_auth_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.jwt_expire_hours * 3600,
        path="/",
    )


def assert_owner(row, user: User) -> None:
    if row is None or getattr(row, "owner_id", None) != user.id:
        # 返回 404，避免泄露资源是否存在。
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
