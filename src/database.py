from typing import Any

from sqlalchemy import (
    CursorResult,
    Boolean,
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
    UniqueConstraint,
    BigInteger,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.constants import DB_NAMING_CONVENTION
from src.storage.constants import (
    MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT,
)

DATABASE_URL = str(settings.DATABASE_URL)
engine = create_async_engine(DATABASE_URL)

metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)


language = Table(
    "language",
    metadata,
    Column("code", String, primary_key=True),
    Column("emoji", String, nullable=False),

    # TODO: flag: show in language selector UI or not
)


meme_source = Table(
    "meme_source",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("type", String, nullable=False),
    Column("url", String, nullable=False),

    Column("status", String, nullable=False),  # in_moderation, parsing_enabled, parsing_disabled

    Column("language_code", ForeignKey("language.code", ondelete="SET NULL")),  # nullable=False ?

    Column("parsed_at", DateTime),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)


meme_raw_telegram = Table(
    "meme_raw_telegram",
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

    UniqueConstraint("meme_source_id", "post_id", name=MEME_SOURCE_POST_UNIQUE_CONSTRAINT),
)


# meme_raw_upload = Table(
#     "meme_raw_upload",
#     metadata,
# TODO: columns TBD, probably also JSONBs to store all raw data
# )


meme = Table(
    "meme",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("meme_source_id", ForeignKey("meme_source.id", ondelete="CASCADE"), nullable=False),
    Column("raw_meme_id", Integer, nullable=False, index=True),
    Column("status", String, nullable=False),

    Column("type", String, nullable=False),
    Column("telegram_file_id", String),
    Column("caption", String),
    Column("language_code", ForeignKey("language.code", ondelete="SET NULL")),

    Column("ocr_result", JSONB),
    Column("duplicate_of", ForeignKey("meme.id", ondelete="SET NULL")),

    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),

    UniqueConstraint("meme_source_id", "raw_meme_id", name=MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT),
)


user_tg = Table(
    "user_tg",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("username", String),
    Column("first_name", String, nullable=False),
    Column("last_name", String),
    Column("is_premium", Boolean),
    Column("language_code", String),  # IETF language tag from telegram
    Column("deep_link", String),

    # Column("first_chat_id", BigInteger, nullable=False),  # chat_id where user first appeared

    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)


user = Table(
    "user",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("type", String, nullable=False),  # super_user, moderator, 

    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("last_active_at", DateTime, onupdate=func.now()),
    Column("blocked_bot_at", DateTime),
)


user_language = Table(
    "user_language",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("language_code", ForeignKey("language.code", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)


user_meme_reaction = Table(
    "user_meme_reaction",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("meme_id", ForeignKey("meme.id", ondelete="CASCADE"), primary_key=True),
    Column("recommended_by", String, nullable=False),
    Column("sent_at", DateTime, server_default=func.now(), nullable=False),
    Column("reaction_id", Integer),
    Column("reacted_at", DateTime),
)


# event = Table(
#     "event",
#     metadata,
#     Column("id", Integer, Identity(), primary_key=True),
#     Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
#     Column("type", String, nullable=False),  # meme_sent, achievement, broadcast, poll
#     Column("object_id", JSONB),
#     Column("created_at", DateTime, server_default=func.now(), nullable=False),
# )


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
