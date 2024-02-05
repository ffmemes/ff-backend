from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.broadcasts.meme import broadcast_memes_to_users_active_hours_ago

deployment_broadcast_hourly = Deployment.build_from_flow(
    flow=broadcast_memes_to_users_active_hours_ago,
    name="broadcast_memes_to_users_active_hours_ago",
    schedule=(CronSchedule(cron="3 * * * *", timezone="Europe/London")),
    work_pool_name=settings.ENVIRONMENT,
)

deployment_broadcast_hourly.apply()
