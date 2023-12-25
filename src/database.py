import os

from typing import Any

from sqlalchemy import (
    CursorResult,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Identity,
    Insert,
    Integer,
    LargeBinary,
    MetaData,
    Select,
    String,
    Table,
    Update,
    func,
    BIGINT,
    text,
    create_engine
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.ext.asyncio import create_async_engine

# from src.config import settings
from src.constants import DB_NAMING_CONVENTION

# src.config raise errors
# DATABASE_URL = str(settings.DATABASE_URL)
# engine = create_async_engine(DATABASE_URL)
DATABASE_URL = os.getenv('DATABASE_URL')
DATABASE_URL_SIMPLE = os.getenv('DATABASE_URL_SIMPLE')

engine = create_async_engine(DATABASE_URL)
simple_engine = create_engine(DATABASE_URL_SIMPLE)

metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)

parsed_memes_telegram = Table(
    "parsed_memes_telegram",
    metadata,
    Column("post_id", String, primary_key=True),
    Column("channel_id", String, primary_key=True),
    Column("created_at", DateTime, nullable=True),
    Column("views", BIGINT, nullable=True),
    Column("content", String, nullable=True),
    Column("media", ARRAY(String), nullable=True),
    Column("insert_type", BIGINT, nullable=True)
)


def init_db():
    metadata.create_all(simple_engine)


async def fetch_one(select_query: Select | Insert | Update) -> dict[str, Any] | None:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return cursor.first()._asdict() if cursor.rowcount > 0 else None


async def fetch_all(select_query: Select | Insert | Update ) -> list[dict[str, Any]]:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return [r._asdict() for r in cursor.all()]


def fetch_raw_sql(select_query: text) -> list[dict[str, Any]]:
    with simple_engine.begin() as conn:
        cursor: CursorResult = conn.execute(select_query)
        return [r._asdict() for r in cursor.all()]


async def execute(select_query: Insert | Update) -> None:
    async with engine.begin() as conn:
        await conn.execute(select_query)
