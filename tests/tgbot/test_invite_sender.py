import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

fake_bot_module = ModuleType("src.tgbot.bot")
fake_bot_module.bot = SimpleNamespace()
sys.modules["src.tgbot.bot"] = fake_bot_module


@pytest.mark.asyncio
async def test_successful_invitation_alert_shows_reward_and_balance(monkeypatch):
    from src.tgbot.senders import invite

    fake_bot = SimpleNamespace(send_message=AsyncMock())
    monkeypatch.setattr(invite, "bot", fake_bot)
    monkeypatch.setattr(
        invite,
        "get_user_info",
        AsyncMock(return_value={"interface_lang": "ru"}),
    )

    await invite.send_successfull_invitation_alert(
        invitor_user_id=123,
        invited_user_name="@ZXCeresha",
        balance=1200,
        reward_amount=100,
    )

    fake_bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="🎉 кореш @ZXCeresha в боте\nтебе капнуло +100 🍔\nбаланс: 1 200 🍔",
    )


def test_invitation_successful_alert_localizations_do_not_show_balance_command():
    from src import localizer

    for text in localizer.localizations["onboarding.invitation_successful_alert"].values():
        formatted = text.format(
            invited_user_name="@ZXCeresha",
            balance="1 200",
            reward_amount=100,
        )

        assert "/b" not in formatted
        assert "1 200" in formatted
