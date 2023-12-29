from telegram.ext import (
    Application, 
    CallbackQueryHandler, 
    CommandHandler, 
    CommandHandler,
    filters,
)
from telegram import (
    Update,
)

from src.config import settings
from src.tgbot.handlers.start import handle_start

application: Application = None  # type: ignore


def add_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", handle_start))


async def process_event(payload: dict) -> None:
    update = Update.de_json(payload, application.bot)

    # TODO: try await application.update_queue.put(update)
    # https://github.com/python-telegram-bot/python-telegram-bot/wiki/Webhooks#custom-solution
    
    await application.process_update(update)


async def setup_webhook(application: Application) -> None:
    await application.initialize()
    await application.bot.set_webhook(
        "https://" + settings.SITE_DOMAIN + "/tgbot/webhook",
        secret_token=settings.TELEGRAM_BOT_WEBHOOK_SECRET,
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