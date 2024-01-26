from typing import Any

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings

from src.constants import Environment


class Config(BaseSettings):
    DATABASE_URL: PostgresDsn
    REDIS_URL: RedisDsn

    SITE_DOMAIN: str = "myapp.com"

    ENVIRONMENT: Environment = Environment.PRODUCTION

    SENTRY_DSN: str | None = None

    CORS_ORIGINS: list[str]
    CORS_ORIGINS_REGEX: str | None = None
    CORS_HEADERS: list[str]

    APP_VERSION: str = "1"

    TELEGRAM_BOT_TOKEN: str | None = None
    TELEGRAM_BOT_USERNAME: str | None = None
    TELEGRAM_BOT_WEBHOOK_SECRET: str | None = None
    MEME_STORAGE_TELEGRAM_CHAT_ID: str | None = None
    ADMIN_LOGS_CHAT_ID: str | None = None

    VK_TOKEN: str | None = None

    MYSTIC_TOKEN: str | None = None

    # @model_validator(mode="after")
    # def validate_sentry_non_local(self) -> "Config":
    #     if self.ENVIRONMENT.is_deployed and not self.SENTRY_DSN:
    #         raise ValueError("Sentry is not set")

    #     return self


settings = Config()

app_configs: dict[str, Any] = {"title": "FFmemes API"}
if not settings.ENVIRONMENT.is_debug:
    app_configs["openapi_url"] = None  # hide docs
