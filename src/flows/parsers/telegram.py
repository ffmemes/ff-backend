from prefect import flow

from src.storage.parsers import telegram


@flow(
    name="Parse raw telegram",
    description="Flow for parsing telegram channels to get posts",
    version="0.1.0"
)
def parse_telegram_source() -> None:
    # 1. get LIMIT=10 tg sources to parse
    # 2. data = telegram.parse_tg_channel(tg_channel_username)
    # 3. save data to db
    # 4. update parsed at for tg source

    pass
