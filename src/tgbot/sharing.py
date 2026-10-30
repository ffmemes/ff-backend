import re
from dataclasses import dataclass
from urllib.parse import urlencode

from telegram import InlineKeyboardButton

from src import localizer
from src.config import settings
from src.tgbot.buttons import styled_inline_keyboard_button

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


def build_meme_share_button(
    *,
    meme_id: int,
    user_id: int,
    text: str,
    interface_lang: str | None,
    style: str | None = None,
) -> InlineKeyboardButton:
    return styled_inline_keyboard_button(
        text,
        url=get_meme_share_url(user_id, meme_id, interface_lang),
        style=style,
    )
