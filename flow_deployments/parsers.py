from prefect.deployments import Deployment

from src.flows.parsers.vk import parse_vk_source
from src.flows.parsers.telegram import parse_telegram_source


# deployment_vk = Deployment.build_from_flow(
#     flow=parse_vk_source,
#     name="parse_vk_source",
#     version="0.1.0",
#     work_queue_name="source_parsers",
# )

# deployment_vk.apply()


deployment_tg = Deployment.build_from_flow(
    flow=parse_telegram_source,
    name="parse_telegram_source",
    version="0.1.0",
    work_queue_name="source_parsers",
)

deployment_tg.apply()
