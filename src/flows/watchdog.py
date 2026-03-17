"""
Watchdog flow: checks that critical data pipelines ran recently.
Sends a Telegram alert if data is stale.
Only alerts once per issue (avoids spam every 5 min).
"""

import httpx
from prefect import flow, get_run_logger
from sqlalchemy import text

from src.config import settings
from src.database import fetch_one

# Track last alert state to avoid repeating the same alert
_last_alerts: set[str] = set()


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
    global _last_alerts
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
        alerts.append("No new meme_raw_telegram rows in 3 hours")

    # Check meme pipeline: any memes stuck in 'created' for too long
    row = await fetch_one(text("""
        SELECT COUNT(*) AS cnt
        FROM meme
        WHERE status = 'created'
          AND telegram_file_id IS NULL
          AND created_at < NOW() - INTERVAL '2 hours'
          AND created_at > NOW() - INTERVAL '24 hours'
    """))
    if row and row["cnt"] > 50:
        alerts.append(f"{row['cnt']} memes stuck without telegram_file_id for 2h+")

    # Check recommendation queues: are users getting memes?
    row = await fetch_one(text("""
        SELECT COUNT(*) AS cnt
        FROM user_meme_reaction
        WHERE reacted_at > NOW() - INTERVAL '30 minutes'
    """))
    if row and row["cnt"] == 0:
        alerts.append("Zero reactions in the last 30 minutes")

    current_alerts = set(alerts)

    # Only send NEW alerts (not already reported)
    new_alerts = current_alerts - _last_alerts
    if new_alerts:
        msg = "Watchdog:\n" + "\n".join(f"- {a}" for a in sorted(new_alerts))
        logger.warning(msg)
        _send_alert(msg)

    # Send recovery notification if issues resolved
    resolved = _last_alerts - current_alerts
    if resolved and _last_alerts:
        msg = "Watchdog recovered:\n" + "\n".join(
            f"- {a}" for a in sorted(resolved)
        )
        logger.info(msg)
        _send_alert(msg)

    _last_alerts = current_alerts

    if not current_alerts:
        logger.info("All systems healthy")
