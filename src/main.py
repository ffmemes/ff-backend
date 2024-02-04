from contextlib import asynccontextmanager
from typing import AsyncGenerator

import sentry_sdk
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src import redis
from src.config import app_configs, settings
from src.tgbot import app as tgbot_app
from src.tgbot.router import router as tgbot_router


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncGenerator:
    # Startup
    tgbot_app.application = tgbot_app.setup_application(
        settings.ENVIRONMENT.is_deployed
    )
    await tgbot_app.application.initialize()
    # if is_webhook:  # all gunicorn workers will call this and hit rate limit
    #     await bot.setup_webhook(bot.application)

    yield

    if settings.ENVIRONMENT.is_testing:
        return
    # Shutdown
    await redis.pool.disconnect()


app = FastAPI(**app_configs, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGINS_REGEX,
    allow_credentials=True,
    allow_methods=("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"),
    allow_headers=settings.CORS_HEADERS,
)

if settings.ENVIRONMENT.is_deployed:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
    )


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(tgbot_router, prefix="/tgbot", tags=["Telegram Bot"])
