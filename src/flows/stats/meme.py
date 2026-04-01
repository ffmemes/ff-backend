from prefect import flow

from src.flows.events import safe_emit
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
    # Incremental: only recompute stats for memes active in the last 3 hours.
    # Memes with no recent reactions keep their existing meme_stats rows.
    # Heavy operations (raw_impr_rank, invited_count) run separately every hour
    # via calculate_meme_stats_heavy to avoid blocking this 15-min flow.
    await meme.calculate_meme_reactions_and_engagement(lookback_hours=3)

    safe_emit("ff.stats.meme.completed", "ff.stats.meme")
