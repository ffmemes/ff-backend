import logging
import redis.asyncio as aioredis

from src import redis, localizer
from src.tgbot import bot
from src.config import settings


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)


if __name__ == "__main__":
    pool = aioredis.ConnectionPool.from_url(
        str(settings.REDIS_URL), max_connections=10, decode_responses=True
    )
    redis.redis_client = aioredis.Redis(connection_pool=pool)

    localizer.localizations = localizer.load()

    bot.application = bot.setup_application(is_webhook=False)
    bot.run_polling(bot.application)
