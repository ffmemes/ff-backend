from telegram import (
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatMemberHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.config import settings
from src.tgbot.constants import (
    MEME_BUTTON_CALLBACK_DATA_REGEXP,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
    MEME_SOURCE_SET_LANG_REGEXP,
    MEME_SOURCE_SET_STATUS_REGEXP,
)
from src.tgbot.handlers import (
    alerts,
    block,
    broken,
    error,
    reaction,
    start,
    upload,
    waitlist,
)
from src.tgbot.handlers.admin.user_info import handle_show_user_info
from src.tgbot.handlers.admin.waitlist import handle_waitlist_invite
from src.tgbot.handlers.moderator import get_meme, meme_source

application: Application = None  # type: ignore


def add_handlers(application: Application) -> None:
    application.add_handler(
        CommandHandler(
            "start",
            start.handle_start,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    # waitlist flow
    # language choose page
    application.add_handler(
        CallbackQueryHandler(
            waitlist.handle_waitlist_choose_language,
            pattern=waitlist.WAITLIST_CHOOSE_LANGUAGE_PAGE_CALLBACK_DATA,
        )
    )

    # select language button
    application.add_handler(
        CallbackQueryHandler(
            waitlist.handle_waitlist_language_button,
            pattern=waitlist.WAITLIST_LANGUAGE_CHANGE_CALLBACK_PATTERN,
        )
    )

    # finish language selection -> show channel sub page
    application.add_handler(
        CallbackQueryHandler(
            waitlist.handle_waitlist_channel_subscription,
            pattern=waitlist.WAITLIST_CHANNEL_SUBSCTIBTION_PAGE_CALLBACK_DATA,
        )
    )

    # check channel subscription button
    application.add_handler(
        CallbackQueryHandler(
            waitlist.handle_check_channel_subscription,
            pattern=waitlist.WAITLIST_CHANNEL_SUBSCRIBTION_CHECK_CALLBACK_DATA,
        )
    )

    # meme reaction
    application.add_handler(
        CallbackQueryHandler(
            reaction.handle_reaction,
            pattern=MEME_BUTTON_CALLBACK_DATA_REGEXP,
        )
    )

    # meme upload by a user
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.FORWARDED & filters.ATTACHMENT,
            callback=upload.handle_forward,
        )
    )

    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.ATTACHMENT,
            callback=upload.handle_message,
        )
    )

    # meme source management
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE
            & filters.Regex("^(https://t.me|https://vk.com)"),
            callback=meme_source.handle_meme_source_link,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            meme_source.handle_meme_source_language_selection,
            pattern=MEME_SOURCE_SET_LANG_REGEXP,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            alerts.handle_empty_meme_queue_alert,
            pattern=MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            meme_source.handle_meme_source_change_status,
            pattern=MEME_SOURCE_SET_STATUS_REGEXP,
        )
    )

    # user blocked bot handler
    application.add_handler(
        ChatMemberHandler(
            block.user_blocked_bot_handler, ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    application.add_error_handler(error.send_stacktrace_to_tg_chat)

    # admin: invite user from waitlist
    application.add_handler(
        CommandHandler(
            "invite",
            handle_waitlist_invite,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    # show meme / memes by ids
    application.add_handler(
        CommandHandler(
            "meme",
            get_meme.handle_get_meme,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    # show meme / memes by ids
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.Regex("^(@)"),
            callback=handle_show_user_info,
        )
    )

    # handle all old & broken callback queries
    application.add_handler(
        CallbackQueryHandler(broken.handle_broken_callback_query, pattern="^")
    )


async def process_event(payload: dict) -> None:
    update = Update.de_json(payload, application.bot)

    # TODO: try await application.update_queue.put(update)
    # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks#custom-solution

    await application.process_update(update)


async def setup_webhook(application: Application) -> None:
    await application.bot.set_webhook(
        "https://" + settings.SITE_DOMAIN + "/tgbot/webhook",
        secret_token=settings.TELEGRAM_BOT_WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
    )
    await application.start()


def setup_application(is_webhook: bool = False) -> Application:
    application_builder = Application.builder().token(settings.TELEGRAM_BOT_TOKEN)

    if is_webhook:
        application_builder.updater(None)

    application = application_builder.build()
    add_handlers(application)

    return application


def run_polling(application: Application) -> None:
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        timeout=60,
        read_timeout=10,
        connect_timeout=10,
    )
