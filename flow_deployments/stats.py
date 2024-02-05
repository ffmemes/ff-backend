from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings
from src.flows.stats.meme import calculate_meme_stats
from src.flows.stats.user import calculate_user_stats
from src.flows.stats.user_meme_source import calculate_user_meme_source_stats

deployment_user_stats = Deployment.build_from_flow(
    flow=calculate_user_stats,
    name="Calculate user_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedule=(CronSchedule(cron="0,15,30,45 * * * *", timezone="Europe/London")),
)

deployment_user_stats.apply()


deployment_user_meme_source_stats = Deployment.build_from_flow(
    flow=calculate_user_meme_source_stats,
    name="Calculate user_meme_source_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedule=(CronSchedule(cron="13,28,43,58 * * * *", timezone="Europe/London")),
)

deployment_user_meme_source_stats.apply()


deployment_user_stats = Deployment.build_from_flow(
    flow=calculate_meme_stats,
    name="Calculate meme_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedule=(CronSchedule(cron="3,18,33,48 * * * *", timezone="Europe/London")),
)

deployment_user_stats.apply()
