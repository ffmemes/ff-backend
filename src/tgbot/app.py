from telegram import (
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatBoostHandler,
    ChatMemberHandler,
    ChosenInlineResultHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from src.config import settings
from src.tgbot.constants import (
    LANG_SETTINGS_END_CALLBACK_DATA,
    LANG_SETTINGS_LANG_CHANGE_CALLBACK_PATTERN,
    MEME_BUTTON_CALLBACK_DATA_REGEXP,
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
    MEME_SOURCE_SET_LANG_REGEXP,
    MEME_SOURCE_SET_STATUS_REGEXP,
    POPUP_BUTTON_CALLBACK_DATA_REGEXP,
    # TELEGRAM_CHANNEL_EN_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
    # TELEGRAM_CHAT_RU_CHAT_ID,
    TELEGRAM_FEEDBACK_CHAT_ID,
)
from src.tgbot.handlers import (
    alerts,
    broken,
    error,
    inline,
    language,
    popup,
    reaction,
    start,
)
from src.tgbot.handlers.admin.boost import handle_chat_boost
from src.tgbot.handlers.admin.broadcast_text import (
    handle_broadcast_text_ru,
    handle_broadcast_text_ru_trigger,
)
from src.tgbot.handlers.admin.forward_channel import handle_forwarded_from_tgchannelru
from src.tgbot.handlers.admin.user_info import delete_user_data, handle_show_user_info
from src.tgbot.handlers.admin.waitlist import (
    handle_waitlist_invite,
    handle_waitlist_invite_before,
)
from src.tgbot.handlers.chat.chat_member import handle_chat_member_update

# from src.tgbot.handlers.chat.explain_meme import explain_meme_ru
from src.tgbot.handlers.chat.feedback import (
    handle_feedback_message,
    handle_feedback_reply,
)
from src.tgbot.handlers.moderator import get_meme, meme_source
from src.tgbot.handlers.stats.stats import handle_stats
from src.tgbot.handlers.stats.wrapped import handle_wrapped, handle_wrapped_button
from src.tgbot.handlers.upload import moderation, upload_meme

application: Application = None  # type: ignore


def add_handlers(application: Application) -> None:
    application.add_handler(
        CommandHandler(
            "start",
            start.handle_start,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    ###################
    # language settings
    application.add_handler(
        CommandHandler(
            "lang",
            language.handle_language_settings,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            language.handle_language_settings_button,
            pattern=LANG_SETTINGS_LANG_CHANGE_CALLBACK_PATTERN,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            language.handle_language_settings_end,
            pattern=LANG_SETTINGS_END_CALLBACK_DATA,
        )
    )

    ###################
    # user feedback & responses
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.Regex(r"^(\/c |\/chat|\/с)"),
            callback=handle_feedback_message,
        )
    )

    application.add_handler(
        MessageHandler(
            filters=filters.Chat(TELEGRAM_FEEDBACK_CHAT_ID) & filters.REPLY,
            callback=handle_feedback_reply,
        )
    )

    ####################
    # wrapped stats
    application.add_handler(
        CommandHandler(
            "wrapped",
            handle_wrapped,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    application.add_handler(
        CallbackQueryHandler(handle_wrapped_button, pattern=r"^wrapped_\d")
    )

    ####################
    # user stats
    application.add_handler(
        CommandHandler(
            "stats",
            handle_stats,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    ############## meme reaction
    application.add_handler(
        CallbackQueryHandler(
            reaction.handle_reaction,
            pattern=MEME_BUTTON_CALLBACK_DATA_REGEXP,
        )
    )

    ############## popup reaction
    application.add_handler(
        CallbackQueryHandler(
            popup.handle_popup_button,
            pattern=POPUP_BUTTON_CALLBACK_DATA_REGEXP,
        )
    )

    ############## admin
    # invite user from waitlist
    application.add_handler(
        CommandHandler(
            "invite",
            handle_waitlist_invite,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )
    application.add_handler(
        CommandHandler(
            "invite_before",
            handle_waitlist_invite_before,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE
            & filters.ForwardedFrom(chat_id=TELEGRAM_CHANNEL_RU_CHAT_ID),
            callback=handle_forwarded_from_tgchannelru,
        )
    )

    ######################
    # broadcast texts
    application.add_handler(
        CommandHandler(
            "broadcastru",
            handle_broadcast_text_ru,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcastru1",
            handle_broadcast_text_ru_trigger,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    ######################
    # handle new meme in channel discussion
    # application.add_handler(
    #     MessageHandler(
    #         filters=filters.Chat(TELEGRAM_CHAT_RU_CHAT_ID)
    #         & filters.PHOTO
    #         & filters.SenderChat(TELEGRAM_CHANNEL_RU_CHAT_ID),
    #         callback=explain_meme_ru,
    #     )
    # )

    ######################
    # meme upload by a user
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.PHOTO,
            # & (filters.PHOTO | filters.VIDEO | filters.ANIMATION),
            callback=upload_meme.handle_message_with_meme,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            upload_meme.handle_rules_accepted_callback,
            pattern=upload_meme.RULES_ACCEPTED_CALLBACK_DATA_REGEXP,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            upload_meme.handle_meme_upload_lang_other,
            pattern=upload_meme.LANGUAGE_SELECTED_OTHER_CALLBACK_DATA_REGEXP,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            upload_meme.handle_meme_upload_lang_selected,
            pattern=upload_meme.LANGUAGE_SELECTED_CALLBACK_DATA_REGEXP,
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            moderation.handle_uploaded_meme_review_button,
            pattern=moderation.UPLOADED_MEME_REVIEW_CALLBACK_DATA_REGEXP,
        )
    )

    # meme source management
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE
            & filters.Regex("^(https://t.me|https://vk.com|https://www.instagram.com)"),
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

    # user blocked bot or bot was added to a chat
    application.add_handler(
        ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # inline search
    application.add_handler(InlineQueryHandler(inline.search_inline))
    application.add_handler(
        ChosenInlineResultHandler(inline.handle_chosen_inline_result)
    )

    application.add_error_handler(error.send_stacktrace_to_tg_chat, block=False)

    # show meme / memes by ids
    application.add_handler(
        CommandHandler(
            "meme",
            get_meme.handle_get_meme,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    # show user info
    application.add_handler(
        MessageHandler(
            filters=filters.ChatType.PRIVATE & filters.Regex("^(@)"),
            callback=handle_show_user_info,
        )
    )

    # delete user data
    application.add_handler(
        CommandHandler(
            "delete",
            delete_user_data,
            filters=filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
        )
    )

    # handle boosts of a chat
    application.add_handler(
        ChatBoostHandler(
            handle_chat_boost,
            block=False,
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
        read_timeout=30,
        connect_timeout=30,
        write_timeout=30,
    )
