from prefect import flow, get_run_logger

from src.stats.user import service


@flow(
    name="Calculate user_stats",
    version="0.1.0"
)
async def calculate_user_stats(
) -> None:
    logger = get_run_logger()
    await service.calculate_user_stats()