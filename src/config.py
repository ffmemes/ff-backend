from typing import Any

from pydantic import PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings

from src.constants import Environment


class Config(BaseSettings):
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_POOL_TTL: int = 60 * 20  # 20 minutes
    DATABASE_POOL_PRE_PING: bool = True
    DATABASE_POOL_TIMEOUT: int = 15  # seconds; wait up to 15s for a free connection before failing
    DATABASE_POOL_MAX_OVERFLOW: int = 20

    REDIS_URL: RedisDsn
    REDIS_HEALTH_CHECK_INTERVAL: int = 30

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
    UPLOADED_MEMES_REVIEW_CHAT_ID: str | None = None
    ADMIN_LOGS_CHAT_ID: str | None = None
    # Shared secret for internal /admin/* HTTP inspect endpoints (agents/operators).
    # When unset, those routes return 503. Prefer a long random token; never commit it.
    ADMIN_API_TOKEN: str | None = None

    VK_TOKEN: str | None = None

    REDIS_MAX_CONNECTIONS: int = 128

    OPENROUTER_API_KEY: str | None = None
    # Optional independent account for free-only OCR redundancy.
    OPENROUTER_API_KEY_SECONDARY: str | None = None

    # FFM-1161/FFM-1689: gate cold_start engines so they only serve genuinely-new
    # users (nsessions <= 1). Dormant returners with nmemes_sent < 30 but
    # multiple sessions fall through to the growing-user blender instead.
    COLD_START_NSESSIONS_GATE_ENABLED: bool = True
    # FFM-1882: narrow true-new cold-start positions 2-10 experiment.
    # Roll back by setting this to false in production env.
    COLD_START_CANDIDATE_GUARDRAILS_ENABLED: bool = True
    # explore_budget_v1: 50/50 non-cold-start users get the labeling budget,
    # fresh-viral blend slot and idle-return first slot. Kill switch = all control.
    EXPLORE_BUDGET_V1_ENABLED: bool = True

    # Source affinity policies (skip/dislike ≈ "next", not "ban channel").
    # Soft demote majority-dislike sources in ranking (default ON).
    RECOMMENDATION_DEMOTE_DISLIKED_SOURCES: bool = True
    RECOMMENDATION_DEMOTE_DISLIKED_MIN_REACTIONS: int = 5
    RECOMMENDATION_DEMOTE_DISLIKED_MULTIPLIER: float = 0.15
    # Retention broadcasts: pick high-confidence meme (affinity + LR) instead of
    # blind Redis queue pop. Kill switch rolls back to queue path.
    BROADCAST_HIGH_QUALITY_PICK_ENABLED: bool = True
    # broadcast_cadence_holdout_v1: no-push holdout per cadence step (15m/24h
    # 15%, 1w/2w/4w 20%). See experiments/2026-10-30-broadcast-cadence-holdout.md.
    BROADCAST_CADENCE_HOLDOUT_ENABLED: bool = True
    # Monthly reminder (users whose last reaction was 29-365 days ago).
    # Owner flips on after deploy. Set HOLDOUT_PCT=0 after the v1 readout.
    MONTHLY_REMINDER_ENABLED: bool = False
    MONTHLY_REMINDER_HOLDOUT_PCT: int = 50

    PREFECT_API_URL: str | None = None

    TELEGRAM_API_ID: int | None = None
    TELEGRAM_API_HASH: str | None = None
    TELEGRAM_SESSION_STRING: str | None = None

    # @model_validator(mode="after")
    # def validate_sentry_non_local(self) -> "Config":
    #     if self.ENVIRONMENT.is_deployed and not self.SENTRY_DSN:
    #         raise ValueError("Sentry is not set")

    #     return self


settings = Config()

app_configs: dict[str, Any] = {"title": "FFmemes API"}
if not settings.ENVIRONMENT.is_debug:
    app_configs["openapi_url"] = None  # hide docs
