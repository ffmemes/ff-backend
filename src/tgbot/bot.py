from telegram.ext import (
    Application, 
    CallbackQueryHandler, 
    CommandHandler, 
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram import (
    Update,
)

from src.config import settings
from src.tgbot.handlers import start, upload, broken, reaction, alerts
from src.tgbot.constants import (
    MEME_BUTTON_CALLBACK_DATA_REGEXP, 
    MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA,
)

application: Application = None  # type: ignore


def add_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start.handle_start, filters=filters.ChatType.PRIVATE))

    application.add_handler(CallbackQueryHandler(
        reaction.handle_reaction,
        pattern=MEME_BUTTON_CALLBACK_DATA_REGEXP,
    ))

    application.add_handler(MessageHandler(
        filters=filters.ChatType.PRIVATE & filters.FORWARDED & filters.ATTACHMENT,
        callback=upload.handle_forward
    ))

    application.add_handler(MessageHandler(
        filters=filters.ChatType.PRIVATE & filters.ATTACHMENT,
        callback=upload.handle_message
    ))

    application.add_handler(CallbackQueryHandler(broken.handle_broken_callback_query, pattern="^"))
    application.add_handler(CallbackQueryHandler(alerts.handle_empty_meme_queue_alert, pattern=MEME_QUEUE_IS_EMPTY_ALERT_CALLBACK_DATA))


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
    application.run_polling(allowed_updates=Update.ALL_TYPES)