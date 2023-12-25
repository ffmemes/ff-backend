from prefect import serve
from prefect.deployments import Deployment

from src.flows.parsers.telegram import parse_telegram_source
from src.flows.parsers.vk import parse_vk_source


def deploy():
    deployment = Deployment.build_from_flow(
        flow=parse_vk_source,
        name="parse_vk_source",
        version="0.1.0",
        work_queue_name="source_parsers",
    )

    deployment.apply()


def serve_flow():
    telegram_deployment = parse_telegram_source.to_deployment(
        name="parse_telegram_source",
        version="0.1.0"
    )
    serve(telegram_deployment)
