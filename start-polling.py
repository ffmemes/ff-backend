import redis.asyncio as aioredis

from src import redis
from src.tgbot import bot
from src.config import settings

if __name__ == "__main__":
    pool = aioredis.ConnectionPool.from_url(
        str(settings.REDIS_URL), max_connections=10, decode_responses=True
    )
    redis.redis_client = aioredis.Redis(connection_pool=pool)

    bot.application = bot.setup_application(is_webhook=False)
    bot.run_polling(bot.application)
