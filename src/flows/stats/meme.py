from prefect import flow

from src.flows.hooks import notify_telegram_on_failure
from src.stats import meme


@flow(
    name="Calculate meme_stats",
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_meme_stats() -> None:
    await meme.calculate_meme_reactions_and_engagement()

    await meme.calculate_meme_raw_impressions_stats()

    await meme.calculate_meme_invited_count()
