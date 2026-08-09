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
from src.tgbot.senders.meme_like_count_experiment import get_visible_meme_like_count
from src.tgbot.senders.utils import collect_user_languages
from src.tgbot.sharing import (
    get_meme_share_button_text,
    get_or_assign_meme_share_button_variant,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedMemeDelivery:
    caption: str
    reply_markup: InlineKeyboardMarkup
    share_button_variant: str
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
    share_button_variant = await get_or_assign_meme_share_button_variant(user_id)
    logger.debug(
        "Prepared meme %s for user %s share_button='%s' variant=%s languages=%s",
        meme.id,
        user_id,
        referral_button_text,
        share_button_variant,
        sorted(languages),
    )
    reply_markup = meme_reaction_keyboard(
        meme.id,
        user_id,
        referral_button_text,
        visible_like_count=await get_visible_meme_like_count(user_id, meme.nlikes),
        share_button_variant=share_button_variant,
        interface_lang=user_info.get("interface_lang"),
        reaction_context=reaction_context,
        meme_type=meme.type.value,
    )
    caption = await get_meme_caption_for_user_id(meme, user_id, user_info)
    return PreparedMemeDelivery(
        caption=caption,
        reply_markup=reply_markup,
        share_button_variant=share_button_variant,
        languages=frozenset(languages),
    )
