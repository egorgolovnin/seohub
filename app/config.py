from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/seohub"
    bot_token: str = ""
    admin_chat_id: int = 0
    channel_id: int = 0
    telethon_api_id: int = 0
    telethon_api_hash: str = ""
    telethon_session_string: str = ""
    anthropic_api_key: str = ""
    app_env: str = "production"
    app_port: int = 8000
    # Residential proxy for geo-check (e.g. "http://user:pass@gate.smartproxy.com:7777")
    proxy_url: str = ""
    admin_group_id: int = 0  # Group for approve/reject requests

    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
