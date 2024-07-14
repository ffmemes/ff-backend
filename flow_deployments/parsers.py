from prefect.client.schemas.schedules import CronSchedule
from prefect.deployments import Deployment

from src.config import settings
from src.flows.parsers.ig import parse_ig_sources
from src.flows.parsers.tg import parse_telegram_sources
from src.flows.parsers.vk import parse_vk_sources

deployment_tg = Deployment.build_from_flow(
    flow=parse_telegram_sources,
    name="Parse Telegram Sources",
    schedules=[CronSchedule(cron="0 * * * *", timezone="Europe/London")],
    work_pool_name=settings.ENVIRONMENT,
)

deployment_tg.apply()


deployment_vk = Deployment.build_from_flow(
    flow=parse_vk_sources,
    name="Parse VK Sources",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="20 * * * *", timezone="Europe/London")],
)

deployment_vk.apply()


deployment_ig = Deployment.build_from_flow(
    flow=parse_ig_sources,
    name="Parse Instgram Sources",
    work_pool_name=settings.ENVIRONMENT,
    schedules=[CronSchedule(cron="30 */5 * * *", timezone="Europe/London")],
)

deployment_ig.apply()
