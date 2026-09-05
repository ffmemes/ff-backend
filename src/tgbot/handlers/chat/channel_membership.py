"""Owned-channel membership events do not register users or alter activity."""

from telegram import ChatMember, Update
from telegram.ext import ContextTypes

from src.config import settings
from src.tgbot.channel_membership import OWNED_CHANNELS, record_channel_membership_event
from src.tgbot.repo.channel_membership import invalidate_channel


async def handle_channel_membership_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not settings.CHANNEL_MEMBERSHIP_SYNC_ENABLED:
        return
    event = update.chat_member
    if event is None or event.chat.id not in OWNED_CHANNELS.values():
        return
    await record_channel_membership_event(
        user_id=event.new_chat_member.user.id,
        chat_id=event.chat.id,
        old_member=event.old_chat_member,
        new_member=event.new_chat_member,
        event_at=event.date,
        update_id=update.update_id,
    )


async def handle_membership_bot_status_update(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if not settings.CHANNEL_MEMBERSHIP_SYNC_ENABLED:
        return
    event = update.my_chat_member
    if event is None or event.chat.id not in OWNED_CHANNELS.values():
        return
    if event.new_chat_member.status not in {ChatMember.OWNER, ChatMember.ADMINISTRATOR}:
        await invalidate_channel(event.chat.id)
