from prefect import flow, get_run_logger

from src.stats.user_meme_source import service


@flow(
    name="Calculate user_meme_source_stats",
    version="0.1.0"
)
async def calculate_user_meme_source_stats(
) -> None:
    logger = get_run_logger()
    await service.calculate_user_meme_source_stats()
