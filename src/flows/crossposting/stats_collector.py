"""
Channel post stats collector via Telethon.

Reads views, forwards, reactions from @ffmemes, @fastfoodmemes, and
@fast_food_memes channel posts. Stores time-series snapshots for analysis.

Schedules (serve_flows.py):
- Full sweep every 6h (all recent messages + subscribers)
- Young-posts hourly (<48h) for early canary / score_version reads
- Single-message refresh after each crosspost (post-hook)

Uses the same Telethon session string as e2e_smoke.py (TELEGRAM_API_ID,
TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING env vars).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from prefect import flow, get_run_logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    SessionExpiredError,
)
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest

from src.config import settings
from src.database import (
    channel_daily_stats,
    crossposting_snapshots,
    editorial_post_snapshots,
    execute,
    fetch_all,
)
from src.flows.hooks import notify_telegram_on_failure

logger = logging.getLogger(__name__)

# Channel usernames (without @)
CHANNELS = {
    "ffmemes": "ffmemes",
    "tgchannelru": "fastfoodmemes",
    "tgchannelen": "fast_food_memes",
}

# Crosspost keys that receive post-hook + young-post refresh (not @ffmemes editorial-only).
CROSSPOST_CHANNEL_KEYS = frozenset({"tgchannelru", "tgchannelen"})

# How long after posting we care about dense early samples.
YOUNG_POST_MAX_AGE = timedelta(hours=48)
# Full sweep still refreshes a wider window for mature 24h labels.
FULL_SWEEP_MESSAGE_LIMIT = 200
FULL_SWEEP_MAX_AGE = timedelta(days=30)


def _get_telethon_client() -> TelegramClient | None:
    """Create a Telethon client from env vars. Returns None if not configured."""
    required = [
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
        settings.TELEGRAM_SESSION_STRING,
    ]
    if not all(required):
        return None
    return TelegramClient(
        StringSession(settings.TELEGRAM_SESSION_STRING),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )


def _extract_metrics(msg) -> tuple[int, int, int, dict[str, int], int]:
    """Return (views, forwards, reactions_total, reactions_detail, comments)."""
    views = getattr(msg, "views", None) or 0
    forwards = getattr(msg, "forwards", None) or 0
    reaction_count = 0
    reactions_detail: dict[str, int] = {}
    if msg.reactions and hasattr(msg.reactions, "results"):
        for r in msg.reactions.results:
            reaction_count += r.count
            emoji = getattr(r.reaction, "emoticon", str(r.reaction))
            reactions_detail[emoji] = r.count
    comments = 0
    if msg.replies:
        comments = getattr(msg.replies, "replies", 0) or 0
    return views, forwards, reaction_count, reactions_detail, comments


async def _persist_crosspost_metrics(
    *,
    channel_key: str,
    meme_id: int,
    telegram_message_id: int,
    views: int,
    forwards: int,
    reactions: int,
    comments: int,
    reactions_detail: dict[str, int],
    message_text: str | None = None,
) -> None:
    """Write one snapshot row + update live columns on ``crossposting``."""
    await execute(
        insert(crossposting_snapshots).values(
            channel=channel_key,
            meme_id=meme_id,
            telegram_message_id=telegram_message_id,
            views=views,
            forwards=forwards,
            reactions=reactions,
            comments=comments,
            reactions_detail=reactions_detail or None,
            message_text=(message_text or "")[:500] if message_text is not None else None,
        )
    )
    await execute(
        text(
            "UPDATE crossposting SET views = :views, forwards = :fwd, "
            "reactions = :react, comments = :comments, "
            "reactions_detail = :rdetail, stats_updated_at = NOW() "
            "WHERE channel = :ch AND telegram_message_id = :msg_id"
        ),
        {
            "views": views,
            "fwd": forwards,
            "react": reactions,
            "comments": comments,
            "rdetail": json.dumps(reactions_detail) if reactions_detail else None,
            "ch": channel_key,
            "msg_id": telegram_message_id,
        },
    )


async def _persist_editorial_metrics(
    *,
    channel_key: str,
    editorial_post_id: int,
    telegram_message_id: int,
    views: int,
    forwards: int,
    reactions: int,
    comments: int,
    reactions_detail: dict[str, int],
) -> None:
    await execute(
        insert(editorial_post_snapshots).values(
            channel=channel_key,
            editorial_post_id=editorial_post_id,
            telegram_message_id=telegram_message_id,
            views=views,
            forwards=forwards,
            reactions=reactions,
            comments=comments,
            reactions_detail=reactions_detail or None,
        )
    )
    await execute(
        text(
            "UPDATE editorial_posts SET views = :views, forwards = :fwd, "
            "reactions = :react, comments = :comments, "
            "reactions_detail = :rdetail, stats_updated_at = NOW() "
            "WHERE channel = :ch AND telegram_message_id = :msg_id"
        ),
        {
            "views": views,
            "fwd": forwards,
            "react": reactions,
            "comments": comments,
            "rdetail": json.dumps(reactions_detail) if reactions_detail else None,
            "ch": channel_key,
            "msg_id": telegram_message_id,
        },
    )


async def _with_telethon_client():
    """Async context-style connect. Caller must disconnect.

    Returns client or None if misconfigured / unauthorized.
    """
    log = get_run_logger()
    client = _get_telethon_client()
    if client is None:
        log.warning(
            "Telethon not configured — set TELEGRAM_API_ID, TELEGRAM_API_HASH, "
            "TELEGRAM_SESSION_STRING to enable channel stats collection"
        )
        return None
    await client.connect()
    if not await client.is_user_authorized():
        log.error(
            "Telethon session expired. Regenerate with: python scripts/generate_session_string.py"
        )
        await client.disconnect()
        return None
    return client


async def refresh_crosspost_message_stats(
    channel_key: str,
    telegram_message_id: int,
    meme_id: int,
) -> dict[str, Any] | None:
    """Fetch stats for one channel message and persist snapshot + live columns.

    Safe to call from post-hooks: returns None and logs on soft failures
    (no Telethon, private channel, missing message). Does not raise FloodWait
    to the caller — logs and returns None.
    """
    log = get_run_logger()
    if channel_key not in CHANNELS:
        log.warning("Unknown channel_key=%s for stats refresh", channel_key)
        return None
    if channel_key not in CROSSPOST_CHANNEL_KEYS:
        log.warning("channel_key=%s is not a crosspost channel; skip", channel_key)
        return None

    username = CHANNELS[channel_key]
    client = await _with_telethon_client()
    if client is None:
        return None

    try:
        try:
            entity = await client.get_entity(username)
        except ChannelPrivateError:
            log.error("Cannot access @%s — private or no access", username)
            return None

        messages = await client.get_messages(entity, ids=telegram_message_id)
        msg = messages if not isinstance(messages, list) else (messages[0] if messages else None)
        if msg is None:
            log.warning(
                "No Telegram message id=%s on @%s (meme_id=%s)",
                telegram_message_id,
                username,
                meme_id,
            )
            return None

        views, forwards, reaction_count, reactions_detail, comments = _extract_metrics(msg)
        await _persist_crosspost_metrics(
            channel_key=channel_key,
            meme_id=meme_id,
            telegram_message_id=telegram_message_id,
            views=views,
            forwards=forwards,
            reactions=reaction_count,
            comments=comments,
            reactions_detail=reactions_detail,
            message_text=msg.text or "",
        )
        log.info(
            "Refreshed stats @%s msg=%s meme=%s views=%s forwards=%s",
            username,
            telegram_message_id,
            meme_id,
            views,
            forwards,
        )
        return {
            "channel": channel_key,
            "meme_id": meme_id,
            "telegram_message_id": telegram_message_id,
            "views": views,
            "forwards": forwards,
            "reactions": reaction_count,
            "comments": comments,
        }
    except FloodWaitError as e:
        log.warning("Telethon flood wait %ss on single-msg refresh @%s", e.seconds, username)
        return None
    except SessionExpiredError:
        log.error("Telethon session expired during single-msg refresh")
        return None
    except Exception as e:
        log.error(
            "Single-msg stats refresh failed @%s msg=%s: %s",
            username,
            telegram_message_id,
            e,
        )
        return None
    finally:
        await client.disconnect()


async def _collect_post_stats(client: TelegramClient, channel_key: str, channel_username: str):
    """Full sweep: views/forwards/reactions for recent posts in a channel.

    Posts may be tracked in two places: `crossposting` (meme cross-posts, high
    volume) or `editorial_posts` (editorial updates, ~1/day). A single
    Telegram message cannot be both, so we dispatch by source.
    """
    log = get_run_logger()

    try:
        entity = await client.get_entity(channel_username)
    except ChannelPrivateError:
        log.error(f"Cannot access @{channel_username} — private or no access")
        return

    # Editorial posts are low-volume (~1/day) so we keep refreshing ~30 days.
    # Meme crossposts get most views in the first 48h; re-updating is cheap.
    messages = await client.get_messages(entity, limit=FULL_SWEEP_MESSAGE_LIMIT)

    cutoff = datetime.utcnow() - FULL_SWEEP_MAX_AGE
    recent_messages = [m for m in messages if m.date and m.date.replace(tzinfo=None) > cutoff]

    log.info(f"@{channel_username}: {len(recent_messages)} posts in last 30d")

    if not recent_messages:
        return

    crosspost_rows = await fetch_all(
        text(
            "SELECT meme_id, telegram_message_id FROM crossposting "
            "WHERE channel = :channel AND telegram_message_id IS NOT NULL"
        ),
        {"channel": channel_key},
    )
    known_crosspost = (
        {r["telegram_message_id"]: r["meme_id"] for r in crosspost_rows} if crosspost_rows else {}
    )

    editorial_rows = await fetch_all(
        text(
            "SELECT id, telegram_message_id FROM editorial_posts "
            "WHERE channel = :channel AND telegram_message_id IS NOT NULL"
        ),
        {"channel": channel_key},
    )
    known_editorial = (
        {r["telegram_message_id"]: r["id"] for r in editorial_rows} if editorial_rows else {}
    )

    crosspost_snapshots = 0
    editorial_snapshots = 0
    for msg in recent_messages:
        views, forwards, reaction_count, reactions_detail, comments = _extract_metrics(msg)

        meme_id = known_crosspost.get(msg.id)
        editorial_id = known_editorial.get(msg.id)

        if meme_id is not None:
            await _persist_crosspost_metrics(
                channel_key=channel_key,
                meme_id=meme_id,
                telegram_message_id=msg.id,
                views=views,
                forwards=forwards,
                reactions=reaction_count,
                comments=comments,
                reactions_detail=reactions_detail,
                message_text=msg.text or "",
            )
            crosspost_snapshots += 1

        if editorial_id is not None:
            await _persist_editorial_metrics(
                channel_key=channel_key,
                editorial_post_id=editorial_id,
                telegram_message_id=msg.id,
                views=views,
                forwards=forwards,
                reactions=reaction_count,
                comments=comments,
                reactions_detail=reactions_detail,
            )
            editorial_snapshots += 1

    log.info(
        f"@{channel_username}: {crosspost_snapshots} crosspost snapshots, "
        f"{editorial_snapshots} editorial snapshots"
    )


async def _collect_young_crosspost_stats(
    client: TelegramClient,
    channel_key: str,
    channel_username: str,
    *,
    max_age: timedelta = YOUNG_POST_MAX_AGE,
) -> int:
    """Refresh only young crossposts (dense early samples for canaries)."""
    log = get_run_logger()
    if channel_key not in CROSSPOST_CHANNEL_KEYS:
        return 0

    young = await fetch_all(
        text(
            """
            SELECT meme_id, telegram_message_id
            FROM crossposting
            WHERE channel = :channel
              AND telegram_message_id IS NOT NULL
              AND created_at > NOW() - make_interval(hours => :max_age_hours)
            ORDER BY created_at DESC
            """
        ),
        {
            "channel": channel_key,
            "max_age_hours": int(max_age.total_seconds() // 3600),
        },
    )
    if not young:
        log.info("@%s: no young crossposts to refresh", channel_username)
        return 0

    try:
        entity = await client.get_entity(channel_username)
    except ChannelPrivateError:
        log.error("Cannot access @%s — private or no access", channel_username)
        return 0

    ids = [int(r["telegram_message_id"]) for r in young]
    id_to_meme = {int(r["telegram_message_id"]): int(r["meme_id"]) for r in young}

    # Telethon accepts a list of ids; may return list aligned with request.
    messages = await client.get_messages(entity, ids=ids)
    if not isinstance(messages, list):
        messages = [messages]

    refreshed = 0
    for msg in messages:
        if msg is None:
            continue
        meme_id = id_to_meme.get(msg.id)
        if meme_id is None:
            continue
        views, forwards, reaction_count, reactions_detail, comments = _extract_metrics(msg)
        await _persist_crosspost_metrics(
            channel_key=channel_key,
            meme_id=meme_id,
            telegram_message_id=msg.id,
            views=views,
            forwards=forwards,
            reactions=reaction_count,
            comments=comments,
            reactions_detail=reactions_detail,
            message_text=msg.text or "",
        )
        refreshed += 1

    log.info("@%s: refreshed %s/%s young crossposts", channel_username, refreshed, len(young))
    return refreshed


async def _collect_subscriber_count(
    client: TelegramClient,
    channel_key: str,
    channel_username: str,
):
    """Snapshot daily subscriber count for a channel."""
    log = get_run_logger()

    try:
        entity = await client.get_entity(channel_username)
        full = await client(GetFullChannelRequest(entity))
        count = full.full_chat.participants_count
    except ChannelPrivateError:
        log.error(f"Cannot access channel @{channel_username} for subscriber count")
        return
    except Exception as e:
        log.warning(f"Failed to get subscriber count for @{channel_username}: {e}")
        return

    today = datetime.utcnow().date()
    stmt = (
        insert(channel_daily_stats)
        .values(
            channel=channel_key,
            date=today,
            subscriber_count=count,
        )
        .on_conflict_do_update(
            index_elements=["channel", "date"],
            set_={"subscriber_count": count},
        )
    )
    await execute(stmt)
    log.info(f"@{channel_username}: {count} subscribers")


@flow(
    retries=2,
    retry_delay_seconds=60,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def collect_channel_stats():
    """Full sweep: post stats + subscriber counts for all channels."""
    log = get_run_logger()

    client = await _with_telethon_client()
    if client is None:
        return

    try:
        for channel_key, channel_username in CHANNELS.items():
            try:
                await _collect_post_stats(client, channel_key, channel_username)
                await _collect_subscriber_count(client, channel_key, channel_username)
            except FloodWaitError as e:
                log.warning(f"Telethon flood wait: {e.seconds}s — skipping @{channel_username}")
            except SessionExpiredError:
                log.error("Telethon session expired mid-collection")
                return
            except Exception as e:
                log.error(f"Error collecting stats for @{channel_username}: {e}")

    finally:
        await client.disconnect()

    log.info("Channel stats collection complete")


@flow(
    name="Collect Young Channel Stats",
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=180,
    on_failure=[notify_telegram_on_failure],
)
async def collect_young_channel_stats():
    """Hourly dense refresh for crossposts younger than 48h (early fwd/views).

    Complements the 6h full sweep so canaries (e.g. score_version=4) get
    1h/3h/6h samples instead of waiting up to a full 6h cycle.
    """
    log = get_run_logger()
    client = await _with_telethon_client()
    if client is None:
        return

    total = 0
    try:
        for channel_key in CROSSPOST_CHANNEL_KEYS:
            username = CHANNELS[channel_key]
            try:
                total += await _collect_young_crosspost_stats(client, channel_key, username)
            except FloodWaitError as e:
                log.warning("Telethon flood wait: %ss — skipping @%s", e.seconds, username)
            except SessionExpiredError:
                log.error("Telethon session expired mid young-post collection")
                return
            except Exception as e:
                log.error("Young-post stats error @%s: %s", username, e)
    finally:
        await client.disconnect()

    log.info("Young channel stats complete: %s messages refreshed", total)
