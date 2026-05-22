from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from telegram import Bot

from src.database import execute, fetch_one, meme_source
from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID


def _utcnow() -> datetime:
    return datetime.utcnow()


async def get_unreported_source_vote(now: datetime | None = None) -> dict[str, Any] | None:
    now = now or _utcnow()
    report_before = now - timedelta(hours=20)
    return await fetch_one(
        text(
            """
            SELECT *
            FROM meme_source
            WHERE data ? 'source_vote'
              AND data->'source_vote' ? 'enabled_at'
              AND NOT (data->'source_vote' ? 'report_sent_at')
              AND (data->'source_vote'->>'enabled_at')::timestamp <= :report_before
            ORDER BY (data->'source_vote'->>'enabled_at')::timestamp ASC
            LIMIT 1
            """
        ),
        {"report_before": report_before},
    )


async def build_source_vote_report(source: dict[str, Any]) -> dict[str, Any]:
    enabled_at = datetime.fromisoformat(source["data"]["source_vote"]["enabled_at"])
    return await fetch_one(
        text(
            """
            SELECT
                COUNT(m.id) AS memes_created,
                COUNT(m.id) FILTER (WHERE m.status = 'ok') AS ok_memes,
                COUNT(m.id) FILTER (WHERE m.status = 'duplicate') AS duplicate_memes,
                COUNT(m.id) FILTER (WHERE m.status = 'ad') AS ad_memes,
                COUNT(m.id) FILTER (WHERE m.status = 'rejected') AS rejected_memes,
                COALESCE(SUM(ms.nlikes), 0) AS likes,
                COALESCE(SUM(ms.ndislikes), 0) AS dislikes,
                COUNT(m.id) FILTER (
                    WHERE COALESCE(ms.nlikes, 0) > COALESCE(ms.ndislikes, 0)
                ) AS memes_more_likes,
                COUNT(m.id) FILTER (
                    WHERE COALESCE(ms.ndislikes, 0) > COALESCE(ms.nlikes, 0)
                ) AS memes_more_dislikes
            FROM meme m
            LEFT JOIN meme_stats ms
                ON ms.meme_id = m.id
            WHERE m.meme_source_id = :source_id
              AND m.created_at >= :enabled_at
            """
        ),
        {"source_id": source["id"], "enabled_at": enabled_at},
    )


def format_source_vote_report(source: dict[str, Any], report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Отчёт по источнику за первые сутки",
            "",
            f"Источник: {source['url']}",
            f"Статус источника: {source['status']}",
            f"Мемов создано: {report['memes_created']}",
            f"OK мемов в рекомендациях: {report['ok_memes']}",
            f"Лайков: {report['likes']}",
            f"Дизлайков: {report['dislikes']}",
            f"Мемов с лайков больше, чем дизлайков: {report['memes_more_likes']}",
            f"Мемов с дизлайков больше, чем лайков: {report['memes_more_dislikes']}",
            f"Дубликаты / реклама / отклонено: "
            f"{report['duplicate_memes']} / {report['ad_memes']} / {report['rejected_memes']}",
        ]
    )


async def mark_source_vote_report_sent(source_id: int, now: datetime | None = None) -> None:
    now = now or _utcnow()
    source = await fetch_one(select(meme_source).where(meme_source.c.id == source_id))
    if source is None:
        return
    data = dict(source.get("data") or {})
    source_vote = dict(data.get("source_vote") or {})
    source_vote["report_sent_at"] = now.isoformat()
    data["source_vote"] = source_vote
    await execute(
        meme_source.update()
        .where(meme_source.c.id == source_id)
        .values(data=data, updated_at=_utcnow())
    )


async def post_next_day_source_report(
    bot: Bot,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    source = await get_unreported_source_vote(now)
    if source is None:
        return {"status": "no_report"}
    report = await build_source_vote_report(source)
    await bot.send_message(
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        text=format_source_vote_report(source, report),
        disable_web_page_preview=True,
    )
    await mark_source_vote_report_sent(source["id"], now)
    return {"status": "reported", "source": source, "report": report}
