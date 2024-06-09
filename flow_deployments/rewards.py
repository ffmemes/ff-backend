from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from src.config import settings
from src.flows.rewards.uploaded_memes import (
    reward_en_users_for_weekly_top_uploaded_memes,
    reward_ru_users_for_weekly_top_uploaded_memes,
)

deployment_weekly_top_uploaded_memes_ru = Deployment.build_from_flow(
    flow=reward_ru_users_for_weekly_top_uploaded_memes,
    name="Reward RU users for weekly top uploaded memes",
    schedules=[CronSchedule(cron="0 19 * * 5", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_weekly_top_uploaded_memes_ru.apply()


deployment_weekly_top_uploaded_memes_en = Deployment.build_from_flow(
    flow=reward_en_users_for_weekly_top_uploaded_memes,
    name="Reward EN users for weekly top uploaded memes",
    schedules=[CronSchedule(cron="0 18 * * 3", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_weekly_top_uploaded_memes_en.apply()
