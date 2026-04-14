import logging
import sys

import redis.asyncio as aioredis

from src import localizer, redis
from src.config import settings
from src.constants import Environment
from src.tgbot import app

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == "__main__":
    if settings.ENVIRONMENT == Environment.PRODUCTION:
        print(
            "ERROR: Polling mode must not run against the production bot.\n"
            "Set ENVIRONMENT=LOCAL in your .env and use a separate test bot token.\n"
            "Production uses webhook mode — polling causes TelegramConflictError.",
            file=sys.stderr,
        )
        sys.exit(1)

    pool = aioredis.ConnectionPool.from_url(
        str(settings.REDIS_URL),
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
    )
    redis.redis_client = aioredis.Redis(connection_pool=pool)

    localizer.localizations = localizer.load()

    app.application = app.setup_application(is_webhook=False)
    app.run_polling(app.application)
