"""
Channel post stats collector via Telethon.

Reads views, forwards, reactions from @fastfoodmemes and @fast_food_memes
channel posts. Stores time-series snapshots for analysis.

Runs every 6 hours via Prefect cron (registered in serve_flows.py).

Uses the same Telethon session string as e2e_smoke.py (TELEGRAM_API_ID,
TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING env vars).
"""

import logging
from datetime import datetime, timedelta

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
    crossposting,
    crossposting_snapshots,
    execute,
    fetch_all,
)
from src.flows.hooks import notify_telegram_on_failure

logger = logging.getLogger(__name__)

# Channel usernames (without @)
CHANNELS = {
    "tgchannelru": "fastfoodmemes",
    "tgchannelen": "fast_food_memes",
}


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


async def _collect_post_stats(client: TelegramClient, channel_key: str, channel_username: str):
    """Collect views/forwards/reactions for recent posts in a channel."""
    log = get_run_logger()

    try:
        entity = await client.get_entity(channel_username)
    except ChannelPrivateError:
        log.error(f"Cannot access @{channel_username} — private or no access")
        return

    # Get recent posts (last 48h worth, limit 50)
    messages = await client.get_messages(entity, limit=50)

    cutoff = datetime.utcnow() - timedelta(hours=48)
    recent_messages = [m for m in messages if m.date and m.date.replace(tzinfo=None) > cutoff]

    log.info(f"@{channel_username}: {len(recent_messages)} posts in last 48h")

    # Get crossposting rows that have telegram_message_id for matching
    if not recent_messages:
        return

    # Fetch all crossposting rows for this channel that have telegram_message_id set.
    # We filter in Python rather than using ANY() which isn't used elsewhere in the codebase.
    rows = await fetch_all(
        text(
            "SELECT meme_id, telegram_message_id FROM crossposting "
            "WHERE channel = :channel AND telegram_message_id IS NOT NULL"
        ),
        {"channel": channel_key},
    )
    known_msg_ids = {r["telegram_message_id"]: r["meme_id"] for r in rows} if rows else {}

    snapshots_inserted = 0
    for msg in recent_messages:
        views = getattr(msg, "views", None) or 0
        forwards = getattr(msg, "forwards", None) or 0
        # Telethon message.reactions is a MessageReactions object
        reaction_count = 0
        if hasattr(msg, "reactions") and msg.reactions and hasattr(msg.reactions, "results"):
            reaction_count = sum(r.count for r in msg.reactions.results)

        meme_id = known_msg_ids.get(msg.id)
        if meme_id is None:
            # Post not tracked in crossposting table (pre-T2 post or manual post)
            continue

        # Insert time-series snapshot
        snapshot_stmt = (
            insert(crossposting_snapshots)
            .values(
                channel=channel_key,
                meme_id=meme_id,
                telegram_message_id=msg.id,
                views=views,
                forwards=forwards,
                reactions=reaction_count,
                message_text=(msg.text or "")[:500],
            )
        )
        await execute(snapshot_stmt)
        snapshots_inserted += 1

        # Update latest values on crossposting table
        await execute(
            text(
                "UPDATE crossposting SET views = :views, forwards = :forwards, "
                "reactions = :reactions, stats_updated_at = NOW() "
                "WHERE channel = :channel AND telegram_message_id = :msg_id"
            ),
            {"views": views, "forwards": forwards, "reactions": reaction_count,
             "channel": channel_key, "msg_id": msg.id},
        )

    log.info(f"@{channel_username}: {snapshots_inserted} snapshots inserted")


async def _collect_subscriber_count(
    client: TelegramClient, channel_key: str, channel_username: str,
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
    """Collect post stats and subscriber counts for all crossposting channels."""
    log = get_run_logger()

    client = _get_telethon_client()
    if client is None:
        log.warning(
            "Telethon not configured — set TELEGRAM_API_ID, TELEGRAM_API_HASH, "
            "TELEGRAM_SESSION_STRING to enable channel stats collection"
        )
        return

    try:
        await client.connect()
        if not await client.is_user_authorized():
            log.error(
                "Telethon session expired. Regenerate with: "
                "python scripts/generate_session_string.py"
            )
            return

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
