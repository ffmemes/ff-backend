from prefect import flow

from src.stats import meme


@flow(
    name="Calculate meme_stats",
)
async def calculate_meme_stats() -> None:
    await meme.calculate_meme_reactions_stats()

    await meme.calculate_meme_raw_impressions_stats()

    await meme.calculate_meme_invited_count()


@flow(
    name="Calculate engagement_score",
)
async def calculate_engagement_score() -> None:
    await meme.calculate_engagement_score()
