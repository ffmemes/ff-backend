from telegram.error import BadRequest, TimedOut

from src.tgbot.logs import log


class _BotWithHtmlFailure:
    def __init__(self) -> None:
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise BadRequest("Can't parse entities: unsupported start tag")


async def test_log_retries_invalid_html_as_plain_text():
    bot = _BotWithHtmlFailure()

    await log("⛔️ <b>BLOCKED</b> by <3", bot)

    assert len(bot.calls) == 2
    assert bot.calls[0]["parse_mode"] == "HTML"
    assert bot.calls[1]["parse_mode"] is None
    assert bot.calls[1]["text"] == "⛔️ <b>BLOCKED</b> by <3"


async def test_log_swallow_admin_chat_timeout():
    class Bot:
        async def send_message(self, **_kwargs):
            raise TimedOut("Timed out")

    await log("non-critical admin note", Bot())
