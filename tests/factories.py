from datetime import datetime

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    meme,
    meme_source,
    meme_source_stats,
    meme_stats,
    user,
    user_language,
    user_meme_reaction,
    user_meme_source_stats,
    user_stats,
)

FIXED_DT = datetime(2024, 6, 1, 12, 0, 0)
TEST_ID_START = 10000


async def create_user(
    conn: AsyncConnection,
    id: int,
    type: str = "user",
) -> dict:
    row = {"id": id, "type": type}
    await conn.execute(insert(user).values(row))
    return row


async def create_user_language(
    conn: AsyncConnection,
    user_id: int,
    language_code: str = "ru",
) -> dict:
    row = {"user_id": user_id, "language_code": language_code}
    await conn.execute(insert(user_language).values(row))
    return row


async def create_meme_source(
    conn: AsyncConnection,
    id: int,
    type: str = "telegram",
    url: str | None = None,
    status: str = "parsing_enabled",
    language_code: str = "ru",
) -> dict:
    if url is None:
        url = f"https://t.me/test_source_{id}"
    row = {
        "id": id,
        "type": type,
        "url": url,
        "status": status,
        "language_code": language_code,
        "created_at": FIXED_DT,
    }
    await conn.execute(insert(meme_source).values(row))
    return row


async def create_meme(
    conn: AsyncConnection,
    id: int,
    meme_source_id: int,
    status: str = "ok",
    type: str = "image",
    language_code: str = "ru",
    telegram_file_id: str = "test_file_id",
    caption: str | None = None,
    raw_meme_id: int | None = None,
    published_at: datetime | None = None,
) -> dict:
    if raw_meme_id is None:
        raw_meme_id = id
    if published_at is None:
        published_at = FIXED_DT
    row = {
        "id": id,
        "meme_source_id": meme_source_id,
        "raw_meme_id": raw_meme_id,
        "status": status,
        "type": type,
        "language_code": language_code,
        "telegram_file_id": telegram_file_id,
        "caption": caption,
        "published_at": published_at,
    }
    await conn.execute(insert(meme).values(row))
    return row


async def create_meme_stats(
    conn: AsyncConnection,
    meme_id: int,
    nlikes: int = 10,
    ndislikes: int = 5,
    nmemes_sent: int = 20,
    lr_smoothed: float = 0.5,
    age_days: int = 30,
    raw_impr_rank: int = 0,
    sec_to_react: float = 7.0,
    invited_count: int = 0,
) -> dict:
    row = {
        "meme_id": meme_id,
        "nlikes": nlikes,
        "ndislikes": ndislikes,
        "nmemes_sent": nmemes_sent,
        "lr_smoothed": lr_smoothed,
        "age_days": age_days,
        "raw_impr_rank": raw_impr_rank,
        "sec_to_react": sec_to_react,
        "invited_count": invited_count,
        "updated_at": FIXED_DT,
    }
    await conn.execute(insert(meme_stats).values(row))
    return row


async def create_meme_source_stats(
    conn: AsyncConnection,
    meme_source_id: int,
    nlikes: int = 10,
    ndislikes: int = 5,
    nmemes_sent_events: int = 20,
    nmemes_parsed: int = 10,
    nmemes_sent: int = 10,
    latest_meme_age: int = 30,
) -> dict:
    row = {
        "meme_source_id": meme_source_id,
        "nlikes": nlikes,
        "ndislikes": ndislikes,
        "nmemes_sent_events": nmemes_sent_events,
        "nmemes_parsed": nmemes_parsed,
        "nmemes_sent": nmemes_sent,
        "latest_meme_age": latest_meme_age,
        "updated_at": FIXED_DT,
    }
    await conn.execute(insert(meme_source_stats).values(row))
    return row


async def create_user_meme_source_stats(
    conn: AsyncConnection,
    user_id: int,
    meme_source_id: int,
    nlikes: int = 5,
    ndislikes: int = 3,
) -> dict:
    row = {
        "user_id": user_id,
        "meme_source_id": meme_source_id,
        "nlikes": nlikes,
        "ndislikes": ndislikes,
        "updated_at": FIXED_DT,
    }
    await conn.execute(insert(user_meme_source_stats).values(row))
    return row


async def create_reaction(
    conn: AsyncConnection,
    user_id: int,
    meme_id: int,
    reaction_id: int | None = None,
    recommended_by: str = "test",
    sent_at: datetime | None = None,
    reacted_at: datetime | None = None,
) -> dict:
    if sent_at is None:
        sent_at = FIXED_DT
    row = {
        "user_id": user_id,
        "meme_id": meme_id,
        "reaction_id": reaction_id,
        "recommended_by": recommended_by,
        "sent_at": sent_at,
        "reacted_at": reacted_at,
    }
    await conn.execute(insert(user_meme_reaction).values(row))
    return row


async def create_user_stats(
    conn: AsyncConnection,
    user_id: int,
    nmemes_sent: int = 0,
    nlikes: int = 0,
    ndislikes: int = 0,
) -> dict:
    row = {
        "user_id": user_id,
        "nmemes_sent": nmemes_sent,
        "nlikes": nlikes,
        "ndislikes": ndislikes,
    }
    await conn.execute(insert(user_stats).values(row))
    return row


async def cleanup_test_data(conn: AsyncConnection) -> None:
    """Delete all test data (id >= 10000) in correct FK order."""
    await conn.execute(delete(meme_stats).where(meme_stats.c.meme_id >= TEST_ID_START))
    await conn.execute(
        delete(meme_source_stats).where(meme_source_stats.c.meme_source_id >= TEST_ID_START)
    )
    await conn.execute(
        delete(user_meme_source_stats).where(user_meme_source_stats.c.user_id >= TEST_ID_START)
    )
    await conn.execute(
        delete(user_meme_reaction).where(user_meme_reaction.c.user_id >= TEST_ID_START)
    )
    await conn.execute(delete(user_language).where(user_language.c.user_id >= TEST_ID_START))
    await conn.execute(delete(user_stats).where(user_stats.c.user_id >= TEST_ID_START))
    await conn.execute(delete(meme).where(meme.c.id >= TEST_ID_START))
    await conn.execute(delete(meme_source).where(meme_source.c.id >= TEST_ID_START))
    await conn.execute(delete(user).where(user.c.id >= TEST_ID_START))
    await conn.commit()
