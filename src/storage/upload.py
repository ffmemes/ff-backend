import asyncio
import io
import logging
from typing import Any

import httpx
import telegram
from pydantic import AnyHttpUrl
from telegram.error import BadRequest, RetryAfter

from src.config import settings
from src.observability.sentry import (
    capture_telegram_storage_upload_failure,
    sentry_log_extra,
)
from src.storage.constants import MemeStatus, MemeType
from src.storage.deduplication import find_duplicate_by_file_id
from src.storage.deduplication.image_hash import dhash, log_phash_shadow_match
from src.storage.parsers.constants import USER_AGENT
from src.storage.service import (
    update_meme,
)
from src.tgbot.bot import bot

logger = logging.getLogger(__name__)


async def download_meme_content_file(
    url: AnyHttpUrl,
    timeout: float = 20.0,
) -> bytes | None:
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError):
            return None

        if response.status_code in (400, 403, 404, 500):
            return None

        response.raise_for_status()

        if not response.content:
            logging.warning("Empty content from URL: %s", url)
            return None

        return response.content


async def download_meme_content_from_tg(
    file_id: str,
) -> bytes:
    file = await bot.get_file(file_id)
    file_bytearray = await file.download_as_bytearray()
    return bytes(file_bytearray)


async def _image_hash(meme_id: int, meme_type: MemeType, content: bytes, media: Any) -> int | None:
    """dHash of the uploaded image, or of Telegram's thumbnail for video/animation.

    Never raises: a hash failure must not break the upload.
    """
    try:
        if meme_type == MemeType.IMAGE:
            return dhash(content)
        thumbnail = getattr(media, "thumbnail", None)
        if thumbnail:
            return dhash(await download_meme_content_from_tg(thumbnail.file_id))
    except Exception:
        logger.warning("image_hash failed for meme %s", meme_id, exc_info=True)
    return None


async def _upload_meme_content_to_tg(
    meme_id: int,
    meme_type: MemeType,
    content: bytes,  # ??
) -> dict[str, Any] | None:
    file_id = None
    media = None

    if meme_type == MemeType.IMAGE:
        try:
            msg = await bot.send_photo(
                chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID, photo=content
            )
        except telegram.error.TimedOut:
            return None
        media = msg.photo[-1]
        file_id = media.file_id

    if meme_type == MemeType.VIDEO:
        try:
            msg = await bot.send_video(
                chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID, video=content
            )
        except telegram.error.TimedOut:
            return None
        media = msg.video
        file_id = media.file_id

    if meme_type == MemeType.ANIMATION:
        try:
            animation_stream = io.BytesIO(content)
            animation_stream.name = "animation.mp4"
            animation_stream.seek(0)
            msg = await bot.send_animation(
                chat_id=settings.MEME_STORAGE_TELEGRAM_CHAT_ID,
                animation=animation_stream,
            )
        except telegram.error.TimedOut:
            return None

        media = msg.animation or msg.video or msg.document
        if not media:
            logging.warning(
                "Telegram did not return animation/video/document for meme %s upload.",
                meme_id,
            )
            return None
        file_id = media.file_id

    if not file_id:
        return None

    image_hash = await _image_hash(meme_id, meme_type, content, media)

    # Check if this file_id already exists before the meme reaches recommendations.
    duplicate_of = await find_duplicate_by_file_id(meme_id, file_id)
    if duplicate_of:
        logging.info(
            "Meme %s is a file_id duplicate of meme %s, marking as duplicate.",
            meme_id,
            duplicate_of,
        )
        meme = await update_meme(
            meme_id=meme_id,
            telegram_file_id=file_id,
            status=MemeStatus.DUPLICATE,
            duplicate_of=duplicate_of,
            image_hash=image_hash,
        )
    else:
        meme = await update_meme(
            meme_id=meme_id,
            telegram_file_id=file_id,
            status=MemeStatus.CREATED,
            image_hash=image_hash,
        )
        if meme and image_hash is not None:
            try:
                await log_phash_shadow_match(meme)
            except Exception:
                logger.warning("phash shadow lookup failed for meme %s", meme_id, exc_info=True)

    return meme


async def upload_meme_content_to_tg(
    meme: dict[str, Any],
    content: bytes,
    *,
    observability_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    # just a wrapper to handle retries

    meme_result = None
    max_attempts = 3
    content_size = len(content)
    for attempt in range(1, max_attempts + 1):
        try:
            meme_result = await _upload_meme_content_to_tg(
                meme_id=meme["id"],
                meme_type=meme["type"],
                content=content,
            )
            if meme_result and meme_result.get("telegram_file_id"):
                return meme_result
        except RetryAfter as e:
            logger.warning(
                "Flood control exceeded while uploading meme to Telegram",
                extra=sentry_log_extra(
                    observability_context,
                    meme_id=meme["id"],
                    meme_type=meme["type"],
                    attempt=attempt,
                    max_attempts=max_attempts,
                    retry_after=e.retry_after,
                    content_size=content_size,
                    error_type=type(e).__name__,
                ),
            )
            await asyncio.sleep(e.retry_after)
        except BadRequest as e:
            logger.warning(
                "Telegram rejected meme upload: %s",
                e,
                extra=sentry_log_extra(
                    observability_context,
                    meme_id=meme["id"],
                    meme_type=meme["type"],
                    attempt=attempt,
                    max_attempts=max_attempts,
                    content_size=content_size,
                    error_type=type(e).__name__,
                ),
            )
            capture_telegram_storage_upload_failure(
                meme,
                reason="bad_request",
                attempt=attempt,
                max_attempts=max_attempts,
                content_size=content_size,
                error=e,
                observability_context=observability_context,
            )
            await update_meme(meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
            return None

        await asyncio.sleep(3)  # flood control

    logger.warning(
        "Meme failed to upload to Telegram after retries",
        extra=sentry_log_extra(
            observability_context,
            meme_id=meme["id"],
            meme_type=meme["type"],
            max_attempts=max_attempts,
            content_size=content_size,
        ),
    )
    capture_telegram_storage_upload_failure(
        meme,
        reason="retry_exhausted",
        max_attempts=max_attempts,
        content_size=content_size,
        observability_context=observability_context,
    )
    await update_meme(meme["id"], status=MemeStatus.BROKEN_CONTENT_LINK)
    return None
