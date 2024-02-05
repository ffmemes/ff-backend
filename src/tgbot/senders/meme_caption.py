from src.storage.schemas import MemeData
from src.tgbot.constants import UserType
from src.tgbot.senders.utils import get_referral_html
from src.tgbot.user_info import get_user_info


async def get_meme_caption_for_user_id(meme: MemeData, user_id: int) -> str:
    user_info = await get_user_info(user_id)

    caption = meme.caption or ""

    caption += "\n\n" + get_referral_html(user_id, meme.id)

    if UserType(user_info["type"]).is_moderator:
        caption += f" #{meme.id}"

    return caption
