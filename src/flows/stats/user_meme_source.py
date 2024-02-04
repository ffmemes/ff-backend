from prefect import flow

from src.stats import user_meme_source


@flow(
    name="Calculate user_meme_source_stats",
)
async def calculate_user_meme_source_stats() -> None:
    await user_meme_source.calculate_user_meme_source_stats()
