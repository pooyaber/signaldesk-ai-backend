from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    public_api_url: str | None = None
    cors_origins: str = "*"
    webhook_secret: str = "change-me"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    database_path: str = "signals.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def cors_origin_list(self) -> list[str]:
        raw = (self.cors_origins or "*").strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
