from typing import Any

from sqlalchemy import (
    CursorResult,
    JSON,
    Column,
    DateTime,
    Insert,
    Integer,
    MetaData,
    Select,
    String,
    Table,
    Update
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.constants import DB_NAMING_CONVENTION

DATABASE_URL = str(settings.DATABASE_URL)
engine = create_async_engine(DATABASE_URL)

metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)

parsed_memes_telegram = Table(
    "parsed_memes_telegram",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("post_id", Integer, nullable=False),
    Column("url", String, nullable=False),
    Column("content", String, nullable=False),
    Column("out_links", ARRAY(String)),
    Column("mentions", ARRAY(String)),
    Column("hashtags", ARRAY(String)),
    Column("forwarded", JSON),
    Column("media", ARRAY(JSON)),
    Column("views", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("forwarded_url", String),
    Column("link_preview", JSON)
)


async def fetch_one(select_query: Select | Insert | Update) -> dict[str, Any] | None:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return cursor.first()._asdict() if cursor.rowcount > 0 else None


async def fetch_all(select_query: Select | Insert | Update) -> list[dict[str, Any]]:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return [r._asdict() for r in cursor.all()]


async def execute(select_query: Insert | Update) -> None:
    async with engine.begin() as conn:
        await conn.execute(select_query)
