import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src import localizer
from src.recommendations.meme_queue import (
    clear_meme_queue_for_user,
    generate_cold_start_recommendations,
)
from src.tgbot.constants import LANG_SETTINGS_END_CALLBACK_DATA
from src.tgbot.handlers.onboarding import onboarding_flow
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
    """Initialize user languages based on Telegram user data."""
    languages_to_add = set()

    if len(set(tg_user.full_name) & set(RUSSIAN_ALPHABET)) > 0:
        languages_to_add.add("ru")

    languages_to_add.add(
        "ru" if tg_user.language_code in localizer.ALMOST_CIS_LANGUAGES else "en"
    )

    if tg_user.language_code:
        languages_to_add.add(tg_user.language_code)

    await add_user_languages(tg_user.id, languages_to_add)


def create_language_button(
    lang: str, lang_text: str, is_selected: bool
) -> InlineKeyboardButton:
    """Create a language selection button."""
    if is_selected:
        callback_data = f"l:{lang}:del"
        button_text = f"✅ {lang_text or lang} ✅".upper()
    else:
        callback_data = f"l:{lang}:add"
        button_text = lang_text or lang

    return InlineKeyboardButton(button_text, callback_data=callback_data)


def create_language_keyboard(
    user_languages: set, interface_lang: str
) -> InlineKeyboardMarkup:
    """Create the language selection keyboard."""
    all_lang_buttons = [
        create_language_button(lang, lang_text, lang in user_languages)
        for lang, lang_text in SUPPORTED_MEME_LANGUAGES.items()
    ]

    lang_keyboard = [
        all_lang_buttons[i : i + 2] for i in range(0, len(all_lang_buttons), 2)
    ]

    if user_languages & set(SUPPORTED_MEME_LANGUAGES):
        end_button = InlineKeyboardButton(
            localizer.t("onboarding.language_settings_end_button", interface_lang),
            callback_data=LANG_SETTINGS_END_CALLBACK_DATA,
        )
        lang_keyboard.append([end_button])

    return InlineKeyboardMarkup(lang_keyboard)


async def handle_language_settings(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle language settings display and updates."""
    user_id = update.effective_user.id
    user_info = await get_user_info(user_id)
    user_languages = await get_user_languages(user_id)

    keyboard = create_language_keyboard(user_languages, user_info["interface_lang"])

    message_text = localizer.t(
        "onboarding.language_settings", user_info["interface_lang"]
    )
    send_message_kwargs = {
        "text": message_text,
        "parse_mode": ParseMode.HTML,
        "reply_markup": keyboard,
    }

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.message.edit_text(**send_message_kwargs)
        except BadRequest:
            pass  # Message content unchanged
    elif update.message:
        await update.message.reply_text(**send_message_kwargs)
    else:
        await update.effective_chat.send_message(**send_message_kwargs)


async def handle_language_settings_button(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle language selection button presses."""
    _, lang_code, action = update.callback_query.data.split(":")
    user_id = update.effective_user.id

    if action == "add":
        await add_user_language(user_id, lang_code)
    else:
        await del_user_language(user_id, lang_code)

    await update_user_info_cache(user_id)
    return await handle_language_settings(update, context)


async def handle_language_settings_end(
    update: telegram.Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the end of language settings."""
    await update.callback_query.answer()
    try:
        await update.callback_query.message.delete()
    except BadRequest:
        pass  # Message already deleted

    user_id = update.effective_user.id
    await clear_meme_queue_for_user(user_id)
    await generate_cold_start_recommendations(user_id)

    return await onboarding_flow(update, context.bot)
