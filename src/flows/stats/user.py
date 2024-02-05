from prefect import flow

from src.stats import user


@flow(
    name="Calculate user_stats",
)
async def calculate_user_stats() -> None:
    await user.calculate_user_stats()
