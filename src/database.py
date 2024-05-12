from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    CursorResult,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Insert,
    Integer,
    MetaData,
    Select,
    String,
    Table,
    UniqueConstraint,
    Update,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine

from src.config import settings
from src.constants import DB_NAMING_CONVENTION
from src.storage.constants import (
    MEME_MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT,
    MEME_RAW_IG_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
)

DATABASE_URL = str(settings.DATABASE_URL)
engine = create_async_engine(DATABASE_URL)

metadata = MetaData(naming_convention=DB_NAMING_CONVENTION)


meme_source = Table(
    "meme_source",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("type", String, nullable=False),
    Column("url", String, nullable=False, unique=True),
    Column("status", String, nullable=False),
    Column("language_code", String, index=True),
    Column("added_by", ForeignKey("user.id", ondelete="SET NULL")),
    Column("data", JSONB),
    Column("parsed_at", DateTime),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)


meme_raw_telegram = Table(
    "meme_raw_telegram",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("post_id", Integer, nullable=False),
    Column("url", String, nullable=False),
    Column("date", DateTime, nullable=False),
    Column("content", String),
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
    UniqueConstraint(
        "meme_source_id",
        "post_id",
        name=MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    ),
)


meme_raw_vk = Table(
    "meme_raw_vk",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("post_id", String, nullable=False),
    Column("url", String, nullable=False),
    Column("date", DateTime, nullable=False),
    Column("content", String),
    Column("media", JSONB),
    Column("views", Integer, nullable=False),
    Column("likes", Integer, nullable=False),
    Column("reposts", Integer, nullable=False),
    Column("comments", Integer, nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
    UniqueConstraint(
        "meme_source_id", "post_id", name=MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT
    ),
)

meme_raw_ig = Table(
    "meme_raw_ig",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("post_id", String, nullable=False),
    Column("url", String, nullable=False),
    Column("published_at", DateTime, nullable=False),
    Column("caption", String),  # caption
    Column("media", JSONB),
    Column("likes", Integer),
    Column("views", Integer),
    Column("comments", Integer),
    Column("shares", Integer),
    Column("media_type", Integer),
    Column("video_duration", Float),
    Column("product_type", String),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
    UniqueConstraint(
        "meme_source_id", "post_id", name=MEME_RAW_IG_MEME_SOURCE_POST_UNIQUE_CONSTRAINT
    ),
)


meme_raw_upload = Table(
    "meme_raw_upload",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("message_id", Integer, nullable=False),
    Column("date", DateTime, nullable=False),
    Column("forward_origin", JSONB),
    Column("media", JSONB, nullable=False),
    Column("language_code", String),  # user selects a languages for the meme
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)


meme = Table(
    "meme",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("raw_meme_id", Integer, nullable=False, index=True),
    Column("status", String, nullable=False),
    Column("type", String, nullable=False, index=True),
    Column("telegram_file_id", String),
    Column("caption", String),
    Column("language_code", String, index=True),
    Column("ocr_result", JSONB),
    Column("duplicate_of", ForeignKey("meme.id", ondelete="SET NULL")),
    Column("published_at", DateTime, nullable=False),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
    UniqueConstraint(
        "meme_source_id",
        "raw_meme_id",
        name=MEME_MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT,
    ),
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
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
)

user_tg_chat_membership = Table(
    "user_tg_chat_membership",
    metadata,
    Column(
        "user_tg_id", ForeignKey("user_tg.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("chat_id", BigInteger, primary_key=True),
    Column(
        "last_seen_at",
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    ),
)


user = Table(
    "user",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("type", String, nullable=False),  # super_user, moderator,
    Column("inviter_id", ForeignKey("user.id", ondelete="SET NULL")),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("last_active_at", DateTime, onupdate=func.now()),
    Column("blocked_bot_at", DateTime),
)


user_language = Table(
    "user_language",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("language_code", String, primary_key=True),
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


user_stats = Table(
    "user_stats",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("nlikes", Integer, nullable=False, server_default="0"),
    Column("ndislikes", Integer, nullable=False, server_default="0"),
    Column("nmemes_sent", Integer, nullable=False, server_default="0"),
    Column("nsessions", Integer, nullable=False, server_default="0"),
    Column("active_days_count", Integer, nullable=False, server_default="0"),
    Column("time_spent_sec", Integer, nullable=False, server_default="0"),
    Column("first_reaction_at", DateTime),
    Column("last_reaction_at", DateTime),
    Column("invited_users", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at",
        DateTime,
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    ),
)


user_meme_source_stats = Table(
    "user_meme_source_stats",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("nlikes", Integer, nullable=False, server_default="0"),
    Column("ndislikes", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at",
        DateTime,
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    ),
)


meme_stats = Table(
    "meme_stats",
    metadata,
    Column("meme_id", ForeignKey("meme.id", ondelete="CASCADE"), primary_key=True),
    Column("nlikes", Integer, nullable=False, server_default="0"),
    Column("ndislikes", Integer, nullable=False, server_default="0"),
    Column("nmemes_sent", Integer, nullable=False, server_default="0"),
    Column("age_days", Integer, nullable=False, server_default="99999"),
    Column("raw_impr_rank", Integer, nullable=False, server_default="99999"),
    Column("sec_to_react", Float, nullable=False, server_default="0"),  # median
    Column("invited_count", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at",
        DateTime,
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    ),
)


meme_source_stats = Table(
    "meme_source_stats",
    metadata,
    Column(
        "meme_source_id",
        ForeignKey("meme_source.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("nlikes", Integer, nullable=False, server_default="0"),
    Column("ndislikes", Integer, nullable=False, server_default="0"),
    Column("nmemes_sent_events", Integer, nullable=False, server_default="0"),
    Column("nmemes_parsed", Integer, nullable=False, server_default="0"),
    Column("nmemes_sent", Integer, nullable=False, server_default="0"),
    Column("latest_meme_age", Integer, nullable=False, server_default="0"),
    Column(
        "updated_at",
        DateTime,
        server_default=func.now(),
        nullable=False,
        onupdate=func.now(),
    ),
)

crossposting = Table(
    "crossposting",
    metadata,
    Column("channel", String, primary_key=True),
    Column("meme_id", ForeignKey("meme.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    # store stats from each source in json
    # updated_at to track stats update
)

user_popup_logs = Table(
    "user_popup_logs",
    metadata,
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
    Column("popup_id", String, primary_key=True),
    Column("sent_at", DateTime, server_default=func.now(), nullable=False),
    Column("reacted_at", DateTime),
)

inline_search_logs = Table(
    "inline_search_logs",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("query", String, nullable=False),
    Column("chat_type", String),
    Column("searched_at", DateTime, server_default=func.now(), nullable=False),
)

inline_search_chosen_result_logs = Table(
    "inline_search_chosen_result_logs",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("result_id", String, nullable=False),
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("query", String, nullable=False),
    Column("chosen_at", DateTime, server_default=func.now(), nullable=False),
)


async def fetch_one(select_query: Select | Insert | Update) -> dict[str, Any] | None:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return cursor.first()._asdict() if cursor.rowcount > 0 else None


async def fetch_all(select_query: Select | Insert | Update) -> list[dict[str, Any]]:
    async with engine.begin() as conn:
        cursor: CursorResult = await conn.execute(select_query)
        return [r._asdict() for r in cursor.all()]


async def execute(select_query: Insert | Update) -> CursorResult:
    async with engine.begin() as conn:
        return await conn.execute(select_query)
