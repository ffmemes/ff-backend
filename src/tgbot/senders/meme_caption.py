from html import escape

from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.senders.utils import get_referral_html


async def get_meme_caption_for_user_id(
    meme: MemeData,
    user_id: int,
    user_info: dict,
) -> str:
    caption = escape(meme.caption, quote=False) if meme.caption else ""

    caption += "\n\n" + get_referral_html(user_id, meme.id)

    if UserType(user_info["type"]).is_moderator:
        caption += f" #{meme.id}"

    return caption
