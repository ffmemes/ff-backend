import logging
import random

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes

from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID, TELEGRAM_CHAT_RU_CHAT_ID
from src.tgbot.handlers.chat.ai import AI_PROMPT_RU, _messages_to_text, call_chatgpt
from src.tgbot.handlers.chat.reaction import give_random_reaction
from src.tgbot.handlers.chat.service import (
    get_latest_chat_messages,
    save_telegram_message,
)
from src.tgbot.handlers.chat.utils import _reply_and_delete
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import charge_user
from src.tgbot.handlers.treasury.service import get_user_balance

logger = logging.getLogger(__name__)


def if_bot_was_mentioned(msg: Message) -> bool:
    print(msg.to_json())
    if msg.text and "@ffmemesbot" in msg.text.lower():
        return True

    if msg.reply_to_message and msg.reply_to_message.from_user:
        user_id = msg.reply_to_message.from_user.id
        if user_id in (
            1123681771,
            TELEGRAM_CHANNEL_RU_CHAT_ID,
            TELEGRAM_CHAT_RU_CHAT_ID,
        ):
            return True

    return False


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    await save_telegram_message(msg)

    # Check if message is a reply to bot's message
    # if if_bot_was_mentioned(msg):
    #     if random.random() < 0.3:  # free generation
    #         return await send_ai_message_to_chat(
    #             context.bot,
    #             chat_id=update.effective_chat.id,
    #             reply_to_message_id=msg.id,
    #         )

    #     return await generate_ai_reply_to_a_message(update, context)
    # elif random.random() < 0.1:
    #     return await send_ai_message_to_chat(
    #         context.bot,
    #         chat_id=update.effective_chat.id,
    #         reply_to_message_id=msg.id,
    #     )
    # else:
    #     await give_random_reaction(update, context)

    if random.random() < 0.05:
        await give_random_reaction(update, context)


async def generate_ai_reply_to_a_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    balance = await get_user_balance(user_id)
    if balance < PAYOUTS[TrxType.BOT_REPLY_PAYMENT] * (-1):
        text = "Я отвечаю только за бургеры, а у тебя их нет!"
        return await _reply_and_delete(
            update.message,
            text,
            sleep_sec=10,
            delete_original=False,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Получить 🍔🍔🍔",
                            url="https://t.me/ffmemesbot?start=kitchen",
                        )
                    ]
                ]
            ),
        )

    await charge_user(
        user_id,
        TrxType.BOT_REPLY_PAYMENT,
        external_id=str(update.message.id),
    )

    return await send_ai_message_to_chat(
        context.bot, update.effective_chat.id, reply_to_message_id=update.message.id
    )


async def send_ai_message_to_chat(
    bot: Bot,
    chat_id: int,
    reply_to_message_id: int | None = None,
):
    pass

    await bot.send_chat_action(
        chat_id=chat_id,
        action="typing",
    )

    messages = await get_latest_chat_messages(chat_id=chat_id)
    messages_text = _messages_to_text(messages)

    res = await call_chatgpt(AI_PROMPT_RU.format(messages=messages_text))
    logger.info(f"AI REPLY:\n{res}")

    msg = await bot.send_message(
        chat_id=chat_id,
        text=res,
        parse_mode="HTML",
        reply_to_message_id=reply_to_message_id,
    )

    await save_telegram_message(msg)
