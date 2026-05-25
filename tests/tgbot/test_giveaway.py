from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.tgbot.handlers.treasury.constants import TrxType
from src.tgbot.handlers.treasury.giveaway import handle_giveaway


def _make_update(user_id: int = 90203):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id))


def _make_context():
    return SimpleNamespace(bot=AsyncMock())


@pytest.mark.asyncio
async def test_channel_audience_giveaway_uses_tagged_ten_burger_reward():
    update = _make_update()
    context = _make_context()
    deep_link = "giveaway_channel_audience_2026_05_25"

    with (
        patch(
            "src.tgbot.handlers.treasury.giveaway.pay_if_not_paid",
            new_callable=AsyncMock,
            return_value=10,
        ) as pay,
        patch(
            "src.tgbot.handlers.treasury.giveaway.next_message",
            new_callable=AsyncMock,
        ) as next_message,
    ):
        await handle_giveaway(update, context, deep_link)

    pay.assert_awaited_once_with(
        update.effective_user.id,
        TrxType.CHANNEL_AUDIENCE_GIVEAWAY,
        deep_link,
    )
    context.bot.send_message.assert_awaited_once()
    assert "+<b>10</b>" in context.bot.send_message.await_args.kwargs["text"]
    next_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_giveaway_keeps_legacy_payout_type():
    update = _make_update()
    context = _make_context()

    with (
        patch(
            "src.tgbot.handlers.treasury.giveaway.pay_if_not_paid",
            new_callable=AsyncMock,
            return_value=77,
        ) as pay,
        patch("src.tgbot.handlers.treasury.giveaway.next_message", new_callable=AsyncMock),
    ):
        await handle_giveaway(update, context, "giveaway_77")

    pay.assert_awaited_once_with(
        update.effective_user.id,
        TrxType.GIVEAWAY,
        "giveaway_77",
    )
    assert "+<b>77</b>" in context.bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_unknown_giveaway_does_not_pay():
    update = _make_update()
    context = _make_context()

    with (
        patch(
            "src.tgbot.handlers.treasury.giveaway.pay_if_not_paid",
            new_callable=AsyncMock,
        ) as pay,
        patch(
            "src.tgbot.handlers.treasury.giveaway.next_message",
            new_callable=AsyncMock,
        ) as next_message,
    ):
        await handle_giveaway(update, context, "giveaway_fake")

    pay.assert_not_awaited()
    context.bot.send_message.assert_not_awaited()
    next_message.assert_awaited_once()
