from prefect import flow

from src.storage.parsers import telegram


@flow(
    name="Parse raw telegram",
    description="Flow for parsing telegram channels to get posts",
    version="0.1.0"
)
def parse_telegram_source() -> None:
    telegram.parse_source()
