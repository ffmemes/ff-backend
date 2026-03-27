"""
Weekly burger economy report for @ffmemes channel.

Posts a Sunday 14:00 MSK summary of burger transactions to the channel.
Scheduled via Prefect cron in serve_flows.py.
"""

from prefect import flow, get_run_logger
from sqlalchemy import text
from telegram.constants import ParseMode

from src.database import fetch_all, fetch_one
from src.flows.hooks import notify_telegram_on_failure
from src.tgbot.bot import bot
from src.tgbot.constants import TELEGRAM_CHANNEL_RU_CHAT_ID


async def _get_weekly_burger_stats() -> dict:
    """Query treasury_trx for weekly aggregates."""

    total_minted = await fetch_one(
        text("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM treasury_trx
            WHERE amount > 0
              AND created_at > now() - interval '7 days'
        """)
    )

    total_spent = await fetch_one(
        text("""
            SELECT COALESCE(SUM(ABS(amount)), 0) as total
            FROM treasury_trx
            WHERE amount < 0
              AND created_at > now() - interval '7 days'
        """)
    )

    active_earners = await fetch_one(
        text("""
            SELECT COUNT(DISTINCT user_id) as count
            FROM treasury_trx
            WHERE amount > 0
              AND created_at > now() - interval '7 days'
        """)
    )

    top_earners = await fetch_all(
        text("""
            SELECT user_id, SUM(amount) as earned
            FROM treasury_trx
            WHERE amount > 0
              AND created_at > now() - interval '7 days'
            GROUP BY user_id
            ORDER BY earned DESC
            LIMIT 5
        """)
    )

    total_supply = await fetch_one(
        text("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM treasury_trx
        """)
    )

    return {
        "minted": total_minted["total"] if total_minted else 0,
        "spent": abs(total_spent["total"]) if total_spent else 0,
        "active_earners": active_earners["count"] if active_earners else 0,
        "top_earners": top_earners or [],
        "total_supply": total_supply["total"] if total_supply else 0,
    }


def _format_report(stats: dict) -> str:
    """Format burger stats as a Russian-language channel post."""
    lines = [
        "🍔 <b>Бургерномика за неделю</b>",
        "",
        f"▪ Выпущено: <b>{stats['minted']:,}</b> 🍔".replace(",", " "),
        f"▪ Потрачено: <b>{stats['spent']:,}</b> 🍔".replace(",", " "),
        f"▪ Заработали бургеры: <b>{stats['active_earners']}</b> чел",
        f"▪ Всего в обороте: <b>{stats['total_supply']:,}</b> 🍔".replace(",", " "),
    ]

    if stats["top_earners"]:
        lines.append("")
        lines.append("Топ-5 бургермагнатов:")
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, earner in enumerate(stats["top_earners"]):
            earned = int(earner["earned"])
            lines.append(f"{medals[i]} +{earned:,} 🍔".replace(",", " "))

    lines.append("")
    lines.append('Как заработать бургеры: <a href="https://t.me/ffmemesbot?start=kitchen">/kitchen</a>')

    return "\n".join(lines)


@flow(
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=120,
    on_failure=[notify_telegram_on_failure],
)
async def post_weekly_burger_report():
    """Post weekly burger economy snapshot to @ffmemes channel."""
    logger = get_run_logger()

    stats = await _get_weekly_burger_stats()
    logger.info(f"Weekly burger stats: minted={stats['minted']}, spent={stats['spent']}")

    text = _format_report(stats)

    msg = await bot.send_message(
        chat_id=TELEGRAM_CHANNEL_RU_CHAT_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    logger.info(f"Posted weekly burger report: msg_id={msg.message_id}")
    return msg.message_id
