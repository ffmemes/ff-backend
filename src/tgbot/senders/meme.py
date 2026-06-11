import asyncio
import logging
from typing import Tuple

from telegram import (
    Bot,
    InlineKeyboardMarkup,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

from src.recommendations.service import create_user_meme_reaction
from src.storage.constants import MemeType
from src.storage.schemas import MemeData
from src.tgbot.bot import bot
from src.tgbot.senders.keyboards import (
    meme_reaction_keyboard,
)
from src.tgbot.senders.meme_caption import get_meme_caption_for_user_id
from src.tgbot.senders.meme_like_count_experiment import get_visible_meme_like_count
from src.tgbot.senders.popups import (
    get_first_meme_nudge_variant_to_send,
    maybe_send_first_meme_nudge,
)
from src.tgbot.senders.utils import collect_user_languages
from src.tgbot.service import mark_user_blocked
from src.tgbot.sharing import (
    get_meme_share_button_text,
    get_or_assign_meme_share_button_variant,
)
from src.tgbot.telegram_retry import telegram_call_with_retry
from src.tgbot.user_info import get_user_info

logger = logging.getLogger(__name__)


async def send_meme_to_user(
    bot: Bot,
    user_id: int,
    meme: MemeData,
    reaction_context: str | None = None,
    first_meme_nudge_tasks: list[asyncio.Task[None]] | None = None,
):
    user_info = await get_user_info(user_id)
    languages = await collect_user_languages(user_id, user_info["interface_lang"])
    is_first_meme = (user_info["nmemes_sent"] or 0) == 0
    referral_button_text = get_meme_share_button_text(user_info["interface_lang"])
    share_button_variant = await get_or_assign_meme_share_button_variant(user_id)
    logger.debug(
        "Sending meme %s to user %s with share button '%s' variant=%s (languages=%s)",
        meme.id,
        user_id,
        referral_button_text,
        share_button_variant,
        sorted(languages),
    )
    reply_markup = meme_reaction_keyboard(
        meme.id,
        user_id,
        referral_button_text,
        visible_like_count=await get_visible_meme_like_count(user_id, meme.nlikes),
        share_button_variant=share_button_variant,
        interface_lang=user_info["interface_lang"],
        reaction_context=reaction_context,
        meme_type=meme.type.value,
    )
    meme.caption = await get_meme_caption_for_user_id(meme, user_id, user_info)

    sent_message = await send_new_message_with_meme(bot, user_id, meme, reply_markup)
    if sent_message is None:
        return

    delivery_task = asyncio.create_task(
        _complete_direct_meme_delivery(
            user_id,
            meme,
            user_info,
            is_first_meme=is_first_meme,
            first_meme_nudge_tasks=first_meme_nudge_tasks,
        )
    )
    try:
        await asyncio.shield(delivery_task)
    except asyncio.CancelledError:
        delivery_task.add_done_callback(
            lambda task: _log_direct_meme_delivery_result(task, user_id, meme.id)
        )
        raise


async def _complete_direct_meme_delivery(
    user_id: int,
    meme: MemeData,
    user_info: dict,
    *,
    is_first_meme: bool,
    first_meme_nudge_tasks: list[asyncio.Task[None]] | None,
) -> None:
    await _record_delivered_meme_reaction(user_id, meme)
    nudge_variant = await get_first_meme_nudge_variant_to_send(
        user_id,
        is_first_meme=is_first_meme,
    )
    if nudge_variant == "treatment":
        nudge_task = asyncio.create_task(maybe_send_first_meme_nudge(user_id, user_info))
        if first_meme_nudge_tasks is None:
            await nudge_task
        else:
            first_meme_nudge_tasks.append(nudge_task)


def _log_direct_meme_delivery_result(
    task: asyncio.Task[None],
    user_id: int,
    meme_id: int,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning(
            "Post-delivery work was cancelled for user %s meme %s",
            user_id,
            meme_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to complete post-delivery work for user %s meme %s after cancellation",
            user_id,
            meme_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


async def _record_delivered_meme_reaction(user_id: int, meme: MemeData) -> None:
    # Once Telegram accepts a direct send, cancellation must not skip the row
    # that lets reaction callbacks and recommendation dedupe find that delivery.
    reaction_task = asyncio.create_task(
        create_user_meme_reaction(user_id, meme.id, meme.recommended_by or "direct")
    )
    try:
        await asyncio.shield(reaction_task)
    except asyncio.CancelledError:
        reaction_task.add_done_callback(
            lambda task: _log_delivered_meme_reaction_result(task, user_id, meme.id)
        )
        raise


def _log_delivered_meme_reaction_result(
    task: asyncio.Task[None],
    user_id: int,
    meme_id: int,
) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.warning(
            "Delivered meme reaction recording was cancelled for user %s meme %s",
            user_id,
            meme_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to record delivered meme reaction for user %s meme %s after cancellation",
            user_id,
            meme_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )


def get_input_media(
    meme: MemeData,
) -> InputMediaPhoto | InputMediaVideo | InputMediaAnimation:
    if meme.type == MemeType.IMAGE:
        return InputMediaPhoto(
            media=meme.telegram_file_id,
            caption=meme.caption,
        )
    elif meme.type == MemeType.VIDEO:
        return InputMediaVideo(
            media=meme.telegram_file_id,
            caption=meme.caption,
        )
    elif meme.type == MemeType.ANIMATION:
        return InputMediaAnimation(
            media=meme.telegram_file_id,
            caption=meme.caption,
        )
    else:
        raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")


async def send_album_with_memes(
    user_id: int,
    memes: list[MemeData],
) -> Tuple[Message]:
    media = []
    for meme in memes:
        if meme.type == MemeType.IMAGE:
            input_media = InputMediaPhoto(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=meme.caption,
            )
        elif meme.type == MemeType.VIDEO:
            input_media = InputMediaVideo(
                media=meme.telegram_file_id,
                parse_mode=ParseMode.HTML,
                caption=meme.caption,
            )
        elif meme.type == MemeType.ANIMATION:
            raise NotImplementedError("Can't send animation in album")
        else:
            raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")
        media.append(input_media)

    return await bot.send_media_group(
        chat_id=user_id,
        media=media,
    )


async def send_new_message_with_meme(
    bot: Bot,
    user_id: int,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    async def _do_send(parse_mode):
        if meme.type == MemeType.IMAGE:
            return await bot.send_photo(
                chat_id=user_id,
                photo=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        elif meme.type == MemeType.VIDEO:
            return await bot.send_video(
                chat_id=user_id,
                video=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        elif meme.type == MemeType.ANIMATION:
            return await bot.send_animation(
                chat_id=user_id,
                animation=meme.telegram_file_id,
                caption=meme.caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        else:
            raise NotImplementedError(f"Can't send meme. Unknown meme type: {meme.type}")

    try:
        return await _do_send(ParseMode.HTML)
    except BadRequest as error:
        if "can't parse entities" in str(error).lower():
            logger.warning(
                "HTML entity error sending meme %s to user %s: %s. Retrying without parse_mode.",
                meme.id,
                user_id,
                error,
            )
            return await _do_send(None)
        raise
    except Forbidden:
        await mark_user_blocked(user_id, source="forbidden_send_meme")


async def edit_last_message_with_meme(
    message: Message,
    meme: MemeData,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    try:
        try:
            await telegram_call_with_retry(
                lambda: message.edit_media(
                    media=get_input_media(meme),
                    reply_markup=reply_markup,
                ),
                action="edit_media",
            )
        except BadRequest as error:
            if not _is_message_not_modified_error(error):
                raise
            logger.info("Telegram media for meme %s was already current", meme.id)
        return await telegram_call_with_retry(
            lambda: message.edit_caption(
                caption=meme.caption,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            ),
            action="edit_caption",
        )
    except BadRequest as error:
        if "Message to edit not found" in str(error):
            return None
        if _is_message_not_modified_error(error):
            logger.info("Telegram message for meme %s was already current", meme.id)
            return message
        raise


def _is_message_not_modified_error(error: BadRequest) -> bool:
    return "message is not modified" in str(error).lower()
