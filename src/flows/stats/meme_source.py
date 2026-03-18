from prefect import flow

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.stats import meme_source


@flow(
    name="Calculate meme_source_stats",
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_meme_source_stats() -> None:
    await meme_source.calculate_meme_source_stats()

    safe_emit("ff.stats.meme_source.completed", "ff.stats.meme_source")
