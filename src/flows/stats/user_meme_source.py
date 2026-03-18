from prefect import flow

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.stats import user_meme_source


@flow(
    name="Calculate user_meme_source_stats",
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_user_meme_source_stats() -> None:
    await user_meme_source.calculate_user_meme_source_stats()

    safe_emit("ff.stats.user_meme_source.completed", "ff.stats.user_meme_source")
