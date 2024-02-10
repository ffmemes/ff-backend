from sqlalchemy.dialects.postgresql import insert

from src.crossposting.constants import Channel
from src.database import (
    crossposting,
    fetch_one,
)


async def log_meme_sent(meme_id: int, channel: Channel) -> None:
    insert_statement = insert(crossposting).values(
        {"meme_id": meme_id, "channel": channel.value}
    )

    await fetch_one(insert_statement)


async def get_next_meme_for_tg_channel_ru():
    pass


async def get_next_meme_for_tg_channel_en():
    pass


async def get_next_meme_for_vk_group_ru():
    pass
