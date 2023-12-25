import sys

from prefect import serve
from prefect.deployments import Deployment

from src.database import init_db
from src.flows.parsers.telegram import parse_telegram_source

deployments = {
    "parse_telegram_source": parse_telegram_source
}


def deploy():
    for deployment_name, deployment_flow in deployments.items():
        deployment = Deployment.to_deployment(
            name=deployment_name,
            flow=deployment_flow,
            version="0.1.0",
            work_pool_name="source_parsers",
            work_queue_name="source_parsers",
        )
        deployment.apply()


def serve_flow():
    init_db()
    flows = []
    for deployment_name, deployment_flow in deployments.items():
        deployment = deployment_flow.to_deployment(
            name=deployment_name,
            version="0.1.0"
        )
        flows.append(deployment)
    serve(*flows)


if __name__ == "__main__":
    globals()[sys.argv[1]]()