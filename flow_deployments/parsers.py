from prefect.deployments import Deployment
from prefect.server.schemas.schedules import CronSchedule

from src.flows.parsers.tg import parse_telegram_sources


deployment_tg = Deployment.build_from_flow(
    flow=parse_telegram_sources,
    name="Parse Telegram Sources",
    version="0.1.0",
    schedule=(CronSchedule(cron="0 */3 * * *", timezone="Europe/London")),
    work_pool_name="all",
)

deployment_tg.apply()


# deployment_vk = Deployment.build_from_flow(
#     flow=parse_vk_source,
#     name="parse_vk_source",
#     version="0.1.0",
#     work_queue_name="source_parsers",
# )

# deployment_vk.apply()
