from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from src import localizer
from src.tgbot.bot import bot
from src.tgbot.constants import POPUP_BUTTON_CALLBACK_DATA_PATTERN
from src.tgbot.schemas import Popup
from src.tgbot.senders.utils import get_random_emoji
from src.tgbot.service import create_user_popup_log, user_popup_already_sent


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
                        callback_data=POPUP_BUTTON_CALLBACK_DATA_PATTERN.format(
                            popup_id=popup_id
                        ),
                    )
                ]
            ]
        ),
    )


async def send_popup(user_id: int, popup: Popup) -> None:
    await bot.send_message(
        chat_id=user_id,
        text=popup.text,
        parse_mode=ParseMode.HTML,
        reply_markup=popup.reply_markup,
    )
    await create_user_popup_log(user_id, popup.id)


async def get_popup_to_send(user_id: int, user_info: dict) -> Popup | None:
    if user_info["nmemes_sent"] == 10:
        popup_id = "achievement.nmemes_sent_10"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] % 1000 == 33:
        popup_id = "popup.inline_search"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    # TODO:
    # 1. tell about our channels with best memes
    # 2. invite to update languages
    # 3. send a circle video with greeting from a team member
    # 4. tell about our github repo

    if user_info["nmemes_sent"] == 100:
        popup_id = "achievement.nmemes_sent_100"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    if user_info["nmemes_sent"] == 1000:
        popup_id = "achievement.nmemes_sent_1000"
        if not await user_popup_already_sent(user_id, popup_id):
            return _get_popup(popup_id, user_info)

    return None
