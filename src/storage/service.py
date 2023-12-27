import uuid
from typing import Any
from datetime import datetime
from sqlalchemy import select, func, nulls_first
from sqlalchemy.dialects.postgresql import insert

from src.database import (
    language,
    meme_source,
    meme_raw_telegram,
    execute, fetch_one, fetch_all,
)
from src.storage.parsers.schemas import TgChannelPostParsingResult
from src.storage.constants import (
    MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MemeSourceType,
    MemeSourceStatus,
)


async def insert_parsed_posts_from_telegram(
    meme_source_id: int,
    telegram_posts: list[TgChannelPostParsingResult],
) -> None:
    posts = [
        post.model_dump(exclude_none=True) | {"meme_source_id": meme_source_id}
        for post in telegram_posts
    ]
    insert_statement = insert(meme_raw_telegram).values(posts)
    insert_posts_query = insert_statement.on_conflict_do_update(
        constraint=MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
        set_={
            "views": insert_statement.excluded.views,
            "updated_at": datetime.utcnow(),
        },
    )

    await execute(insert_posts_query)


async def get_telegram_sources_to_parse(limit=10) -> list[dict[str, Any]]:
    select_query = (
        select(meme_source)
        .where(meme_source.c.type == MemeSourceType.TELEGRAM)
        .where(meme_source.c.status == MemeSourceStatus.PARSING_ENABLED)
        .order_by(nulls_first(meme_source.c.parsed_at))
        .limit(limit)
    )
    return await fetch_all(select_query)


async def update_meme_source(meme_source_id: int, **kwargs) -> dict[str, Any] | None:
    update_query = (
        meme_source.update()
        .where(meme_source.c.id == meme_source_id)
        .values(**kwargs)
        .returning(meme_source)
    )
    return await fetch_one(update_query)
