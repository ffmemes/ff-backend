from prefect import flow

from src.stats import meme


@flow(
    name="Calculate meme_stats",
)
async def calculate_meme_stats() -> None:
    await meme.calculate_meme_reactions_stats()

    await meme.calculate_meme_raw_impressions_stats()
