from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from src.config import settings
from src.flows.broadcasts.meme import (
    broadcast_next_meme_to_active_1w_ago,
    broadcast_next_meme_to_active_4w_ago,
    broadcast_next_meme_to_active_15m_ago,
    broadcast_next_meme_to_active_24h_ago,
    broadcast_next_meme_to_active_48h_ago,
)

# broadcasts meme in 15m after last activity
deployment_broadcast_15m_ago = Deployment.build_from_flow(
    flow=broadcast_next_meme_to_active_15m_ago,
    name="broadcast_next_meme_to_active_15m_ago",
    schedules=[CronSchedule(cron="*/15 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_broadcast_15m_ago.apply()

# broadcasts meme in 48h after last activity
deployment_broadcast_24h_ago = Deployment.build_from_flow(
    flow=broadcast_next_meme_to_active_24h_ago,
    name="broadcast_next_meme_to_active_24h_ago",
    schedules=[CronSchedule(cron="5 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_broadcast_24h_ago.apply()


# broadcasts meme in 48h after last activity
deployment_broadcast_48h_ago = Deployment.build_from_flow(
    flow=broadcast_next_meme_to_active_48h_ago,
    name="broadcast_next_meme_to_active_48h_ago",
    schedules=[CronSchedule(cron="5 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_broadcast_48h_ago.apply()

# broadcasts meme in 1w after last activity
deployment_broadcast_1w_ago = Deployment.build_from_flow(
    flow=broadcast_next_meme_to_active_1w_ago,
    name="broadcast_next_meme_to_active_1w_ago",
    schedules=[CronSchedule(cron="7 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_broadcast_1w_ago.apply()

# broadcasts meme in 4w after last activity
deployment_broadcast_4w_ago = Deployment.build_from_flow(
    flow=broadcast_next_meme_to_active_4w_ago,
    name="broadcast_next_meme_to_active_4w_ago",
    schedules=[CronSchedule(cron="9 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)


deployment_broadcast_4w_ago.apply()
