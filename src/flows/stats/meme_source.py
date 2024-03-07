from prefect import flow

from src.stats import meme_source


@flow(
    name="Calculate meme_source_stats",
)
async def calculate_meme_source_stats() -> None:
    await meme_source.calculate_meme_source_stats()
