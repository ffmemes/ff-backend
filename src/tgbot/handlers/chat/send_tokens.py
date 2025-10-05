import asyncio
import random
from datetime import datetime
from html import escape

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from src.tgbot.constants import UserType
from src.tgbot.handlers.chat.service import get_active_chat_users
from src.tgbot.handlers.chat.utils import _reply_and_delete
from src.tgbot.handlers.treasury.constants import PAYOUTS, TrxType
from src.tgbot.handlers.treasury.payments import pay_if_not_paid
from src.tgbot.handlers.treasury.service import get_user_balance, transfer_tokens
from src.tgbot.service import get_user_by_id
from src.tgbot.user_info import get_user_info


async def send_tokens_to_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Explain a tg channel post to the user
    Handle message from channel in a chat
    """
    if not update.message or not update.message.text or not update.message.reply_to_message:
        return

    if not update.message.text[1:].isdigit():
        return await _reply_and_delete(
            update.message,
            "Нужно указать число после плюсика)",
            delete_original=True,
        )

    to_send = int(update.message.text[1:])

    if to_send <= 0:
        wolves = random.randint(1, 5)
        dotes = random.randint(3, 50)
        return await _reply_and_delete(
            update.message,
            f"Ну ты жадный пёс {'🐺' * wolves}{'.' * dotes}",
            delete_original=True,
        )

    from_user_tg = update.effective_user
    from_user_id = from_user_tg.id
    balance = await get_user_balance(from_user_id)

    if balance < to_send:
        return await _reply_and_delete(
            update.message,
            "У тебя нет столько бургеров.....",
            delete_original=True,
        )

    to_user_tg = update.message.reply_to_message.from_user
    if to_user_tg.is_bot:
        return await _reply_and_delete(
            update.message,
            "Мне не нужны твои бургеры, я и есть бургер",
            delete_original=True,
        )

    to_user_id = to_user_tg.id
    if from_user_id == to_user_id:
        return  # no need to send tokens to yourself

    to_user = await get_user_by_id(to_user_id)
    if not to_user or to_user["type"] == UserType.BLOCKED_BOT:
        return await _reply_and_delete(
            update.message,
            f"Не вижу {to_user_tg.name} в боте! ай-яй-яй 😿",
            sleep_sec=10,
            delete_original=True,
        )

    # add a treasury transaction: -send, +send
    # send a private messages to both users

    await transfer_tokens(from_user_id, to_user_id, to_send)

    from_user_balance = await get_user_balance(from_user_id)
    to_user_balance = await get_user_balance(to_user_id)

    msend = await context.bot.send_message(
        chat_id=from_user_id,
        text=f"""
Отправил {to_user_tg.name}: -{to_send} 🍔

Твой новый баланс: {from_user_balance} 🍔
        """,
    )

    mreceive = await context.bot.send_message(
        chat_id=to_user_id,
        text=f"""
Вам бургеры от {from_user_tg.name}: +{to_send} 🍔

Новый баланс {to_user_balance} 🍔
        """,
    )

    # update balances

    reaction = random.choice(["👌", "🕊", "👍", "🎉", "🤝", "😘", "🫡"])
    await update.message.set_reaction(reaction=reaction, is_big=True)

    await asyncio.sleep(60)
    try:
        await msend.delete()
        await mreceive.delete()
    except BadRequest:
        pass


def get_html_user_tag(u: dict):
    if u.get("username"):
        return "@" + u["username"]
    elif u.get("first_name"):
        return f"""<a href="tg://user?id={u["user_id"]}">{escape(u["first_name"])}</a>"""
    else:
        raise Exception(f"Can't tag user: {u}")


async def reward_active_chat_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_user_info(update.effective_user.id)
    if user["type"] != UserType.ADMIN:
        return

    # example: +fire 10
    limit_text = update.message.text.split(" ")[1]
    if not limit_text.isdigit():
        return

    limit = int(limit_text)

    return await _reward_active_chat_users(
        context.bot,
        chat_id=update.effective_chat.id,
        limit=limit,
        sender_name=update.effective_user.name,
    )


async def _reward_active_chat_users(
    bot: Bot,
    chat_id: int,
    limit: int,
    sender_name: str,
):
    active_users = await get_active_chat_users(chat_id, limit)

    text = f"{sender_name} запустил ракету\n"

    tags = [get_html_user_tag(u) for u in active_users]
    text += ", ".join(tags)

    reward_per_person = PAYOUTS[TrxType.ACTIVE_IN_CHAT]
    text += f"\nполучили по {reward_per_person}🍔"

    today = datetime.today().strftime("%Y-%m-%d")
    external_id = today + "_" + sender_name
    for user in active_users:
        user_id = user["user_id"]
        await pay_if_not_paid(
            user_id,
            TrxType.ACTIVE_IN_CHAT,
            external_id=external_id,
        )

    await bot.send_message(
        chat_id=chat_id,
        text=f"{text}",
        parse_mode=ParseMode.HTML,
    )
