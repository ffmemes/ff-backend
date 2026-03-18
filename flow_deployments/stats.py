from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from src.config import settings
from src.flows.stats.meme import calculate_meme_stats
from src.flows.stats.meme_source import calculate_meme_source_stats
from src.flows.stats.user import calculate_user_stats
from src.flows.stats.user_meme_source import calculate_user_meme_source_stats

# Tier 2 periodic stats: user_stats and user_meme_source_stats serve as
# consistency catch-up for Tier 1 (inline per-user stats on reaction).
# Meme stats and meme source stats are global and only run periodically.

deployment_user_stats = Deployment.build_from_flow(
    flow=calculate_user_stats,
    name="Calculate user_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="0,15,30,45 * * * *", timezone="Europe/London")],
)

deployment_user_stats.apply()


deployment_user_meme_source_stats = Deployment.build_from_flow(
    flow=calculate_user_meme_source_stats,
    name="Calculate user_meme_source_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="5,20,35,50 * * * *", timezone="Europe/London")],
)

deployment_user_meme_source_stats.apply()


deployment_meme_stats = Deployment.build_from_flow(
    flow=calculate_meme_stats,
    name="Calculate meme_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="10,25,40,55 * * * *", timezone="Europe/London")],
)

deployment_meme_stats.apply()


deployment_meme_source_stats = Deployment.build_from_flow(
    flow=calculate_meme_source_stats,
    name="Calculate meme_source_stats",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="12,27,42,57 * * * *", timezone="Europe/London")],
)

deployment_meme_source_stats.apply()
