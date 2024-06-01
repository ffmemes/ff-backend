from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.rewards.uploaded_memes import (
    reward_ru_users_for_weekly_top_uploaded_memes,
)

deployment_user_stats = Deployment.build_from_flow(
    flow=reward_ru_users_for_weekly_top_uploaded_memes,
    name="Reward RU users for weekly top uploaded memes",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="0 19 * * 5", timezone="Europe/London")],
)

deployment_user_stats.apply()
