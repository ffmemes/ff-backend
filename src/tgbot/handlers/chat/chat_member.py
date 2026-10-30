# https://docs.python-telegram-bot.org/en/stable/examples.chatmemberbot.html

import logging
from typing import Optional, Tuple

from telegram import Chat, ChatMember, ChatMemberUpdated, Update
from telegram.ext import ContextTypes


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
        from src.tgbot.handlers import block

        if not was_member and is_member:
            logging.info("%s unblocked the bot", cause_name)
            await block.handle_user_unblocked_bot(update, context)
        elif was_member and not is_member:
            logging.info("%s blocked the bot", cause_name)
            await block.handle_user_blocked_bot(update, context)

    elif chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
        if not was_member and is_member:
            logging.info("%s added the bot to the group %s", cause_name, chat.title)
            try:
                from src.tgbot.handlers.chat.service import upsert_telegram_chat_bot_joined

                await upsert_telegram_chat_bot_joined(chat)
            except Exception as e:
                logging.warning("Failed to persist bot join for chat %s: %s", chat.id, e)
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
