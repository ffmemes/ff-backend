import logging
from collections.abc import Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import POPUP_BUTTON_CALLBACK_DATA_PATTERN
from src.tgbot.schemas import Popup
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import (
    create_user_popup_log,
    user_popup_already_sent,
)
from src.tgbot.utils import get_related_channel_link

logger = logging.getLogger(__name__)


PopupFactory = Callable[[str, dict], Popup]
PopupPredicate = Callable[[int], bool]
StaticPopupRule = tuple[PopupPredicate, str, PopupFactory]


def _sent_count_is(expected: int) -> PopupPredicate:
    return lambda nmemes_sent: nmemes_sent == expected


def _sent_count_mod_1000_is(expected: int) -> PopupPredicate:
    return lambda nmemes_sent: nmemes_sent % 1000 == expected


def _get_popup(popup_id: str, user_info: dict) -> Popup:
    # TODO: alertn when we don't have localization for the popup
    return Popup(
        id=popup_id,
        text=localizer.t(popup_id, user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_random_emoji() * 3,
                        callback_data=POPUP_BUTTON_CALLBACK_DATA_PATTERN.format(popup_id=popup_id),
                    )
                ]
            ]
        ),
    )


def _get_channel_popup(popup_id: str, user_info: dict) -> Popup:
    channel_link = get_related_channel_link(user_info["interface_lang"])
    return Popup(
        id=popup_id,
        text=localizer.t(popup_id, user_info["interface_lang"]),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📢 Subscribe",
                        url=channel_link,
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ I subscribed",
                        callback_data=POPUP_BUTTON_CALLBACK_DATA_PATTERN.format(popup_id=popup_id),
                    )
                ],
            ]
        ),
    )


STATIC_POPUP_RULES: tuple[StaticPopupRule, ...] = (
    (_sent_count_is(10), "achievement.nmemes_sent_10", _get_popup),
    (_sent_count_mod_1000_is(20), "popup.upload_meme", _get_popup),
    (_sent_count_mod_1000_is(5), "popup.telegram_channel", _get_channel_popup),
    (_sent_count_mod_1000_is(70), "popup.github_repo", _get_popup),
    (_sent_count_mod_1000_is(90), "popup.feedback", _get_popup),
    (_sent_count_is(100), "achievement.nmemes_sent_100", _get_popup),
    (_sent_count_is(1000), "achievement.nmemes_sent_1000", _get_popup),
)


async def send_popup(user_id: int, popup: Popup) -> None:
    await bot.send_message(
        chat_id=user_id,
        text=popup.text,
        parse_mode=ParseMode.HTML,
        reply_markup=popup.reply_markup,
    )
    await create_user_popup_log(user_id, popup.id)


async def _unsent_popup(
    user_id: int,
    popup_id: str,
    user_info: dict,
    popup_factory: PopupFactory | None = None,
) -> Popup | None:
    if await user_popup_already_sent(user_id, popup_id):
        return None
    popup_factory = popup_factory or _get_popup
    return popup_factory(popup_id, user_info)


async def _static_popup(user_id: int, user_info: dict) -> Popup | None:
    nmemes_sent = user_info["nmemes_sent"]
    for matches, popup_id, popup_factory in STATIC_POPUP_RULES:
        if matches(nmemes_sent):
            return await _unsent_popup(user_id, popup_id, user_info, popup_factory)
    return None


async def get_popup_to_send(user_id: int, user_info: dict) -> Popup | None:
    popup = await _static_popup(user_id, user_info)
    if popup is not None:
        return popup

    # TODO:
    # 1. invite to update languages
    # 2. send a circle video with greeting from a team member
    return None
