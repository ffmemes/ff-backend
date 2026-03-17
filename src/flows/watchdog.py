"""
Watchdog flow: checks that critical data pipelines ran recently.
Sends a Telegram alert if data is stale.
"""

import httpx
from prefect import flow, get_run_logger
from sqlalchemy import text

from src.config import settings
from src.database import fetch_one


def _send_alert(msg: str) -> None:
    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.ADMIN_LOGS_CHAT_ID
    if not bot_token or not chat_id:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg},
            timeout=10,
        )
    except Exception:
        pass


@flow(name="Watchdog", log_prints=True)
async def watchdog() -> None:
    logger = get_run_logger()
    alerts = []

    # Check meme_stats freshness (should update every 15 min)
    row = await fetch_one(text("""
        SELECT MAX(updated_at) AS last_update
        FROM meme_stats
        WHERE updated_at > NOW() - INTERVAL '1 hour'
    """))
    if row is None or row["last_update"] is None:
        alerts.append("meme_stats not updated in the last hour")

    # Check parser freshness (TG sources should parse every hour)
    row = await fetch_one(text("""
        SELECT MAX(created_at) AS last_parse
        FROM meme_raw_telegram
        WHERE created_at > NOW() - INTERVAL '3 hours'
    """))
    if row is None or row["last_parse"] is None:
        alerts.append("No new meme_raw_telegram rows in the last 3 hours")

    if alerts:
        msg = "Watchdog alerts:\n" + "\n".join(f"- {a}" for a in alerts)
        logger.warning(msg)
        _send_alert(msg)
    else:
        logger.info("All systems healthy")
