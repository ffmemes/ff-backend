from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.config import settings

from src.flows.parsers.tg import parse_telegram_sources
from src.flows.parsers.vk import parse_vk_sources


deployment_tg = Deployment.build_from_flow(
    flow=parse_telegram_sources,
    name="Parse Telegram Sources",
    version="0.1.0",
    schedule=(CronSchedule(cron="0 */3 * * *", timezone="Europe/London")),
    work_pool_name=settings.ENVIRONMENT,
)

deployment_tg.apply()


deployment_vk = Deployment.build_from_flow(
    flow=parse_vk_sources,
    name="Parse VK Sources",
    version="0.1.0",
    work_pool_name=settings.ENVIRONMENT,
    schedule=(CronSchedule(cron="10 */3 * * *", timezone="Europe/London")),
)

deployment_vk.apply()
