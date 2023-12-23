from prefect.deployments import Deployment

from src.flows.parsers.vk import parse_vk_source

deployment = Deployment.build_from_flow(
    flow=parse_vk_source,
    name="parse_vk_source",
    version="0.1.0",
    work_queue_name="source_parsers",
)

deployment.apply()  # type: ignore
