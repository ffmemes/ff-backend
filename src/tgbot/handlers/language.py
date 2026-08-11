import re

import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, User
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from src import localizer
from src.recommendations.meme_queue import (
    clear_meme_queue_for_user,
    generate_recommendations,
)
from src.recommendations.service import get_user_reactions
from src.tgbot.constants import (
    LANG_SETTINGS_END_CALLBACK_DATA,
    ONBOARDING_LANG_CALLBACK_DATA_PATTERN,
)
from src.tgbot.handlers.onboarding import onboarding_flow
from src.tgbot.service import (
    add_user_language,
    add_user_languages,
    del_user_language,
    get_user_languages,
    set_user_languages_exclusive,
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

# Telegram app language that is a reliable meme-content signal.
# `en` is intentionally NOT auto-trusted (often default / VPN / US app store).
_AUTO_CONTENT_LANG_FROM_TG = frozenset({"ru", "uk", "es", "fa", "hi"})


async def init_user_languages_from_tg_user(tg_user: User):
    """Initialize user languages based on Telegram user data (legacy multi-seed).

    Prefer :func:`resolve_onboarding_auto_language` for new-user onboarding.
    Kept for orphans / existing users with empty ``user_language``.
    """
    languages_to_add = set()

    if len(set(tg_user.full_name) & set(RUSSIAN_ALPHABET)) > 0:
        languages_to_add.add("ru")

    languages_to_add.add("ru" if tg_user.language_code in localizer.ALMOST_CIS_LANGUAGES else "en")

    if tg_user.language_code:
        languages_to_add.add(tg_user.language_code)

    await add_user_languages(tg_user.id, languages_to_add)


def _normalize_tg_lang(language_code: str | None) -> str | None:
    if not language_code:
        return None
    return language_code.lower().replace("_", "-").split("-", 1)[0]


def resolve_onboarding_auto_language(tg_user: User) -> str | None:
    """Primary content language we can set without asking, or None to show picker.

    - Cyrillic in display name → ``ru``
    - Telegram CIS codes → ``ru`` (except explicit ``uk``)
    - Strong non-EN app languages we serve → that code
    - bare ``en`` / unknown → ask (EN is a weak signal)
    """
    full_name = tg_user.full_name or ""
    if len(set(full_name) & set(RUSSIAN_ALPHABET)) > 0:
        return "ru"

    base = _normalize_tg_lang(tg_user.language_code)
    if not base:
        return None
    if base == "uk":
        return "uk"
    if base in localizer.ALMOST_CIS_LANGUAGES or base == "ru":
        return "ru"
    if base in _AUTO_CONTENT_LANG_FROM_TG and base in SUPPORTED_MEME_LANGUAGES:
        return base
    return None


def _picker_interface_lang(tg_user: User) -> str:
    base = _normalize_tg_lang(tg_user.language_code) or "en"
    if base in localizer.ALMOST_CIS_LANGUAGES or base == "ru":
        return "ru"
    return base if base in ("en", "uk", "es") else "en"


def create_onboarding_language_keyboard() -> InlineKeyboardMarkup:
    """One primary language per tap — not multi-select."""
    rows = [
        [
            InlineKeyboardButton(
                label,
                callback_data=ONBOARDING_LANG_CALLBACK_DATA_PATTERN.format(lang=code),
            )
        ]
        for code, label in SUPPORTED_MEME_LANGUAGES.items()
    ]
    return InlineKeyboardMarkup(rows)


async def send_onboarding_language_picker(
    update: telegram.Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Show single-choice language picker; onboarding continues after a tap."""
    interface_lang = _picker_interface_lang(update.effective_user)
    text = localizer.t("onboarding.pick_language", interface_lang)
    kwargs = {
        "text": text,
        "parse_mode": ParseMode.HTML,
        "reply_markup": create_onboarding_language_keyboard(),
    }
    try:
        if update.message:
            await update.message.reply_text(**kwargs)
        else:
            await update.effective_chat.send_message(**kwargs)
    except Forbidden:
        pass


async def handle_onboarding_language_selected(
    update: telegram.Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Single-language onboarding choice → set language → welcome + first meme."""
    query = update.callback_query
    if query is None or not query.data:
        return

    match = re.fullmatch(r"ol:([\w-]{2,8})", query.data)
    if not match:
        await query.answer()
        return

    lang = match.group(1)
    if lang not in SUPPORTED_MEME_LANGUAGES:
        await query.answer()
        return

    user_id = update.effective_user.id
    await query.answer()
    await set_user_languages_exclusive(user_id, [lang])
    await update_user_info_cache(user_id)
    await clear_meme_queue_for_user(user_id)
    await generate_recommendations(user_id, limit=5)

    try:
        await query.message.delete()
    except BadRequest:
        pass

    return await onboarding_flow(update, context.bot)


def create_language_button(lang: str, lang_text: str, is_selected: bool) -> InlineKeyboardButton:
    """Create a language selection button."""
    if is_selected:
        callback_data = f"l:{lang}:del"
        button_text = f"✅ {lang_text or lang} ✅".upper()
    else:
        callback_data = f"l:{lang}:add"
        button_text = lang_text or lang

    return InlineKeyboardButton(button_text, callback_data=callback_data)


def create_language_keyboard(user_languages: set, interface_lang: str) -> InlineKeyboardMarkup:
    """Create the language selection keyboard."""
    all_lang_buttons = [
        create_language_button(lang, lang_text, lang in user_languages)
        for lang, lang_text in SUPPORTED_MEME_LANGUAGES.items()
    ]

    lang_keyboard = [all_lang_buttons[i : i + 2] for i in range(0, len(all_lang_buttons), 2)]

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

    message_text = localizer.t("onboarding.language_settings", user_info["interface_lang"])
    send_message_kwargs = {
        "text": message_text,
        "parse_mode": ParseMode.HTML,
        "reply_markup": keyboard,
    }

    try:
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
    except Forbidden:
        pass  # User blocked the bot


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
    await generate_recommendations(user_id, limit=5)

    if await get_user_reactions(user_id):
        return None

    return await onboarding_flow(update, context.bot)
