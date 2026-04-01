from prefect import flow

from src.flows.hooks import notify_telegram_on_failure
from src.stats import meme


@flow(
    name="Calculate meme_stats (heavy)",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=600,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_meme_stats_heavy() -> None:
    # raw_impr_rank: relative rank within source by scrape-time view count.
    # Changes only when new memes arrive (parsers run hourly), so hourly is sufficient.
    # Decoupled from the 15-min flow so a slow full-table scan can't block lr_smoothed.
    await meme.calculate_meme_raw_impressions_stats()

    # invited_count: full scan of user_deep_link_log. Hourly is more than enough.
    await meme.calculate_meme_invited_count()
