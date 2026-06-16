import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

fake_bot_module = ModuleType("src.tgbot.bot")
fake_bot_module.bot = SimpleNamespace()
sys.modules["src.tgbot.bot"] = fake_bot_module


@pytest.mark.asyncio
async def test_invited_user_reward_uses_single_balance_alert(monkeypatch):
    from src.tgbot.constants import UserType
    from src.tgbot.handlers import deep_link
    from src.tgbot.handlers.treasury.constants import TrxType

    get_user_by_id = AsyncMock(
        return_value={
            "id": 111,
            "blocked_bot_at": None,
            "type": UserType.USER,
        }
    )
    update_user = AsyncMock()
    get_tg_user_by_id = AsyncMock(return_value={"is_premium": False})
    pay_if_not_paid = AsyncMock(return_value=1200)
    pay_if_not_paid_with_alert = AsyncMock()
    send_successfull_invitation_alert = AsyncMock()
    log = AsyncMock()

    monkeypatch.setattr(deep_link, "get_user_by_id", get_user_by_id)
    monkeypatch.setattr(deep_link, "update_user", update_user)
    monkeypatch.setattr(deep_link, "get_tg_user_by_id", get_tg_user_by_id)
    monkeypatch.setattr(deep_link, "pay_if_not_paid", pay_if_not_paid)
    monkeypatch.setattr(deep_link, "pay_if_not_paid_with_alert", pay_if_not_paid_with_alert)
    monkeypatch.setattr(
        deep_link,
        "send_successfull_invitation_alert",
        send_successfull_invitation_alert,
    )
    monkeypatch.setattr(deep_link, "log", log)

    await deep_link.handle_invited_user(
        bot=SimpleNamespace(),
        invited_user={"id": 222},
        invited_user_name="@ZXCeresha",
        deep_link="m_111_333",
    )

    pay_if_not_paid.assert_awaited_once_with(
        111,
        TrxType.USER_INVITER,
        external_id="222",
    )
    pay_if_not_paid_with_alert.assert_not_awaited()
    send_successfull_invitation_alert.assert_awaited_once_with(
        111,
        "@ZXCeresha",
        balance=1200,
        reward_amount=100,
    )
