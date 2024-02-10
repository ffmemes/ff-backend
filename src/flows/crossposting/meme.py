from prefect import flow, get_run_logger

from src.config import settings
from src.crossposting.constants import Channel
from src.crossposting.senders import send_meme_to_tg_channel
from src.crossposting.service import get_next_meme_for_tg_channel_en, log_meme_sent


@flow
async def post_meme_to_tg_channel_en():
    """
    Runs each hour:
    1. Takes users which were active (hours, hours-1) hours ago
    2. Sends them a best meme
    """
    logger = get_run_logger()

    next_meme = await get_next_meme_for_tg_channel_en()
    logger.info(f"Next meme for TG Channel EN: {next_meme['id']}")

    # TODO: add settings.CROSSPOSING_TG_CHANNEL_EN_CHAT_ID
    await send_meme_to_tg_channel(settings.CROSSPOSING_TG_CHANNEL_EN_CHAT_ID, next_meme)

    await log_meme_sent(next_meme["id"], Channel.TG_CHANNEL_EN)
