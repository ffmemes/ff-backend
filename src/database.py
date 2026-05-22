import asyncio
import uuid
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    CursorResult,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Insert,
    Integer,
    MetaData,
    Select,
    SmallInteger,
    String,
    Table,
    UniqueConstraint,
    Update,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import settings
from src.constants import DB_NAMING_CONVENTION, Environment
from src.storage.constants import (
    MEME_MEME_SOURCE_RAW_MEME_UNIQUE_CONSTRAINT,
    MEME_RAW_IG_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_RAW_TELEGRAM_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
    MEME_RAW_VK_MEME_SOURCE_POST_UNIQUE_CONSTRAINT,
)

DATABASE_URL = str(settings.DATABASE_URL)

T = TypeVar("T")

_engine_kwargs: dict = dict(
    connect_args={
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)
if settings.ENVIRONMENT == Environment.TESTING:
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs.update(
        max_overflow=settings.DATABASE_POOL_MAX_OVERFLOW,
        pool_size=settings.DATABASE_POOL_SIZE,
        pool_recycle=settings.DATABASE_POOL_TTL,
        pool_pre_ping=settings.DATABASE_POOL_PRE_PING,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
        pool_use_lifo=True,
    )

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)


@event.listens_for(engine.sync_engine, "handle_error")
def _mark_bad_connection_as_disconnect(context: object) -> None:
    """Tell SQLAlchemy to invalidate pool connections that asyncpg reports as broken.

    pool_pre_ping catches most stale connections, but a race is possible: the server
    closes the connection between the ping and the actual query.  When that happens
    asyncpg raises ConnectionDoesNotExistError (a subclass of InterfaceError).

    Similarly, under high concurrency the pool can hand out a connection whose
    previous async operation hasn't fully completed.  asyncpg raises
    InternalClientError ("cannot switch to state …; another operation is in
    progress") in this case.

    Marking either as a disconnect causes the pool to discard that connection so
    it is never handed out again.
    """
    original = getattr(context, "original_exception", None)
    if original is not None and (
        _has_exception_named(original, "ConnectionDoesNotExistError")
        or _is_concurrent_use_error(original)
    ):
        context.is_disconnect = True  # type: ignore[union-attr]


def _walk_exception_chain(exc: BaseException) -> list[BaseException]:
    """Return SQLAlchemy + asyncpg wrapper exceptions without looping forever."""
    chain: list[BaseException] = []
    stack: list[BaseException] = [exc]
    seen: set[int] = set()

    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)

        for attr in ("orig", "__cause__", "__context__"):
            nested = getattr(current, attr, None)
            if isinstance(nested, BaseException):
                stack.append(nested)

    return chain


def _has_exception_named(exc: BaseException, name: str) -> bool:
    return any(type(current).__name__ == name for current in _walk_exception_chain(exc))


def _is_stale_connection_error(exc: BaseException) -> bool:
    return _has_exception_named(exc, "ConnectionDoesNotExistError")


def _is_concurrent_use_error(exc: BaseException) -> bool:
    """Return True when asyncpg reports concurrent use of a single connection.

    Under high webhook concurrency the pool can hand out a connection whose
    previous async commit/rollback hasn't fully completed.  asyncpg raises
    InternalClientError("cannot switch to state …; another operation … is in
    progress").  Retrying with a fresh connection resolves the issue.
    """
    for current in _walk_exception_chain(exc):
        if type(current).__name__ != "InternalClientError":
            continue
        message = str(current)
        if "another operation" in message and "in progress" in message:
            return True
    return False


def _is_deadlock_error(exc: BaseException) -> bool:
    """Return True when asyncpg reports a PostgreSQL deadlock.

    Deadlocks are transient — PostgreSQL rolls back one victim transaction
    automatically.  Retrying the statement (with a small backoff to let the
    winning transaction finish) is the standard resolution per PG docs.
    """
    return _has_exception_named(exc, "DeadlockDetectedError")


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


# Pool of channels we've seen forwarded into already-tracked sources, awaiting
# moderator promotion into `meme_source`. Never auto-enabled; populated by the
# TG ETL hook in `discover_source_candidates_from_telegram_posts`.
meme_source_candidate = Table(
    "meme_source_candidate",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("type", String, nullable=False),
    Column("url", String, nullable=False, unique=True),
    Column("status", String, nullable=False, server_default="discovered", index=True),
    Column("times_forwarded", Integer, nullable=False, server_default="1"),
    Column("first_seen_at", DateTime, server_default=func.now(), nullable=False),
    Column("last_seen_at", DateTime, server_default=func.now(), nullable=False),
    Column("sample_meme_source_id", Integer),
    Column("sample_meme_raw_telegram_post_id", Integer),
    Column(
        "promoted_meme_source_id",
        ForeignKey("meme_source.id", ondelete="SET NULL"),
    ),
    Column("dismissed_reason", String),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
    Index(
        "ix_meme_source_candidate_status_times",
        "status",
        text("times_forwarded DESC"),
    ),
)

meme_source_candidate_poll = Table(
    "meme_source_candidate_poll",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column(
        "candidate_id",
        ForeignKey("meme_source_candidate.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("chat_id", BigInteger, nullable=False),
    Column("message_id", BigInteger),
    Column(
        "prepared_meme_source_id",
        ForeignKey("meme_source.id", ondelete="SET NULL"),
    ),
    Column("status", String, nullable=False, server_default="draft"),
    Column("opened_at", DateTime),
    Column("closes_at", DateTime, nullable=False),
    Column("closed_at", DateTime),
    Column(
        "result_meme_source_id",
        ForeignKey("meme_source.id", ondelete="SET NULL"),
    ),
    Column("data", JSONB),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("updated_at", DateTime, onupdate=func.now()),
    Index("ix_meme_source_candidate_poll_status_closes_at", "status", "closes_at"),
    Index(
        "uq_meme_source_candidate_poll_message",
        "chat_id",
        "message_id",
        unique=True,
        postgresql_where=text("message_id IS NOT NULL"),
    ),
    Index(
        "uq_meme_source_candidate_poll_active_global",
        text("(true)"),
        unique=True,
        postgresql_where=text("status IN ('draft', 'open')"),
    ),
    Index(
        "uq_meme_source_candidate_poll_active_candidate",
        "candidate_id",
        unique=True,
        postgresql_where=text("status IN ('draft', 'open')"),
    ),
)

meme_source_candidate_vote = Table(
    "meme_source_candidate_vote",
    metadata,
    Column(
        "poll_id",
        ForeignKey("meme_source_candidate_poll.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("user_id", BigInteger, primary_key=True),
    Column("vote", SmallInteger, nullable=False),
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
    Column("views", Integer, nullable=False),  # TODO: make nullable
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
        index=True,
    ),
    Column("raw_meme_id", Integer, nullable=False, index=True),
    Column("status", String, nullable=False, index=True),
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
    Index(
        "idx_meme_ocr_text_gin",
        text("(ocr_result ->> 'text') gin_trgm_ops"),
        postgresql_using="gin",
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
    Column("user_tg_id", ForeignKey("user_tg.id", ondelete="CASCADE"), primary_key=True),
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
    Column("nickname", String),
    Column("type", String, nullable=False),  # super_user, moderator,
    Column("inviter_id", ForeignKey("user.id", ondelete="SET NULL")),
    Column("balance", Integer, nullable=False, server_default="0"),
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
    Column("median_session_length", Integer, nullable=False, server_default="0"),
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
    Column("sec_to_react", Float, nullable=False, server_default="99999"),  # median
    Column("invited_count", Integer, nullable=False, server_default="0"),
    Column("lr_smoothed", Float, nullable=False, server_default="0"),
    Column("engagement_score", Float, nullable=False, server_default="0"),
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
    Column("telegram_message_id", BigInteger),
    Column("caption_text", String),
    Column("score_version", Integer, server_default="1"),
    Column("views", Integer),
    Column("forwards", Integer),
    Column("reactions", Integer),
    Column("comments", Integer),
    Column("reactions_detail", JSONB),  # {"😁": 6, "❤": 4, ...}
    Column("stats_updated_at", DateTime),
)

crossposting_snapshots = Table(
    "crossposting_snapshots",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("channel", String, nullable=False),
    Column("meme_id", ForeignKey("meme.id", ondelete="CASCADE"), nullable=False),
    Column("telegram_message_id", BigInteger, nullable=False),
    Column("views", Integer),
    Column("forwards", Integer),
    Column("reactions", Integer),
    Column("comments", Integer),
    Column("reactions_detail", JSONB),  # {"😁": 6, "❤": 4, ...}
    Column("message_text", String),
    Column("snapshot_at", DateTime, server_default=func.now(), nullable=False),
)

crossposting_decision_log = Table(
    "crossposting_decision_log",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("decided_at", DateTime, server_default=func.now(), nullable=False),
    Column("channel", String, nullable=False),
    Column("picked_meme_id", ForeignKey("meme.id", ondelete="SET NULL")),
    Column("score_version", Integer, nullable=False),
    Column("median_signal", Float),
    Column("candidate_pool_size", Integer),
    # candidates JSONB: list of {meme_id, source_id, rank, nlikes, ndislikes,
    # raw_impr_rank, age_days, nmemes_sent, invited_count,
    # pre_inbot_share_clicks, pre_inbot_share_click_users, caption_present,
    # src_signal, src_quality_mult, lr_factor, impr_factor, age_factor,
    # caption_factor, sent_factor, invited_boost, final_score}
    Column("candidates", JSONB, nullable=False),
    Index(
        "ix_crossposting_decision_log_channel_time",
        "channel",
        "decided_at",
    ),
)


channel_daily_stats = Table(
    "channel_daily_stats",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("channel", String, nullable=False),
    Column("date", Date, nullable=False),
    Column("subscriber_count", Integer),
    Column("posts_count", Integer),
    Column("total_forwards", Integer),
    Column("total_views", Integer),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    UniqueConstraint("channel", "date"),
)

editorial_posts = Table(
    "editorial_posts",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("channel", String, nullable=False),
    Column("telegram_message_id", BigInteger, nullable=True),
    Column("draft_hash", String, nullable=False),
    Column("category", String),
    Column("entity_id", String),
    Column("topic_slug", String),
    Column("text", String, nullable=False),
    Column("has_media", Boolean, nullable=False, server_default="false"),
    Column("validation_version", Integer, nullable=False, server_default="1"),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
    Column("views", Integer),
    Column("forwards", Integer),
    Column("reactions", Integer),
    Column("comments", Integer),
    Column("reactions_detail", JSONB),  # {"😁": 6, "❤": 4, ...}
    Column("stats_updated_at", DateTime),
    UniqueConstraint("draft_hash", name="uq_editorial_posts_draft_hash"),
    UniqueConstraint("channel", "telegram_message_id", name="uq_editorial_posts_channel_msg"),
)

editorial_post_snapshots = Table(
    "editorial_post_snapshots",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("channel", String, nullable=False),
    Column(
        "editorial_post_id",
        ForeignKey("editorial_posts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("telegram_message_id", BigInteger, nullable=False),
    Column("views", Integer),
    Column("forwards", Integer),
    Column("reactions", Integer),
    Column("comments", Integer),
    Column("reactions_detail", JSONB),
    Column("snapshot_at", DateTime, server_default=func.now(), nullable=False),
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

treasury_trx = Table(
    "treasury_trx",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("user_id", ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("type", String, nullable=False, index=True),
    Column("amount", Integer, nullable=False),
    Column("external_id", String),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

user_deep_link_log = Table(
    "user_deep_link_log",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("deep_link", String, index=True),
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

telegram_chat = Table(
    "telegram_chat",
    metadata,
    Column("id", BigInteger, primary_key=True),  # Telegram chat_id
    Column("type", String(20)),  # group, supergroup, channel, private
    Column("title", String(256)),
    Column("username", String(128)),
    Column("members_count", Integer),
    Column("bot_status", String(20)),  # member, left, kicked, None
    Column("bot_joined_at", DateTime),
    Column("bot_left_at", DateTime),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

message_tg = Table(
    "message_tg",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("message_id", BigInteger, nullable=False),
    Column("date", DateTime),
    Column("chat_id", BigInteger, nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("text", String),  # also stores caption when the message is media
    Column("reply_to_message_id", BigInteger),
    Column("sender_chat_id", BigInteger),  # Channel ID when posted as channel (777000 case)
    Column("media_type", String),  # photo|video|animation|document|sticker|voice|video_note
    Column("file_id", String),  # best-quality Telegram file_id for the attached media
    Column("media_group_id", String),  # album grouping id
    Column("forward_from_chat_id", BigInteger),
    Column("forward_from_message_id", BigInteger),
    Column("forward_from_user_id", BigInteger),
    UniqueConstraint("chat_id", "message_id", name="uq_message_tg"),
)

user_wrapped = Table(
    "user_wrapped",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("user_id", BigInteger, ForeignKey("user.id"), nullable=False),
    Column("data", JSONB, nullable=False),
    Column("card_telegram_file_id", String),
    Column("created_at", DateTime, server_default=func.now()),
)

chat_meme_reaction = Table(
    "chat_meme_reaction",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("chat_id", BigInteger, nullable=False),
    Column("meme_id", Integer, ForeignKey("meme.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("reaction", SmallInteger, nullable=False),  # 1 = like, 2 = dislike
    Column("reacted_at", DateTime, server_default=func.now(), nullable=False),
    UniqueConstraint("chat_id", "meme_id", "user_id", name="uq_chat_meme_reaction"),
)

chat_agent_usage = Table(
    "chat_agent_usage",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("chat_id", BigInteger, nullable=False),
    Column("user_id", BigInteger, nullable=False),
    Column("prompt_tokens", Integer, nullable=False, server_default="0"),
    Column("completion_tokens", Integer, nullable=False, server_default="0"),
    Column("tool_calls", Integer, nullable=False, server_default="0"),
    Column("response_time_ms", Integer),
    Column("trigger_type", String),  # mention, reply, activity
    Column("created_at", DateTime, server_default=func.now(), nullable=False),
)

# === Experiment Analytics ===

experiment_assignment = Table(
    "experiment_assignment",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("experiment_id", String(100), nullable=False),
    Column("user_id", BigInteger, ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("variant", String(50), nullable=False),  # 'control', 'treatment', etc.
    Column(
        "assignment_metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("assigned_at", DateTime, server_default=func.now(), nullable=False),
    UniqueConstraint("experiment_id", "user_id", name="uq_experiment_assignment"),
)


def _is_transient_connection_error(exc: BaseException) -> bool:
    return _is_stale_connection_error(exc) or _is_concurrent_use_error(exc)


# Shared retry budget for stale / concurrent-use connection errors.
# Three retries (25 ms + 50 ms + 100 ms backoff) give the event loop enough
# time to dispose dirty connections under burst webhook concurrency.
# Under traffic spikes the LIFO pool can hand out several consecutively
# dirty connections; 2 retries proved insufficient (9 Sentry events on
# 2026-04-12).  Bumping to 3 retries with wider backoff makes exhaustion
# astronomically unlikely while adding only ~175 ms worst-case latency.
_TRANSIENT_MAX_RETRIES = 3


async def fetch_one(
    select_query: Select | Insert | Update,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
        try:
            async with engine.begin() as conn:
                cursor: CursorResult = await conn.execute(select_query, params or {})
                row = cursor.first()
                return row._asdict() if row is not None else None
        except Exception as exc:
            if _is_transient_connection_error(exc) and attempt < _TRANSIENT_MAX_RETRIES:
                await asyncio.sleep(0.025 * (2**attempt))  # 25 ms, 50 ms, 100 ms
                continue
            raise
    raise RuntimeError("fetch_one retry loop exhausted")  # pragma: no cover


async def fetch_all(
    select_query: Select | Insert | Update,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
        try:
            async with engine.begin() as conn:
                cursor: CursorResult = await conn.execute(select_query, params or {})
                return [r._asdict() for r in cursor.all()]
        except Exception as exc:
            if _is_transient_connection_error(exc) and attempt < _TRANSIENT_MAX_RETRIES:
                await asyncio.sleep(0.025 * (2**attempt))  # 25 ms, 50 ms, 100 ms
                continue
            raise
    raise RuntimeError("fetch_all retry loop exhausted")  # pragma: no cover


async def execute(
    select_query: Insert | Update,
    params: dict[str, Any] | None = None,
) -> CursorResult:
    """Execute a write statement, retrying on stale connections and deadlocks.

    Deadlocks are caused by concurrent stats flows (retries + scheduled runs)
    both upserting the same rows in different lock-acquisition orders.
    PostgreSQL rolls back the victim transaction automatically; retrying it
    (after a short backoff) is the standard resolution.

    Retry policy:
        - Stale/concurrent-use connection: up to 3 retries, 25 / 50 / 100 ms backoff
        - Deadlock (DeadlockDetectedError): up to 2 retries, 100 ms / 200 ms backoff
    """
    _DEADLOCK_MAX_RETRIES = 2
    _max_attempts = max(_TRANSIENT_MAX_RETRIES, _DEADLOCK_MAX_RETRIES) + 1
    _transient_attempts = 0

    for attempt in range(_max_attempts):
        try:
            async with engine.begin() as conn:
                return await conn.execute(select_query, params or {})
        except Exception as exc:
            if _is_transient_connection_error(exc) and _transient_attempts < _TRANSIENT_MAX_RETRIES:
                await asyncio.sleep(0.025 * (2**_transient_attempts))  # 25 ms, 50 ms, 100 ms
                _transient_attempts += 1
                continue
            if _is_deadlock_error(exc) and attempt < _DEADLOCK_MAX_RETRIES:
                # Deadlock: short exponential backoff then retry
                await asyncio.sleep(0.1 * (2**attempt))  # 100 ms, 200 ms
                continue
            raise
    # Unreachable — loop always returns or raises
    raise RuntimeError("execute retry loop exhausted without returning")  # pragma: no cover


async def run_in_transaction(fn: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    """Run several DB statements in one transaction with the standard retry policy."""
    _DEADLOCK_MAX_RETRIES = 2
    _max_attempts = max(_TRANSIENT_MAX_RETRIES, _DEADLOCK_MAX_RETRIES) + 1
    _transient_attempts = 0

    for attempt in range(_max_attempts):
        try:
            async with engine.begin() as conn:
                return await fn(conn)
        except Exception as exc:
            if _is_transient_connection_error(exc) and _transient_attempts < _TRANSIENT_MAX_RETRIES:
                await asyncio.sleep(0.025 * (2**_transient_attempts))
                _transient_attempts += 1
                continue
            if _is_deadlock_error(exc) and attempt < _DEADLOCK_MAX_RETRIES:
                await asyncio.sleep(0.1 * (2**attempt))
                continue
            raise
    raise RuntimeError("transaction retry loop exhausted without returning")  # pragma: no cover
