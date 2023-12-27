from typing import Any

from sqlalchemy import (
    CursorResult,
    Column,
    DateTime,
    Insert,
    Integer,
    MetaData,
    Select,
    String,
    Table,
    Update,
    Identity,
    ForeignKey,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.constants import DB_NAMING_CONVENTION

DATABASE_URL = str(settings.DATABASE_URL)
engine = create_async_engine(DATABASE_URL)

metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)


language = Table(
    "language",
    metadata,
    Column("code", String, primary_key=True),
    Column("emoji", String, nullable=False),
)


meme_source = Table(
    "meme_source",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("type", String, nullable=False),
    Column("url", String, nullable=False),

    Column("status", String, nullable=False),  # in_moderation, parsing_enabled, parsing_disabled

    Column("language_code", ForeignKey("language.code", ondelete="SET_NULL")),  # nullable=False ?

    Column("parsed_at", DateTime),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)


parsed_memes_telegram = Table(
    "parsed_memes_telegram",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("meme_source_id", ForeignKey("meme_source.id", ondelete="CASCADE"), nullable=False),
    Column("post_id", Integer, nullable=False),

    Column("url", String, nullable=False),
    Column("content", String, nullable=False),
    Column("date", DateTime, nullable=False),

    Column("out_links", JSONB),
    Column("mentions", JSONB),
    Column("hashtags", JSONB),
    Column("forwarded", JSONB),
    Column("media", JSONB),
    Column("views", Integer, nullable=False),
    Column("forwarded_url", String),
    Column("link_preview", JSONB),

    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
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
