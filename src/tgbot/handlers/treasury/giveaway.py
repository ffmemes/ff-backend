"""
Giveaway handler for channel promotions.

Deep link format: ?start=giveaway_{campaign_id}
Example: https://t.me/ffmemesbot?start=giveaway_77

Only whitelisted campaign IDs are accepted. Users craft arbitrary
giveaway_* links otherwise and mint unlimited burgers.

Each giveaway campaign is identified by its deep link string and transaction type.
A user can only claim each giveaway once (enforced by pay_if_not_paid).
"""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid
from src.tgbot.senders.next_message import next_message

# Whitelist of active giveaway campaign IDs mapped to their readout transaction type.
# Add new campaigns here before posting the deep link to the channel.
ACTIVE_GIVEAWAY_CAMPAIGNS: dict[str, TrxType] = {
    "giveaway_77": TrxType.GIVEAWAY,  # launch giveaway: 77 burgers to first clickers
    "giveaway_channel_audience_2026_05_25": TrxType.CHANNEL_AUDIENCE_GIVEAWAY,
}


async def handle_giveaway(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    deep_link: str,
) -> None:
    user_id = update.effective_user.id

    trx_type = ACTIVE_GIVEAWAY_CAMPAIGNS.get(deep_link)
    if trx_type is None:
        # Unknown campaign — silently continue to meme feed
        await next_message(
            context.bot,
            user_id,
            prev_update=update,
            prev_reaction_id=None,
        )
        return

    amount = PAYOUTS[trx_type]

    # deep_link is the external_id — ensures one claim per campaign per user
    balance = await pay_if_not_paid(user_id, trx_type, deep_link)

    if balance is not None:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🍔 +<b>{amount}</b> бургеров! Подарок от @ffmemes канала.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text="🍔 Ты уже забрал бургеры из этой раздачи!",
            parse_mode=ParseMode.HTML,
        )

    await next_message(
        context.bot,
        user_id,
        prev_update=update,
        prev_reaction_id=None,
    )
