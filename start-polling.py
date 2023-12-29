from src.tgbot import bot


if __name__ == "__main__":
    application = bot.setup_application(is_webhook=False)
    bot.run_polling(application)