from prefect import flow

from src.flows.hooks import notify_telegram_on_failure
from src.stats import user


@flow(
    name="Calculate user_stats",
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=120,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_user_stats() -> None:
    await user.calculate_user_stats()

    await user.calculate_inviter_stats()
