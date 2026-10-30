"""Single seam for preparing a meme for Telegram delivery.

Both the reaction hot path (`next_message`) and direct send (`send_meme_to_user`)
must build the same share button + caption + keyboard. CTA / share experiments
should touch this module only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from telegram import InlineKeyboardMarkup

from src.storage.schemas import MemeData
from src.tgbot.senders.keyboards import meme_reaction_keyboard
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.senders.utils import collect_user_languages
from src.tgbot.sharing import get_meme_share_button_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedMemeDelivery:
    caption: str
    reply_markup: InlineKeyboardMarkup
    languages: frozenset[str]


async def prepare_meme_delivery(
    *,
    user_id: int,
    meme: MemeData,
    user_info: dict,
    reaction_context: str | None = None,
) -> PreparedMemeDelivery:
    languages = await collect_user_languages(user_id, user_info.get("interface_lang"))
    referral_button_text = get_meme_share_button_text(user_info.get("interface_lang"))
    logger.debug(
        "Prepared meme %s for user %s share_button='%s' languages=%s",
        meme.id,
        user_id,
        referral_button_text,
        sorted(languages),
    )
    reply_markup = meme_reaction_keyboard(
        meme.id,
        user_id,
        referral_button_text,
        share_button=True,
        interface_lang=user_info.get("interface_lang"),
        reaction_context=reaction_context,
    )
    caption = await get_meme_caption_for_user_id(meme, user_id, user_info)
    return PreparedMemeDelivery(
        caption=caption,
        reply_markup=reply_markup,
        languages=frozenset(languages),
    )
