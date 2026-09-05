import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.logging import LoggingIntegration
from starlette.middleware.cors import CORSMiddleware

from src import redis
from src.admin.router import router as admin_router
from src.config import app_configs, settings
from src.observability.sentry import before_send, before_send_log
from src.tgbot import app as tgbot_app
from src.tgbot.channel_workers import start_channel_workers, stop_channel_workers
from src.tgbot.router import router as tgbot_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_application: FastAPI) -> AsyncGenerator:
    # Startup
    tgbot_app.application = tgbot_app.setup_application(settings.ENVIRONMENT.is_deployed)
    await tgbot_app.application.initialize()
    channel_workers = start_channel_workers(tgbot_app.application.bot)

    # flush all redis keys on startup for debug
    # await redis.redis_client.flushall()

    # if is_webhook:  # all gunicorn workers will call this and hit rate limit
    #     await bot.setup_webhook(bot.application)

    try:
        yield
    finally:
        await stop_channel_workers(channel_workers)

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
        environment=settings.ENVIRONMENT.value,
        release=f"ff-backend@{settings.APP_VERSION}",
        enable_logs=True,
        integrations=[
            LoggingIntegration(
                sentry_logs_level=logging.WARNING,
                level=logging.INFO,
                event_level=logging.ERROR,
            ),
        ],
        ignore_errors=[
            "telegram.error.Forbidden",  # handled by error.py -> records blocked_bot_at
        ],
        include_local_variables=False,
        before_send=before_send,
        before_send_log=before_send_log,
    )


@app.get("/healthcheck", include_in_schema=False)
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/prefect/flow-runs", include_in_schema=False)
async def prefect_flow_runs(limit: int = 20):
    """Proxy recent Prefect flow runs for monitoring.

    Queries Prefect API internally (within Docker network),
    bypassing external auth issues.
    """
    prefect_url = settings.PREFECT_API_URL
    if not prefect_url:
        return {"error": "PREFECT_API_URL not configured"}

    headers = {}
    if settings.PREFECT_AUTH_STRING:
        headers["Authorization"] = f"Bearer {settings.PREFECT_AUTH_STRING}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{prefect_url}/flow_runs/filter",
                headers=headers,
                json={
                    "sort": "START_TIME_DESC",
                    "limit": min(limit, 100),
                },
                timeout=10,
            )
            resp.raise_for_status()
            runs = resp.json()
    except Exception as e:
        logger.error("Failed to query Prefect API: %s", e)
        return {"error": f"Prefect API query failed: {e}"}

    return [
        {
            "name": r.get("name"),
            "flow_id": r.get("flow_id"),
            "state_type": r.get("state_type"),
            "state_name": r.get("state_name"),
            "start_time": r.get("start_time"),
            "end_time": r.get("end_time"),
            "total_run_time": r.get("total_run_time"),
        }
        for r in runs
    ]


@app.get("/prefect/deployments", include_in_schema=False)
async def prefect_deployments():
    """List Prefect deployments with their status."""
    prefect_url = settings.PREFECT_API_URL
    if not prefect_url:
        return {"error": "PREFECT_API_URL not configured"}

    headers = {}
    if settings.PREFECT_AUTH_STRING:
        headers["Authorization"] = f"Bearer {settings.PREFECT_AUTH_STRING}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{prefect_url}/deployments/filter",
                headers=headers,
                json={"limit": 50},
                timeout=10,
            )
            resp.raise_for_status()
            deployments = resp.json()
    except Exception as e:
        logger.error("Failed to query Prefect API: %s", e)
        return {"error": f"Prefect API query failed: {e}"}

    return [
        {
            "name": d.get("name"),
            "status": d.get("status"),
            "paused": d.get("paused"),
            "last_polled": d.get("last_polled"),
            "created": d.get("created"),
            "updated": d.get("updated"),
        }
        for d in deployments
    ]


app.include_router(tgbot_router, prefix="/tgbot", tags=["Telegram Bot"])
app.include_router(admin_router)
