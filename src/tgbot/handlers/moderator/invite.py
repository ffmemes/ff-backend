"""Utilities and handlers for promoting power users to moderators."""

import logging
from collections.abc import Mapping

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest, TelegramError
from telegram.ext import ContextTypes

from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID, UserType
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import (
    add_user_tg_chat_membership,
    get_user_languages,
    update_user,
)
from src.tgbot.user_info import update_user_info_cache

INVITE_MESSAGE_TEMPLATE = (
    "🥳 Ты посмотрел {nmemes_sent} мемов! Нам очень нужна помощь модераторов "
    "в русской ленте Fast Food & Memes. Нажми кнопку ниже, чтобы получить "
    "одноразовую ссылку и присоединиться к нашему модераторскому чату."
)
INVITE_BUTTON_TEXT = "Хочу модерировать 🇷🇺"
MODERATOR_INVITE_CALLBACK_DATA = "moderator_invite:join"


async def maybe_send_moderator_invite(
    bot: Bot, user_id: int, user_info: Mapping[str, object]
) -> None:
    """Send a moderator invite when the user hits a milestone."""

    nmemes_sent = int(user_info.get("nmemes_sent") or 0)
    if nmemes_sent == 0 or nmemes_sent % 500 != 0:
        return

    raw_type = user_info.get("type")
    user_type = None
    if raw_type:
        try:
            user_type = UserType(str(raw_type))
        except ValueError:
            logging.warning(
                "Unknown user type '%s' for user %s when evaluating moderator invite",
                raw_type,
                user_id,
            )

    if user_type and user_type in (UserType.MODERATOR, UserType.ADMIN):
        return

    user_languages = await get_user_languages(user_id)
    if "ru" not in user_languages:
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=INVITE_BUTTON_TEXT,
                    callback_data=MODERATOR_INVITE_CALLBACK_DATA,
                )
            ]
        ]
    )

    await bot.send_message(
        chat_id=user_id,
        text=INVITE_MESSAGE_TEMPLATE.format(nmemes_sent=nmemes_sent),
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )
    logging.info(
        "Sent moderator invitation to user_id=%s for milestone=%s",
        user_id,
        nmemes_sent,
    )


async def handle_moderator_invite_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None or query.data != MODERATOR_INVITE_CALLBACK_DATA:
        return

    user_id = query.from_user.id

    try:
        invite_link = await context.bot.create_chat_invite_link(
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            creates_join_request=False,
            member_limit=1,
        )
    except TelegramError:
        logging.exception("Failed to generate moderator invite link for user_id=%s", user_id)
        await query.answer(text="Не получилось выдать ссылку, попробуй позже", show_alert=True)
        return

    if query.message and query.message.reply_markup is not None:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest as exc:
            if exc.message != "Message is not modified":
                raise

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            "Добро пожаловать в модераторскую команду! "
            f"Вот твоя одноразовая ссылка: {invite_link.invite_link}"
        ),
        disable_web_page_preview=True,
    )

    await add_user_tg_chat_membership(user_id, TELEGRAM_MODERATOR_CHAT_ID)
    await update_user(user_id, type=UserType.MODERATOR.value)
    await update_user_info_cache(user_id)

    logging.info("Promoted user_id=%s to moderator", user_id)

    await query.answer()
    await next_message(context.bot, user_id, prev_update=update)
