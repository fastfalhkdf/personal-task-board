"""D3 收尾项：默认 JWT 密钥启动守卫（设计方案 §10）。"""

import pytest

from app.config import Settings
from app.main import require_strong_secret


def _settings(**kw) -> Settings:
    base = {"app_env": "local", "jwt_secret": "task-secret"}
    base.update(kw)
    return Settings(**base)


def test_dev_env_allows_default_secret():
    require_strong_secret(_settings(app_env="local"))
    require_strong_secret(_settings(app_env="dev"))


def test_production_rejects_default_secret():
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        require_strong_secret(_settings(app_env="production", jwt_secret="task-secret"))


def test_production_rejects_compose_placeholder_and_empty():
    with pytest.raises(RuntimeError):
        require_strong_secret(
            _settings(app_env="production", jwt_secret="change-this-in-production")
        )
    with pytest.raises(RuntimeError):
        require_strong_secret(_settings(app_env="production", jwt_secret=""))


def test_production_accepts_strong_secret():
    require_strong_secret(
        _settings(app_env="production", jwt_secret="a-long-random-string-123")
    )
