"""邮件与公文助手配置。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    siliconflow_api_key: str = ""
    openai_base_url: str = "https://api.siliconflow.cn/v1"
    model_chat: str = "Qwen/Qwen2.5-7B-Instruct"
    app_env: str = "local"
    port: int = 8000
    database_url: str = "sqlite:///./data/task_board.db"
    jwt_secret: str = "task-secret"
    jwt_expire_hours: int = 12
    cookie_secure: bool = False
    agent_max_steps: int = 6
    agent_confirm_write: bool = True
    agent_confirm_ttl_minutes: int = 10

    def require_key(self) -> str:
        if not self.siliconflow_api_key:
            raise RuntimeError("缺少 SILICONFLOW_API_KEY。请复制 .env.example 为 .env 并填写密钥。")
        return self.siliconflow_api_key

    def mask_key(self) -> str:
        key = self.siliconflow_api_key
        return "(empty)" if not key else f"{key[:6]}***{key[-4:]}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
