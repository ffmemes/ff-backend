import asyncio
from datetime import datetime, timezone

from prefect import flow, get_run_logger

from src.broadcasts.service import (
    drop_holdout,
    get_monthly_reminder_user_ids,
    get_user_ids_active_minutes_ago,
    send_meme_broadcast,
)
from src.config import settings
from src.flows.hooks import notify_telegram_on_failure
from src.recommendations.broadcast_pick import pick_reengagement_meme
from src.tgbot.bot import bot
from src.tgbot.senders.meme import send_meme_to_user

CADENCE_HOLDOUT_EXPERIMENT = "broadcast_cadence_holdout_v1"
# Per-step no-push share; 48h has no holdout.
CADENCE_HOLDOUT_PCT = {"15m": 15, "24h": 15, "1w": 20, "2w": 20, "4w": 20}
MONTHLY_REMINDER_EXPERIMENT = "monthly_reminder_v1"

_BROADCAST_FLOW_OPTS = dict(
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=600,
    on_failure=[notify_telegram_on_failure],
)


async def _send_to_user(
    user_id: int,
    *,
    broadcast_label: str | None = None,
) -> None:
    # HQ pick (affinity + proven LR) when enabled; else feed-queue fallback.
    # recommended_by is broadcast_reengagement_hq vs broadcast_reengagement
    # so we can measure push effectiveness separately from in-session feed.
    meme, picked_label = await pick_reengagement_meme(user_id)
    if meme:
        await send_meme_to_user(
            bot,
            user_id,
            meme,
            recommended_by=broadcast_label or picked_label,
        )


async def broadcast_next_meme_to_users(user_ids: list[int]):
    logger = get_run_logger()
    logger.info(f"Going to sent next meme to {len(user_ids)} users")

    for user_id in user_ids:
        try:
            await asyncio.wait_for(
                _send_to_user(user_id),
                timeout=20,
            )
            logger.info(f"Sent meme to #{user_id}")
        except asyncio.TimeoutError:
            logger.warning(f"Timed out processing user #{user_id} (>20s), skipping")
        except Exception:
            logger.warning(f"Failed to send meme to #{user_id}", exc_info=True)
        await asyncio.sleep(0.2)  # flood control


async def _broadcast_cadence_step(step: str, from_minutes_ago: int, to_minutes_ago: int):
    user_ids = await get_user_ids_active_minutes_ago(from_minutes_ago, to_minutes_ago)
    holdout_pct = CADENCE_HOLDOUT_PCT.get(step)
    if holdout_pct and settings.BROADCAST_CADENCE_HOLDOUT_ENABLED:
        user_ids = await drop_holdout(f"{CADENCE_HOLDOUT_EXPERIMENT}_{step}", user_ids, holdout_pct)
    await broadcast_next_meme_to_users(user_ids)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_15m_ago():
    await _broadcast_cadence_step("15m", 15, 30)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_24h_ago():
    await _broadcast_cadence_step("24h", 24 * 60, 24 * 60 + 60)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_48h_ago():
    await _broadcast_cadence_step("48h", 48 * 60, 48 * 60 + 60)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_1w_ago():
    await _broadcast_cadence_step("1w", 7 * 24 * 60, 7 * 24 * 60 + 60)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_2w_ago():
    await _broadcast_cadence_step("2w", 2 * 7 * 24 * 60, 2 * 7 * 24 * 60 + 60)


@flow(**_BROADCAST_FLOW_OPTS)
async def broadcast_next_meme_to_active_4w_ago():
    await _broadcast_cadence_step("4w", 4 * 7 * 24 * 60, 4 * 7 * 24 * 60 + 60)


@flow(**{**_BROADCAST_FLOW_OPTS, "timeout_seconds": 3 * 60 * 60})
async def broadcast_monthly_reminder():
    """One HQ meme to users who reacted before and went quiet 29-365 days ago."""
    logger = get_run_logger()
    if not settings.MONTHLY_REMINDER_ENABLED:
        logger.info("MONTHLY_REMINDER_ENABLED is off; skipping")
        return
    user_ids = await drop_holdout(
        MONTHLY_REMINDER_EXPERIMENT,
        await get_monthly_reminder_user_ids(),
        settings.MONTHLY_REMINDER_HOLDOUT_PCT,
    )
    # One broadcast_id per month: Redis dedup makes retries/re-runs safe.
    broadcast_id = f"monthly-reminder-{datetime.now(timezone.utc):%Y-%m}"
    result = await send_meme_broadcast(broadcast_id, user_ids)
    logger.info(f"{broadcast_id}: {result}")
