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
    TELEGRAM_INLINE_SHARE_ENABLED: bool = True
    TELEGRAM_INLINE_SHARE_CANARY_PERCENT: int = 0
    MEME_STORAGE_TELEGRAM_CHAT_ID: str | None = None
    UPLOADED_MEMES_REVIEW_CHAT_ID: str | None = None
    ADMIN_LOGS_CHAT_ID: str | None = None
    # Shared secret for internal /admin/* HTTP inspect endpoints (agents/operators).
    # When unset, those routes return 503. Prefer a long random token; never commit it.
    ADMIN_API_TOKEN: str | None = None

    VK_TOKEN: str | None = None
    VK_USER_TOKEN: str | None = None
    VK_GROUP_ID: int | None = None

    REDIS_MAX_CONNECTIONS: int = 128

    OPENAI_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None

    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    CHAT_AGENT_ENABLED: bool = False

    # FFM-1161/FFM-1689: gate cold_start engines so they only serve genuinely-new
    # users (nsessions <= 1). Dormant returners with nmemes_sent < 30 but
    # multiple sessions fall through to the growing-user blender instead.
    COLD_START_NSESSIONS_GATE_ENABLED: bool = True
    # FFM-1882: narrow true-new cold-start positions 2-10 experiment.
    # Roll back by setting this to false in production env.
    COLD_START_CANDIDATE_GUARDRAILS_ENABLED: bool = True

    # Recommendation batch diagnostics are realtime operational data, not
    # durable product facts. Keep compact logs/spans always on and sample full
    # payloads so future Prometheus/Grafana adapters can reuse the same seam.
    RECOMMENDATION_DIAGNOSTICS_SAMPLE_RATE: float = 0.01
    RECOMMENDATION_SOURCE_DIVERSITY_ENABLED: bool = False
    RECOMMENDATION_SHADOW_SCORING_ENABLED: bool = True
    # Source affinity policies (skip/dislike ≈ "next", not "ban channel").
    # Soft demote majority-dislike sources in ranking (default ON).
    RECOMMENDATION_DEMOTE_DISLIKED_SOURCES: bool = True
    RECOMMENDATION_DEMOTE_DISLIKED_MIN_REACTIONS: int = 5
    RECOMMENDATION_DEMOTE_DISLIKED_MULTIPLIER: float = 0.15
    # Hard exclude only strong hate (default OFF — empty-queue risk).
    RECOMMENDATION_BLOCK_DISLIKED_SOURCES: bool = False
    RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS: int = 15
    RECOMMENDATION_BLOCK_DISLIKED_RATIO: float = 3.0  # ndislikes >= 3 * nlikes
    # Retention broadcasts: pick high-confidence meme (affinity + LR) instead of
    # blind Redis queue pop. Kill switch rolls back to queue path.
    BROADCAST_HIGH_QUALITY_PICK_ENABLED: bool = True
    # RU crosspost ranker: multiply score by ln(nlikes+1) (meme volume, not LR).
    # Offline 2026-08-09: src×log1p(likes) top-20% lift ~1.14 on time-split.
    # Kill switch reverts @fastfoodmemes to score_version=2 behavior.
    CROSSPOST_RU_MEME_LIKE_VOLUME_ENABLED: bool = True

    PREFECT_API_URL: str | None = None
    PREFECT_AUTH_STRING: str | None = None

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
