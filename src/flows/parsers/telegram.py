from prefect import flow

from src.storage.parsers import telegram
from src.utils import generate_flow_run_name


@flow(name="Parse raw telegram",
      description="Flow for parsing telegram channels to get posts",
      version="0.1.0",
      flow_run_name=generate_flow_run_name)
def parse_telegram_source() -> None:
    telegram.parse_source()
