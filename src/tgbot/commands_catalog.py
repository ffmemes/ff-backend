"""User-facing bot command surface (menu + help).

Keep the Telegram ☰ menu intentionally tiny. Secondary commands live in /help.
See docs/product/surface-and-commands.md.
"""

from __future__ import annotations

import logging

from telegram import Bot, BotCommand

logger = logging.getLogger(__name__)

# Default menu language + per-language overrides for set_my_commands.
# /last is always first — the only high-frequency command we want in ☰.
MENU_COMMANDS_DEFAULT: list[tuple[str, str]] = [
    ("last", "Show previous meme"),
    ("help", "What this bot can do"),
]

MENU_COMMANDS_BY_LANG: dict[str, list[tuple[str, str]]] = {
    "ru": [
        ("last", "Предыдущий мем"),
        ("help", "Что умеет бот"),
    ],
    "en": MENU_COMMANDS_DEFAULT,
    "uk": [
        ("last", "Попередній мем"),
        ("help", "Що вміє бот"),
    ],
}

# Public command names for the last/help surface (typed or menu).
PUBLIC_COMMANDS = frozenset(
    {
        "last",
        "previous",
        "prev",
        "help",
    }
)


def menu_bot_commands(language_code: str | None = None) -> list[BotCommand]:
    pairs = MENU_COMMANDS_BY_LANG.get(language_code or "", MENU_COMMANDS_DEFAULT)
    return [BotCommand(command=name, description=desc) for name, desc in pairs]


async def sync_bot_commands(bot: Bot) -> None:
    """Push the user menu to Telegram (default + a few language codes)."""
    try:
        await bot.set_my_commands(menu_bot_commands())
        for lang in ("ru", "en", "uk"):
            await bot.set_my_commands(menu_bot_commands(lang), language_code=lang)
    except Exception:
        logger.exception("Failed to sync Telegram bot commands menu")
