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
)


async def insert_parsed_posts_from_telegram(telegram_posts: list[TgChannelPostParsingResult]) -> None:
    posts = [post.model_dump() for post in telegram_posts]
    insert_statement = insert(meme_raw_telegram).values(posts)
    insert_posts_query = insert_statement.on_conflict_do_update(
        constraint=MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
        set_={
            "views": insert_statement.excluded.views,
            "content": insert_statement.excluded.content,
            "media": insert_statement.excluded.media,
            "updated_at": datetime.utcnow(),
        },
    )

    await execute(insert_posts_query)


async def get_telegram_sources_to_parse(limit=10) -> list[dict[str, Any]]:
    select_query = (
        select(meme_source)
        .where(meme_source.c.type == MemeSourceType.TELEGRAM)
        .order_by(nulls_first(meme_source.c.parsed_at))
        .limit(limit)
    )
    return await fetch_all(select_query)
