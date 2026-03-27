# https://docs.python-telegram-bot.org/en/stable/examples.chatmemberbot.html

import asyncio
import logging
from typing import Optional, Tuple

from telegram import Bot, Chat, ChatMember, ChatMemberUpdated, Update
from telegram.ext import ContextTypes

from src.config import settings


def extract_status_change(
    chat_member_update: ChatMemberUpdated,
) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member'
    was a member of the chat and whether the 'new_chat_member' is a member of the chat.
    Returns None, if the status didn't change.
    """
    status_change = chat_member_update.difference().get("status")
    old_is_member, new_is_member = chat_member_update.difference().get("is_member", (None, None))

    if status_change is None:
        return None

    old_status, new_status = status_change
    was_member = old_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (old_status == ChatMember.RESTRICTED and old_is_member is True)
    is_member = new_status in [
        ChatMember.MEMBER,
        ChatMember.OWNER,
        ChatMember.ADMINISTRATOR,
    ] or (new_status == ChatMember.RESTRICTED and new_is_member is True)

    return was_member, is_member


async def handle_chat_member_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Tracks the chats the bot is in."""
    result = extract_status_change(update.my_chat_member)
    if result is None:
        return
    was_member, is_member = result

    # Let's check who is responsible for the change
    cause_name = update.effective_user.full_name

    # Handle chat types differently:
    chat = update.effective_chat
    if chat.type == Chat.PRIVATE:
        if not was_member and is_member:
            # This may not be really needed in practice because most clients
            # will automatically send a /start command after the user unblocks the bot,
            # and start_private_chat() will add the user to "user_ids".
            # We're including this here for the sake of the example.
            logging.info("%s unblocked the bot", cause_name)
        elif was_member and not is_member:
            logging.info("%s blocked the bot", cause_name)
            # doesn't work properly
            # await block.handle_user_blocked_bot(update, context)

    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logging.info("%s added the bot to the group %s", cause_name, chat.title)
            try:
                from src.tgbot.handlers.chat.service import upsert_telegram_chat_bot_joined
                await upsert_telegram_chat_bot_joined(chat)
            except Exception as e:
                logging.warning("Failed to persist bot join for chat %s: %s", chat.id, e)
            # Onboarding: welcome message + demo meme
            try:
                await _send_group_onboarding(context.bot, chat.id)
            except Exception as e:
                logging.warning("Onboarding failed for chat %s: %s", chat.id, e)
        elif was_member and not is_member:
            logging.info("%s removed the bot from the group %s", cause_name, chat.title)
            try:
                from src.tgbot.handlers.chat.service import update_telegram_chat_bot_left
                await update_telegram_chat_bot_left(chat.id)
            except Exception as e:
                logging.warning("Failed to persist bot leave for chat %s: %s", chat.id, e)

    elif not was_member and is_member:
        logging.info("%s added the bot to the channel %s", cause_name, chat.title)

    elif was_member and not is_member:
        logging.info("%s removed the bot from the channel %s", cause_name, chat.title)


async def _send_group_onboarding(bot: Bot, chat_id: int) -> None:
    """Send welcome message + demo meme when bot is added to a group."""
    if not settings.CHAT_AGENT_ENABLED:
        return

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "Привет! Я мем-сомелье 🎩\n\n"
            "Упомяните меня или ответьте на мое сообщение, и я найду идеальный мем.\n\n"  # noqa: E501
            "Чтобы я мог читать сообщения и лучше шутить, "
            "дайте мне права администратора 🙏"
        ),
    )

    await asyncio.sleep(2)

    # Send a demo meme with like/dislike buttons
    try:
        from sqlalchemy import text

        from src.database import fetch_one
        from src.tgbot.handlers.chat.group_meme_reaction import build_meme_reaction_keyboard

        row = await fetch_one(text("""
            SELECT m.id, m.type, m.telegram_file_id
            FROM meme m
            INNER JOIN meme_stats ms ON ms.meme_id = m.id
            WHERE m.status = 'ok'
              AND m.telegram_file_id IS NOT NULL
              AND ms.nlikes > 20
            ORDER BY random()
            LIMIT 1
        """))

        if row:
            keyboard = build_meme_reaction_keyboard(row["id"])
            file_id = row["telegram_file_id"]
            if row["type"] == "animation":
                await bot.send_animation(chat_id=chat_id, animation=file_id, reply_markup=keyboard)
            elif row["type"] == "video":
                await bot.send_video(chat_id=chat_id, video=file_id, reply_markup=keyboard)
            else:
                await bot.send_photo(chat_id=chat_id, photo=file_id, reply_markup=keyboard)
    except Exception as e:
        logging.warning("Failed to send demo meme in onboarding: %s", e)
