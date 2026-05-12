from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.tgbot.constants import (
    MEME_SOURCE_SET_LANG_REGEXP,
    MEME_SOURCE_SET_STATUS_REGEXP,
    SOURCE_CANDIDATE_ACTION_REGEXP,
)
from src.tgbot.handlers.moderator import get_meme, meme_source
from src.tgbot.handlers.moderator.invite import (
    MODERATOR_INVITE_CALLBACK_DATA,
    handle_moderator_invite_callback,
)
from src.tgbot.handlers.moderator.source_candidates import (
    handle_discovered_sources_command,
    handle_source_candidate_action,
)


def add_moderator_handlers(application: Application) -> None:
    application.add_handlers(
        [
            CallbackQueryHandler(
                handle_moderator_invite_callback,
                pattern=rf"^{MODERATOR_INVITE_CALLBACK_DATA}$",
            ),
            MessageHandler(
                filters=filters.ChatType.PRIVATE
                & filters.Regex("^(https://t.me|https://vk.com|https://www.instagram.com)"),
                callback=meme_source.handle_meme_source_link,
            ),
            CallbackQueryHandler(
                meme_source.handle_meme_source_language_selection,
                pattern=MEME_SOURCE_SET_LANG_REGEXP,
            ),
            CallbackQueryHandler(
                meme_source.handle_meme_source_change_status,
                pattern=MEME_SOURCE_SET_STATUS_REGEXP,
            ),
            CommandHandler(
                "discoveredsources",
                handle_discovered_sources_command,
                filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
            ),
            CallbackQueryHandler(
                handle_source_candidate_action,
                pattern=SOURCE_CANDIDATE_ACTION_REGEXP,
            ),
            CommandHandler(
                "meme",
                get_meme.handle_get_meme,
                filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
            ),
            CommandHandler(
                "show",
                get_meme.handle_show_memes,
                filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
            ),
        ]
    )
