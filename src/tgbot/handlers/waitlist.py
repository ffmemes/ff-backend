import telegram
from telegram.constants import ChatMemberStatus, ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.tgbot.handlers.language import ALMOST_CIS_LANGUAGES
from src.tgbot.service import (
    add_user_language,
    del_user_language,
    get_user_languages,
)
from src.tgbot.user_info import get_user_info, update_user_info_cache

# TODO: find a better place for these consts
LANGUAGE_CODE_TO_TEXT = {
    "ru": "🇷🇺 Русский",
    "en": "🇺🇸 English",
    "uk": "🇺🇦 Українська",
}

SUPPORTED_MEME_LANGUAGES = ["ru", "en", "uk"]
WAITLIST_CHOOSE_LANGUAGE_PAGE_CALLBACK_DATA = "waitlist:choose_language"
WAITLIST_LANGUAGE_CHANGE_CALLBACK_PATTERN = r"^l:\w+:(add|del)"

WAITLIST_CHANNEL_SUBSCTIBTION_PAGE_CALLBACK_DATA = "waitlist:channel_subscription"
WAITLIST_CHANNEL_SUBSCRIBTION_CHECK_CALLBACK_DATA = "waitlist:subscription_check"

TELEGRAM_CHANNEL_EN_CHAT_ID = -1002120551028
TELEGRAM_CHANNEL_EN_LINK = "https://t.me/fast_food_memes"

TELEGRAM_CHANNEL_RU_CHAT_ID = -1001152876229
TELEGRAM_CHANNEL_RU_LINK = "https://t.me/fastfoodmemes"


async def handle_waitlist_start(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    await update.effective_user.send_message(
        localizer.t("waitlist.start", user_info["interface_lang"]),
        parse_mode=ParseMode.HTML,
        reply_markup=telegram.InlineKeyboardMarkup(
            [
                [
                    telegram.InlineKeyboardButton(
                        localizer.t(
                            "waitlist.button_to_language_choose",
                            user_info["interface_lang"],
                        ),
                        callback_data=WAITLIST_CHOOSE_LANGUAGE_PAGE_CALLBACK_DATA,
                    )
                ]
            ]
        ),
    )


async def handle_waitlist_choose_language(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    user_languages = await get_user_languages(update.effective_user.id)

    all_lang_buttons = []
    for lang in SUPPORTED_MEME_LANGUAGES:
        if lang in user_languages:
            callback_data = f"l:{lang}:del"
            button_text = f"{LANGUAGE_CODE_TO_TEXT[lang] or lang} ✅"
        else:
            callback_data = f"l:{lang}:add"
            button_text = LANGUAGE_CODE_TO_TEXT[lang] or lang

        all_lang_buttons.append(
            telegram.InlineKeyboardButton(button_text, callback_data=callback_data)
        )

    # two buttons per line
    lang_keyboard = [
        all_lang_buttons[i : i + 2] for i in range(0, len(all_lang_buttons), 2)
    ]
    try:
        await update.callback_query.message.edit_text(
            localizer.t("waitlist.language_choose", user_info["interface_lang"]),
            parse_mode=ParseMode.HTML,
            reply_markup=telegram.InlineKeyboardMarkup(
                lang_keyboard
                + [
                    [
                        telegram.InlineKeyboardButton(
                            localizer.t(
                                "waitlist.button_to_channel_subscribe",
                                user_info["interface_lang"],
                            ),
                            callback_data=WAITLIST_CHANNEL_SUBSCTIBTION_PAGE_CALLBACK_DATA,
                        )
                    ],
                ]
            ),
        )
    except telegram.error.BadRequest as e:
        if e.message == "Message is not modified":
            return
        raise e


async def handle_waitlist_language_button(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _, lang_code, action = update.callback_query.data.split(":")

    if action == "add":
        await add_user_language(update.effective_user.id, lang_code)
    else:
        await del_user_language(update.effective_user.id, lang_code)

    _ = await update_user_info_cache(update.effective_user.id)
    return await handle_waitlist_choose_language(update, context)


async def handle_waitlist_channel_subscription(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)

    # in case a user decide to turn off ru / en language
    # we need to turn them back since almost all of our memes
    # are in these languages
    # TODO: refactor this

    user_languages = await get_user_languages(update.effective_user.id)
    if not user_languages & {"ru", "en"}:
        enable_lang = (
            "ru" if user_info["interface_lang"] in ALMOST_CIS_LANGUAGES else "en"
        )
        await add_user_language(update.effective_user.id, enable_lang)
        user_info = await update_user_info_cache(update.effective_user.id)
        await update.callback_query.answer(
            localizer.t(
                "waitlist.we_enabled_language_alert", user_info["interface_lang"]
            ).format(language=LANGUAGE_CODE_TO_TEXT[enable_lang]),
            show_alert=True,
        )

    # different channels to subscribe
    if user_info["interface_lang"] in ALMOST_CIS_LANGUAGES:
        channel_link = TELEGRAM_CHANNEL_RU_LINK
    else:
        channel_link = TELEGRAM_CHANNEL_EN_LINK

    await update.callback_query.message.edit_text(
        localizer.t("waitlist.channel_subscribe", user_info["interface_lang"]).format(
            channel_link=channel_link
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=telegram.InlineKeyboardMarkup(
            [
                [
                    telegram.InlineKeyboardButton(
                        localizer.t(
                            "waitlist.check_channel_subscribtion",
                            user_info["interface_lang"],
                        ),
                        callback_data=WAITLIST_CHANNEL_SUBSCRIBTION_CHECK_CALLBACK_DATA,
                    )
                ]
            ]
        ),
    )


async def handle_check_channel_subscription(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    if user_info["interface_lang"] in ALMOST_CIS_LANGUAGES:
        channel_chat_id = TELEGRAM_CHANNEL_RU_CHAT_ID
        channel_link = TELEGRAM_CHANNEL_RU_LINK
    else:
        channel_chat_id = TELEGRAM_CHANNEL_EN_CHAT_ID
        channel_link = TELEGRAM_CHANNEL_EN_LINK

    try:
        res = await context.bot.get_chat_member(
            chat_id=channel_chat_id, user_id=update.effective_user.id
        )
        if res.status in [
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.OWNER,
        ]:
            await update.callback_query.answer(
                localizer.t(
                    "waitlist.channel_subscribed_alert", user_info["interface_lang"]
                )
            )
            return await handle_waitlist_final(update, context)

    except telegram.error.BadRequest as e:
        if e.message == "Chat not found":
            raise Exception(f"Add bot to channel admins: {channel_link}")

    await update.callback_query.answer(
        localizer.t(
            "waitlist.channel_not_subscribed_alert", user_info["interface_lang"]
        ).format(channel_link=channel_link),
        show_alert=True,
    )
    return await handle_waitlist_channel_subscription(update, context)


async def handle_waitlist_final(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_info = await get_user_info(update.effective_user.id)
    await update.callback_query.message.edit_text(
        localizer.t("waitlist.final", user_info["interface_lang"]),
        parse_mode=ParseMode.HTML,
    )
