from prefect.deployments import Deployment

from src.flows.parsers.telegram import parse_telegram_sources
# from src.flows.parsers.vk import parse_vk_source


deployment_tg = Deployment.build_from_flow(
    flow=parse_telegram_sources,
    name="Parse Telegram Sources",
    version="0.1.0",
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
