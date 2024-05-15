import telegram
from telegram import User
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src import localizer
from src.recommendations.meme_queue import (
    clear_meme_queue_for_user,
    generate_cold_start_recommendations,
)
from src.tgbot.constants import (
    LANG_SETTINGS_END_CALLBACK_DATA,
)
from src.tgbot.handlers.onboarding import onboarding_flow
from src.tgbot.senders.next_message import next_message
from src.tgbot.service import (
    add_user_language,
    add_user_languages,
    del_user_language,
    get_user_languages,
)
from src.tgbot.user_info import get_user_info, update_user_info_cache

RUSSIAN_ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"


SUPPORTED_MEME_LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇺🇸 English",
    "uk": "🇺🇦 Українська",
    "es": "🇪🇸 Español",
    "fa": "🇮🇷 فارسی",
    "hi": "🇮🇳 हिन्दी",
}


async def init_user_languages_from_tg_user(tg_user: User):
    """
    When user press /start we add languages to user
    """
    languages_to_add = set()

    name_with_slavic_letters = len(set(tg_user.full_name) & set(RUSSIAN_ALPHABET)) > 0
    if name_with_slavic_letters:
        languages_to_add.add("ru")

    # add languages ru / en since they are the most common
    if tg_user.language_code in localizer.ALMOST_CIS_LANGUAGES:
        languages_to_add.add("ru")
    else:
        languages_to_add.add("en")

    if tg_user.language_code is not None:
        languages_to_add.add(tg_user.language_code)

    await add_user_languages(tg_user.id, languages_to_add)


async def handle_language_settings(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Shows language settings
    Maybe be called from a command or from a button
    """

    user_info = await get_user_info(update.effective_user.id)
    user_languages = await get_user_languages(update.effective_user.id)

    all_lang_buttons = []
    for lang, lang_text in SUPPORTED_MEME_LANGUAGES.items():
        if lang in user_languages:
            callback_data = f"l:{lang}:del"
            button_text = f"✅ {lang_text or lang} ✅".upper()
        else:
            callback_data = f"l:{lang}:add"
            button_text = lang_text or lang

        all_lang_buttons.append(
            telegram.InlineKeyboardButton(button_text, callback_data=callback_data)
        )

    # two buttons per line
    lang_keyboard = [
        all_lang_buttons[i : i + 2] for i in range(0, len(all_lang_buttons), 2)
    ]

    # add end button if user has any of the supported languages
    if len(user_languages & set(SUPPORTED_MEME_LANGUAGES)) > 0:
        lang_keyboard += [
            [
                telegram.InlineKeyboardButton(
                    localizer.t(
                        "onboarding.language_settings_end_button",
                        user_info["interface_lang"],
                    ),
                    callback_data=LANG_SETTINGS_END_CALLBACK_DATA,
                )
            ],
        ]

    send_message_kwargs = {
        "text": localizer.t(
            "onboarding.language_settings",
            user_info["interface_lang"],
        ),
        "parse_mode": ParseMode.HTML,
        "reply_markup": telegram.InlineKeyboardMarkup(lang_keyboard),
    }

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text(**send_message_kwargs)
        except telegram.error.BadRequest:
            # specified new message content and reply markup are exactly the same
            pass
    elif update.message:
        await update.message.reply_text(**send_message_kwargs)
    else:
        await update.effective_chat.send_message(**send_message_kwargs)


# callback_data: l:{lang_code}:{add/del}
async def handle_language_settings_button(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    _, lang_code, action = update.callback_query.data.split(":")

    if action == "add":
        await add_user_language(update.effective_user.id, lang_code)
    else:
        await del_user_language(update.effective_user.id, lang_code)

    _ = await update_user_info_cache(update.effective_user.id)
    return await handle_language_settings(update, context)


# callback_data: LANG_END_CALLBACK_DATA
async def handle_language_settings_end(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.callback_query.answer()
    try:
        await update.callback_query.message.delete()
    except telegram.error.BadRequest:
        pass  # message was already deleted (network lagging)

    user_info = await get_user_info(update.effective_user.id)

    await clear_meme_queue_for_user(update.effective_user.id)
    await generate_cold_start_recommendations(update.effective_user.id)

    recently_joined = user_info["nmemes_sent"] <= 3
    if recently_joined:
        return await onboarding_flow(update, context.bot)

    return await next_message(
        context.bot,
        update.effective_user.id,
        prev_update=update,
        prev_reaction_id=None,
    )
