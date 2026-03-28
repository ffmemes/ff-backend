import asyncio
import logging

from telegram import Bot, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest, Forbidden, TimedOut

from src.recommendations import meme_queue
from src.recommendations.service import (
    create_user_meme_reaction,
    user_meme_reaction_exists,
)
from src.storage.constants import MemeStatus
from src.storage.schemas import MemeData
from src.storage.service import update_meme
from src.tgbot.constants import Reaction
from src.tgbot.logs import log
from src.tgbot.senders.alerts import send_queue_preparing_alert
from src.tgbot.senders.keyboards import (
    meme_reaction_keyboard,
    select_referral_button_text,
)
from src.tgbot.senders.meme import (
    edit_last_message_with_meme,
    send_new_message_with_meme,
)
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.senders.popups import get_popup_to_send, send_popup
from src.tgbot.senders.utils import collect_user_languages, has_russian_language
from src.tgbot.user_info import get_user_info

logger = logging.getLogger(__name__)

QUEUE_REFILL_BACKOFF = 0.3  # seconds to wait when queue refill is in progress


async def get_next_meme_for_user(
    user_id: int,
    max_attempts: int = 10,
) -> MemeData | None:
    for _ in range(max_attempts):
        meme = await meme_queue.get_next_meme_for_user(user_id)
        if meme and not await user_meme_reaction_exists(user_id, meme.id):
            return meme
        # Queue empty OR popped an already-reacted meme (duplicate).
        # Either way, try to refill. check_queue returns False if another
        # task is already refilling — in that case, wait briefly for it
        # to finish rather than burning through attempts.
        acquired = await meme_queue.check_queue(user_id)
        if not acquired:
            await asyncio.sleep(QUEUE_REFILL_BACKOFF)

    logger.warning(
        "Failed to find unseen meme for user %s after %s attempts",
        user_id,
        max_attempts,
    )
    return None


async def next_message(
    bot: Bot,
    user_id: int,
    prev_update: Update,
    prev_reaction_id: int | None = None,
) -> Message:
    user_info = await get_user_info(user_id)
    languages = await collect_user_languages(user_id, user_info["interface_lang"])
    has_russian = has_russian_language(languages)
    # TODO: if watched > 30 memes / day show paywall / tasks / donate

    popup = await get_popup_to_send(user_id, user_info)
    if popup:
        return await send_popup(user_id, popup)

    previous_callback = prev_update.callback_query
    previous_message: Message | None = previous_callback.message if previous_callback else None
    should_replace_previous = (
        prev_reaction_id is not None
        and not Reaction(prev_reaction_id).is_positive
        and previous_message is not None
        and previous_message.effective_attachment is not None
    )

    attempt = 0
    max_attempts = 5
    no_memes_left = False

    while attempt < max_attempts:
        meme = await get_next_meme_for_user(user_id)
        if not meme:
            no_memes_left = True
            break

        referral_button_text = select_referral_button_text(has_russian)
        logger.debug(
            "Next meme %s for user %s uses referral button '%s' (languages=%s)",
            meme.id,
            user_id,
            referral_button_text,
            sorted(languages),
        )
        reply_markup = meme_reaction_keyboard(
            meme.id,
            user_id,
            referral_button_text,
        )
        meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

        try:
            if should_replace_previous and previous_message is not None:
                msg = await _replace_previous_message(bot, previous_message, meme, reply_markup)
            else:
                msg = await send_new_message_with_meme(bot, user_id, meme, reply_markup)
        except BadRequest as error:
            await _disable_broken_meme(meme, error)
            attempt += 1
            continue
        except TimedOut:
            logger.warning(
                "Telegram API timed out delivering meme %s to user %s, retrying",
                meme.id,
                user_id,
            )
            attempt += 1
            continue

        await create_user_meme_reaction(user_id, meme.id, meme.recommended_by)
        asyncio.create_task(meme_queue.check_queue(user_id))
        return msg

    asyncio.create_task(meme_queue.check_queue(user_id))

    if no_memes_left:
        return await send_queue_preparing_alert(bot, user_id)

    logger.error(
        "Failed to deliver meme to user %s after %s attempts",
        user_id,
        attempt,
    )
    return await send_queue_preparing_alert(bot, user_id)


async def _replace_previous_message(
    bot: Bot,
    previous_message: Message,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None,
) -> Message:
    try:
        edited_message = await edit_last_message_with_meme(previous_message, meme, reply_markup)
    except BadRequest as error:
        if _is_missing_message_error(error):
            logger.info(
                "Previous message for meme %s is missing (error: %s). "
                "Sending new message instead.",
                meme.id,
                error,
            )
            edited_message = None
        else:
            raise

    if edited_message is not None:
        return edited_message

    try:
        await previous_message.delete()
    except (BadRequest, Forbidden):
        pass

    return await send_new_message_with_meme(
        bot,
        previous_message.chat_id,
        meme,
        reply_markup,
    )


async def _disable_broken_meme(meme: MemeData, error: BadRequest) -> None:
    await update_meme(meme.id, status=MemeStatus.BROKEN_CONTENT_LINK)
    await log(f"meme {meme.id} is disabled now because of: {error.__class__.__name__}: {error}")


def _is_missing_message_error(error: BadRequest) -> bool:
    message = str(error).lower()
    return "message to edit not found" in message or "message_id_invalid" in message
