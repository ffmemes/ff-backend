from datetime import datetime

from telegram import Chat, ChatBoostSource, ChatBoostSourcePremium, Update, User
from telegram.ext import (
    ContextTypes,
)

from src.tgbot.constants import (
    TELEGRAM_CHANNEL_EN_CHAT_ID,
    # TELEGRAM_CHAT_EN_CHAT_ID,
    # TELEGRAM_CHAT_RU_CHAT_ID,
    TELEGRAM_CHANNEL_RU_CHAT_ID,
)
from src.tgbot.handlers.treasury.payments import TrxType, pay_if_not_paid_with_alert
from src.tgbot.logs import log


def _chat_name(chat: Chat) -> str:
    if chat.username:
        return "@" + chat.username

    return chat.effective_name


async def handle_chat_boost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.chat_boost.chat
    chat_id = chat.id

    if update.chat_boost.boost.source.source != ChatBoostSource.PREMIUM:
        return await log(
            f"⚡️⚡️⚡️ Someone boosted chat {chat_id}/{_chat_name(chat)}",
            context.bot,
        )

    boost_source: ChatBoostSourcePremium = update.chat_boost.boost.source
    user: User = boost_source.user

    await log(
        f"⚡️⚡️⚡️ {user.name} boosted chat {chat_id}/{_chat_name(chat)}",
        context.bot,
    )

    if chat_id in (TELEGRAM_CHANNEL_RU_CHAT_ID, TELEGRAM_CHANNEL_EN_CHAT_ID):
        await pay_if_not_paid_with_alert(
            bot=context.bot,
            user_id=user.id,
            type=TrxType.BOOSTER_CHANNEL,
            external_id=datetime.today().strftime("%Y-%m-%d"),
        )

    # IDEA: boost staking: give coins for each boost given to our chat / channel.
