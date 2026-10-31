from prefect import flow, get_run_logger

from src.flows.hooks import notify_telegram_on_failure
from src.storage.source_voting import advance_daily_source_cycle
from src.tgbot.bot import bot


@flow(
    name="Daily Moderator Source Voting",
    description="Advance the moderator-chat daily source voting cycle",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=600,
    on_failure=[notify_telegram_on_failure],
)
async def daily_moderator_source_voting() -> None:
    logger = get_run_logger()
    result = await advance_daily_source_cycle(bot)
    logger.info("Daily moderator source voting result: %s", result)
