import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, SwitchInlineQueryChosenChat

from src import localizer
from src.config import settings
from src.flows.events import safe_emit
from src.tgbot.service import assign_experiment, get_experiment_variant

logger = logging.getLogger(__name__)

MEME_SHARE_BUTTON_EXPERIMENT_ID = "meme_share_button"
MEME_SHARE_BUTTON_URL = "url_share"
MEME_SHARE_BUTTON_INLINE = "inline_query"
MEME_REACTION_CONTEXT_ONBOARD = "onboard"
MEME_SHARE_DEEP_LINK_PREFIX = "m"

_SHARE_DEEP_LINK_RE = re.compile(r"^(?:m|s)_(?P<sharer_user_id>\d+)_(?P<meme_id>\d+)$")


@dataclass(frozen=True)
class MemeShareDeepLink:
    sharer_user_id: int
    meme_id: int


def parse_meme_share_deep_link(deep_link: str | None) -> MemeShareDeepLink | None:
    if not deep_link:
        return None

    match = _SHARE_DEEP_LINK_RE.match(deep_link)
    if match is None:
        return None

    return MemeShareDeepLink(
        sharer_user_id=int(match.group("sharer_user_id")),
        meme_id=int(match.group("meme_id")),
    )


def get_meme_share_deep_link(user_id: int, meme_id: int) -> str:
    return f"{MEME_SHARE_DEEP_LINK_PREFIX}_{user_id}_{meme_id}"


def get_meme_share_link(user_id: int, meme_id: int) -> str:
    deep_link = get_meme_share_deep_link(user_id, meme_id)
    return f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}?start={deep_link}"


def get_meme_share_button_text(interface_lang: str | None) -> str:
    return localizer.t("meme.share_button", interface_lang)


def get_meme_share_text(interface_lang: str | None) -> str:
    return localizer.t("meme.share_text", interface_lang)


def get_meme_share_url(user_id: int, meme_id: int, interface_lang: str | None) -> str:
    params = urlencode(
        {
            "url": get_meme_share_link(user_id, meme_id),
            "text": get_meme_share_text(interface_lang),
        }
    )
    return f"https://t.me/share/url?{params}"


def get_meme_inline_query(meme_id: int) -> str:
    return f"#{meme_id}"


def build_meme_share_assignment(user_id: int) -> tuple[str, dict[str, Any]]:
    key = f"{MEME_SHARE_BUTTON_EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 2
    variant = MEME_SHARE_BUTTON_URL if bucket == 0 else MEME_SHARE_BUTTON_INLINE
    return variant, {
        "assignment_strategy": "sha256(experiment_id:user_id)%2",
        "url_share": "t.me/share/url with m_{sharer_user_id}_{meme_id}",
        "inline_query": "switch_inline_query_chosen_chat with #meme_id",
    }


async def get_or_assign_meme_share_button_variant(user_id: int) -> str:
    if not settings.TELEGRAM_INLINE_SHARE_ENABLED:
        return MEME_SHARE_BUTTON_URL

    try:
        variant = await get_experiment_variant(user_id, MEME_SHARE_BUTTON_EXPERIMENT_ID)
        if variant is not None:
            return variant

        proposed, metadata = build_meme_share_assignment(user_id)
        inserted = await assign_experiment(
            user_id,
            MEME_SHARE_BUTTON_EXPERIMENT_ID,
            proposed,
            metadata,
        )
        if inserted:
            safe_emit(
                f"ff.experiment.{MEME_SHARE_BUTTON_EXPERIMENT_ID}.evaluated",
                f"user.{user_id}",
                {"user_id": user_id, "group": proposed},
            )
            return proposed

        return (
            await get_experiment_variant(user_id, MEME_SHARE_BUTTON_EXPERIMENT_ID)
            or MEME_SHARE_BUTTON_URL
        )
    except Exception:
        logger.warning("meme share-button assignment failed for user %d", user_id, exc_info=True)
        return MEME_SHARE_BUTTON_URL


def build_meme_share_button(
    *,
    meme_id: int,
    user_id: int,
    text: str,
    variant: str,
    interface_lang: str | None,
    meme_type: str | None = None,
) -> InlineKeyboardButton:
    # Cached inline results are reliable for photos/videos. Animation file IDs
    # may be GIF or MPEG4, so use the URL adapter until we store the subtype.
    supports_exact_inline = meme_type not in {"animation"}
    if variant == MEME_SHARE_BUTTON_INLINE and supports_exact_inline:
        return InlineKeyboardButton(
            text,
            switch_inline_query_chosen_chat=SwitchInlineQueryChosenChat(
                query=get_meme_inline_query(meme_id),
                allow_user_chats=True,
                allow_bot_chats=False,
                allow_group_chats=True,
                allow_channel_chats=True,
            ),
        )

    return InlineKeyboardButton(
        text,
        url=get_meme_share_url(user_id, meme_id, interface_lang),
    )
