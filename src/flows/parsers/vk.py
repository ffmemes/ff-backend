from prefect import flow, get_run_logger

from src.storage.parsers import vk


@flow(name="get_new_sanctioned_addresses", version="0.1.0")
async def parse_vk_source() -> None:
    logger = get_run_logger()
    logger.info("Starting flow for scraping vk source")

    # TODO:
    # result = vk.parse_source()
