from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from telegram import Message

from src.database import (
    execute,
    fetch_one,
    meme,
    meme_raw_upload,
    meme_source,
)
from src.storage.constants import MemeSourceType, MemeStatus, MemeType
from src.tgbot.service import get_or_create_meme_source


async def create_meme_raw_upload(msg: Message) -> dict[str, Any]:
    query = (
        insert(meme_raw_upload)
        .values(
            user_id=msg.from_user.id,
            message_id=msg.message_id,
            forward_origin=msg.forward_origin.to_dict() if msg.forward_origin else None,
            media=msg.photo[-1].to_dict(),
            date=msg.date.replace(tzinfo=None),
        )
        .returning(meme_raw_upload)
    )
    return await fetch_one(query)


async def update_meme_raw_upload(update_id: int, **kwargs) -> dict[str, Any]:
    query = (
        meme_raw_upload.update()
        .where(meme_raw_upload.c.id == update_id)
        .values(**kwargs)
        .returning(meme_raw_upload)
    )
    return await fetch_one(query)


async def get_meme_raw_upload_by_id(upload_id: int) -> dict[str, Any]:
    query = meme_raw_upload.select().where(meme_raw_upload.c.id == upload_id)
    return await fetch_one(query)


async def get_or_create_meme_source_for_meme_upload(
    meme_upload: dict[str, Any],
) -> dict[str, Any]:
    return await get_or_create_meme_source(
        url="tg://user?id={}".format(meme_upload["user_id"]),
        type=MemeSourceType.USER_UPLOAD,
        status=MemeStatus.CREATED,
        added_by=meme_upload["user_id"],
    )


async def create_meme_from_meme_raw_upload(
    meme_upload: dict[str, Any],
) -> dict[str, Any]:
    published_at = (
        datetime.fromtimestamp(meme_upload["forward_origin"]["date"]).replace(
            tzinfo=None
        )
        if meme_upload["forward_origin"]
        else meme_upload["date"]
    )

    meme_source_for_meme_upload = await get_or_create_meme_source_for_meme_upload(
        meme_upload
    )

    query = (
        insert(meme)
        .values(
            meme_source_id=meme_source_for_meme_upload["id"],
            raw_meme_id=meme_upload["id"],
            status=MemeStatus.CREATED,
            type=MemeType.IMAGE,
            telegram_file_id=meme_upload["media"]["file_id"],
            caption=None,
            language_code=meme_upload["language_code"],
            published_at=published_at,
        )
        .returning(meme)
    )
    return await fetch_one(query)


async def update_meme_by_upload_id(upload_id: int, **kwargs) -> dict[str, Any]:
    query = (
        meme.update()
        .where(meme.c.raw_meme_id == upload_id)
        .where(meme.c.meme_source_id == meme_source.c.id)
        .where(meme_source.c.type == MemeSourceType.USER_UPLOAD)
        .values(**kwargs)
        .returning(meme)
    )
    return await fetch_one(query)


async def count_24h_uploaded_not_approved_memes(user_id: int) -> int:
    query = f"""
        SELECT count(*)
        FROM meme M
        JOIN meme_source S
            ON S.id = M.meme_source_id
            AND S.type = '{MemeSourceType.USER_UPLOAD}'
            AND S.added_by = {user_id}
            AND M.status = '{MemeStatus.CREATED}'
            AND M.created_at > NOW() - INTERVAL '1 day'
    """
    res = await execute(text(query))
    return res.scalar()
