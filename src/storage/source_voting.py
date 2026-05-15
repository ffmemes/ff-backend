import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from telegram import Bot
from telegram.error import TelegramError

from src.database import (
    execute,
    fetch_all,
    fetch_one,
    meme_source,
    meme_source_candidate,
    meme_source_candidate_poll,
    meme_source_candidate_vote,
)
from src.storage.constants import MemeSourceStatus, MemeSourceType
from src.storage.etl import insert_parsed_posts_from_telegram
from src.storage.moderation import advance_meme_source
from src.storage.parsers.schemas import TgChannelPostParsingResult
from src.storage.parsers.tg import TelegramChannelScraper
from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID
from src.tgbot.senders.keyboards import source_candidate_vote_keyboard

POLL_STATUS_DRAFT = "draft"
POLL_STATUS_OPEN = "open"
POLL_STATUS_PASSED = "passed"
POLL_STATUS_REJECTED = "rejected"
POLL_STATUS_EXPIRED_NO_QUORUM = "expired_no_quorum"
POLL_STATUS_CANCELLED = "cancelled"

CANDIDATE_STATUS_DISCOVERED = "discovered"
CANDIDATE_STATUS_PREPARED = "prepared"
CANDIDATE_STATUS_PROMOTED = "promoted"
CANDIDATE_STATUS_DISMISSED = "dismissed"

VOTE_ADD_SOURCE = 1
VOTE_SKIP_SOURCE = 2

SOURCE_VOTE_QUORUM = 3
SOURCE_VOTE_MIN_LIKES = 2
SOURCE_VOTE_LIKE_SHARE_THRESHOLD = 0.30
SOURCE_VOTE_WINDOW = timedelta(hours=24)

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def _utcnow() -> datetime:
    return datetime.utcnow()


def _telegram_username(source_url: str) -> str:
    return source_url.rstrip("/").split("/")[-1]


def _candidate_text_fragments(post: TgChannelPostParsingResult) -> list[str]:
    fragments: list[str] = []
    if post.content:
        fragments.append(post.content)
    link_preview = post.link_preview or {}
    for key in ("siteName", "title", "description"):
        value = link_preview.get(key)
        if isinstance(value, str) and value:
            fragments.append(value)
    return fragments


def extract_cyrillic_evidence(posts: list[TgChannelPostParsingResult]) -> str | None:
    for post in posts:
        for fragment in _candidate_text_fragments(post):
            if _CYRILLIC_RE.search(fragment):
                return " ".join(fragment.split())[:240]
    return None


async def fetch_telegram_candidate_posts(
    source_url: str,
    nposts: int = 20,
) -> list[TgChannelPostParsingResult]:
    scraper = TelegramChannelScraper(_telegram_username(source_url))
    return await scraper.get_items(nposts)


async def _get_meme_source_by_url(url: str) -> dict[str, Any] | None:
    return await fetch_one(select(meme_source).where(meme_source.c.url == url))


async def _mark_candidate(
    candidate_id: int,
    *,
    status: str,
    dismissed_reason: str | None = None,
    promoted_meme_source_id: int | None = None,
    expected_status: str | None = None,
) -> dict[str, Any] | None:
    update_stmt = meme_source_candidate.update().where(meme_source_candidate.c.id == candidate_id)
    if expected_status is not None:
        update_stmt = update_stmt.where(meme_source_candidate.c.status == expected_status)

    values: dict[str, Any] = {
        "status": status,
        "updated_at": _utcnow(),
    }
    if dismissed_reason is not None:
        values["dismissed_reason"] = dismissed_reason
    if promoted_meme_source_id is not None:
        values["promoted_meme_source_id"] = promoted_meme_source_id

    return await fetch_one(update_stmt.values(**values).returning(meme_source_candidate))


async def _create_or_reuse_prepared_source(
    candidate: dict[str, Any],
    added_by_user_id: int | None,
) -> dict[str, Any] | None:
    existing = await _get_meme_source_by_url(candidate["url"])
    if existing is not None:
        return existing

    insert_statement = (
        insert(meme_source)
        .values(
            {
                "url": candidate["url"],
                "type": candidate["type"],
                "status": MemeSourceStatus.IN_MODERATION.value,
                "added_by": added_by_user_id,
            }
        )
        .on_conflict_do_update(
            index_elements=(meme_source.c.url,),
            set_={"updated_at": _utcnow()},
        )
        .returning(meme_source)
    )
    return await fetch_one(insert_statement)


async def prepare_source_candidate(
    candidate_id: int,
    *,
    added_by_user_id: int | None = None,
    posts: list[TgChannelPostParsingResult] | None = None,
    nposts: int = 20,
) -> dict[str, Any]:
    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == candidate_id)
    )
    if candidate is None:
        return {"status": "not_found", "candidate": None, "source": None}
    if candidate["status"] == CANDIDATE_STATUS_PREPARED and candidate["promoted_meme_source_id"]:
        source = await fetch_one(
            select(meme_source).where(meme_source.c.id == candidate["promoted_meme_source_id"])
        )
        if source and source["status"] == MemeSourceStatus.PARSING_ENABLED.value:
            await _mark_candidate(
                candidate_id,
                status=CANDIDATE_STATUS_PROMOTED,
                promoted_meme_source_id=source["id"],
                expected_status=CANDIDATE_STATUS_PREPARED,
            )
            return {"status": "already_enabled", "candidate": candidate, "source": source}
        return {"status": "prepared", "candidate": candidate, "source": source}
    if candidate["status"] != CANDIDATE_STATUS_DISCOVERED:
        return {"status": candidate["status"], "candidate": candidate, "source": None}
    if candidate["type"] != MemeSourceType.TELEGRAM.value:
        await _mark_candidate(
            candidate_id,
            status=CANDIDATE_STATUS_DISMISSED,
            dismissed_reason="daily_source_vote:unsupported_type",
            expected_status=CANDIDATE_STATUS_DISCOVERED,
        )
        return {"status": "unsupported_type", "candidate": candidate, "source": None}

    source = await _create_or_reuse_prepared_source(candidate, added_by_user_id)
    if source is None:
        return {"status": "source_create_failed", "candidate": candidate, "source": None}
    if source["status"] == MemeSourceStatus.PARSING_ENABLED.value:
        await _mark_candidate(
            candidate_id,
            status=CANDIDATE_STATUS_PROMOTED,
            promoted_meme_source_id=source["id"],
            expected_status=CANDIDATE_STATUS_DISCOVERED,
        )
        return {"status": "already_enabled", "candidate": candidate, "source": source}

    if posts is None:
        posts = await fetch_telegram_candidate_posts(candidate["url"], nposts=nposts)

    evidence = extract_cyrillic_evidence(posts)
    if not posts:
        await advance_meme_source(
            source["id"],
            moderator_id="source-vote:prepare",
            status=MemeSourceStatus.PARSING_DISABLED.value,
            trigger_parse=False,
        )
        await _mark_candidate(
            candidate_id,
            status=CANDIDATE_STATUS_DISMISSED,
            dismissed_reason="daily_source_vote:no_public_posts",
            promoted_meme_source_id=source["id"],
            expected_status=CANDIDATE_STATUS_DISCOVERED,
        )
        return {
            "status": "no_public_posts",
            "candidate": candidate,
            "source": source,
            "posts_count": 0,
        }
    if evidence is None:
        await advance_meme_source(
            source["id"],
            moderator_id="source-vote:prepare",
            status=MemeSourceStatus.PARSING_DISABLED.value,
            trigger_parse=False,
        )
        await _mark_candidate(
            candidate_id,
            status=CANDIDATE_STATUS_DISMISSED,
            dismissed_reason="non_ru_no_cyrillic",
            promoted_meme_source_id=source["id"],
            expected_status=CANDIDATE_STATUS_DISCOVERED,
        )
        return {
            "status": "non_ru_no_cyrillic",
            "candidate": candidate,
            "source": source,
            "posts_count": len(posts),
        }

    await insert_parsed_posts_from_telegram(source["id"], posts, discover_candidates=False)
    source_result = await advance_meme_source(
        source["id"],
        moderator_id="source-vote:prepare",
        language_code="ru",
        trigger_parse=False,
    )
    prepared_candidate = await _mark_candidate(
        candidate_id,
        status=CANDIDATE_STATUS_PREPARED,
        promoted_meme_source_id=source["id"],
        expected_status=CANDIDATE_STATUS_DISCOVERED,
    )

    return {
        "status": "prepared",
        "candidate": prepared_candidate or candidate,
        "source": source_result["source"],
        "posts_count": len(posts),
        "cyrillic_evidence": evidence,
    }


async def get_source_candidate_vote_counts(poll_id: int) -> dict[str, int]:
    rows = await fetch_all(
        text(
            """
            SELECT vote, COUNT(*) AS voters
            FROM meme_source_candidate_vote
            WHERE poll_id = :poll_id
            GROUP BY vote
            """
        ),
        {"poll_id": poll_id},
    )
    yes = 0
    no = 0
    for row in rows:
        if row["vote"] == VOTE_ADD_SOURCE:
            yes = row["voters"]
        elif row["vote"] == VOTE_SKIP_SOURCE:
            no = row["voters"]
    return {"yes": yes, "no": no, "total": yes + no}


async def get_source_candidate_poll(poll_id: int) -> dict[str, Any] | None:
    return await fetch_one(
        select(meme_source_candidate_poll).where(meme_source_candidate_poll.c.id == poll_id)
    )


async def get_active_source_candidate_poll() -> dict[str, Any] | None:
    return await fetch_one(
        select(meme_source_candidate_poll)
        .where(meme_source_candidate_poll.c.status.in_([POLL_STATUS_DRAFT, POLL_STATUS_OPEN]))
        .order_by(meme_source_candidate_poll.c.created_at.asc())
        .limit(1)
    )


async def get_due_source_candidate_poll(now: datetime | None = None) -> dict[str, Any] | None:
    now = now or _utcnow()
    return await fetch_one(
        select(meme_source_candidate_poll)
        .where(meme_source_candidate_poll.c.status == POLL_STATUS_OPEN)
        .where(meme_source_candidate_poll.c.closes_at <= now)
        .order_by(meme_source_candidate_poll.c.closes_at.asc())
        .limit(1)
    )


async def record_source_candidate_vote(
    *,
    poll_id: int,
    user_id: int,
    vote: int,
    chat_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    if vote not in (VOTE_ADD_SOURCE, VOTE_SKIP_SOURCE):
        return {"status": "invalid_vote"}

    poll = await get_source_candidate_poll(poll_id)
    if poll is None:
        return {"status": "not_found"}
    if chat_id != TELEGRAM_MODERATOR_CHAT_ID or poll["chat_id"] != TELEGRAM_MODERATOR_CHAT_ID:
        return {"status": "wrong_chat", "poll": poll}
    if poll["chat_id"] != chat_id:
        return {"status": "wrong_chat", "poll": poll}
    if poll["status"] != POLL_STATUS_OPEN or poll["closes_at"] <= now:
        return {"status": "closed", "poll": poll}

    existing = await fetch_one(
        select(meme_source_candidate_vote)
        .where(meme_source_candidate_vote.c.poll_id == poll_id)
        .where(meme_source_candidate_vote.c.user_id == user_id)
    )
    stmt = (
        insert(meme_source_candidate_vote)
        .values(
            {
                "poll_id": poll_id,
                "user_id": user_id,
                "vote": vote,
            }
        )
        .on_conflict_do_update(
            index_elements=(
                meme_source_candidate_vote.c.poll_id,
                meme_source_candidate_vote.c.user_id,
            ),
            set_={"vote": vote, "updated_at": now},
        )
    )
    await execute(stmt)

    counts = await get_source_candidate_vote_counts(poll_id)
    return {
        "status": "changed" if existing and existing["vote"] != vote else "recorded",
        "poll": poll,
        "counts": counts,
    }


def source_vote_passed(counts: dict[str, int]) -> bool:
    total = counts["total"]
    return (
        total >= SOURCE_VOTE_QUORUM
        and counts["yes"] >= SOURCE_VOTE_MIN_LIKES
        and counts["yes"] / total > SOURCE_VOTE_LIKE_SHARE_THRESHOLD
    )


async def _set_poll_status(
    poll_id: int,
    *,
    status: str,
    closed_at: datetime | None = None,
    result_meme_source_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    values: dict[str, Any] = {"status": status, "updated_at": _utcnow()}
    if closed_at is not None:
        values["closed_at"] = closed_at
    if result_meme_source_id is not None:
        values["result_meme_source_id"] = result_meme_source_id
    if data is not None:
        values["data"] = data
    return await fetch_one(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll_id)
        .values(**values)
        .returning(meme_source_candidate_poll)
    )


async def _append_source_vote_metadata(
    source_id: int,
    *,
    poll: dict[str, Any],
    counts: dict[str, int],
    enabled_at: datetime,
) -> dict[str, Any] | None:
    source = await fetch_one(select(meme_source).where(meme_source.c.id == source_id))
    if source is None:
        return None
    data = dict(source.get("data") or {})
    data["source_vote"] = {
        **dict(data.get("source_vote") or {}),
        "poll_id": poll["id"],
        "candidate_id": poll["candidate_id"],
        "chat_id": poll["chat_id"],
        "message_id": poll["message_id"],
        "yes": counts["yes"],
        "no": counts["no"],
        "closed_at": enabled_at.isoformat(),
        "enabled_at": enabled_at.isoformat(),
    }
    return await fetch_one(
        meme_source.update()
        .where(meme_source.c.id == source_id)
        .values(data=data, updated_at=_utcnow())
        .returning(meme_source)
    )


async def enable_passed_source_poll(
    poll: dict[str, Any],
    counts: dict[str, int],
    now: datetime,
) -> dict[str, Any] | None:
    source_id = poll["prepared_meme_source_id"]
    if source_id is None:
        candidate = await fetch_one(
            select(meme_source_candidate).where(meme_source_candidate.c.id == poll["candidate_id"])
        )
        source_id = None if candidate is None else candidate["promoted_meme_source_id"]
    if source_id is None:
        return None

    await advance_meme_source(
        source_id,
        moderator_id=f"source-vote:{poll['id']}",
        language_code="ru",
        status=MemeSourceStatus.PARSING_ENABLED.value,
        trigger_parse=False,
    )
    await _mark_candidate(
        poll["candidate_id"],
        status=CANDIDATE_STATUS_PROMOTED,
        promoted_meme_source_id=source_id,
    )
    await _append_source_vote_metadata(source_id, poll=poll, counts=counts, enabled_at=now)

    from src.flows.storage.memes import process_cached_telegram_source

    await process_cached_telegram_source(source_id)
    return await fetch_one(select(meme_source).where(meme_source.c.id == source_id))


async def close_source_candidate_poll(
    poll_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    poll = await get_source_candidate_poll(poll_id)
    if poll is None:
        return {"status": "not_found"}
    if poll["status"] != POLL_STATUS_OPEN:
        return {"status": "already_closed", "poll": poll}

    counts = await get_source_candidate_vote_counts(poll_id)
    poll_data = dict(poll.get("data") or {})
    poll_data["final_counts"] = counts

    result_source = None
    if counts["total"] < SOURCE_VOTE_QUORUM:
        status = POLL_STATUS_EXPIRED_NO_QUORUM
    elif source_vote_passed(counts):
        status = POLL_STATUS_PASSED
        result_source = await enable_passed_source_poll(poll, counts, now)
    else:
        status = POLL_STATUS_REJECTED
        if poll["prepared_meme_source_id"]:
            await advance_meme_source(
                poll["prepared_meme_source_id"],
                moderator_id=f"source-vote:{poll_id}",
                status=MemeSourceStatus.PARSING_DISABLED.value,
                trigger_parse=False,
            )
        await _mark_candidate(
            poll["candidate_id"],
            status=CANDIDATE_STATUS_DISMISSED,
            dismissed_reason=f"source_vote:{poll_id}",
        )

    updated_poll = await _set_poll_status(
        poll_id,
        status=status,
        closed_at=now,
        result_meme_source_id=None if result_source is None else result_source["id"],
        data=poll_data,
    )
    return {
        "status": status,
        "poll": updated_poll,
        "counts": counts,
        "source": result_source,
    }


async def select_daily_source_candidate() -> dict[str, Any] | None:
    return await fetch_one(
        text(
            """
            SELECT c.*
            FROM meme_source_candidate c
            WHERE c.status IN ('discovered', 'prepared')
              AND c.type = 'telegram'
              AND NOT EXISTS (
                  SELECT 1
                  FROM meme_source_candidate_poll p
                  WHERE p.candidate_id = c.id
                    AND p.status IN (
                        'draft',
                        'open',
                        'passed',
                        'rejected',
                        'expired_no_quorum'
                    )
              )
              AND (
                  c.status = 'prepared'
                  OR NOT EXISTS (
                      SELECT 1 FROM meme_source ms WHERE ms.url = c.url
                  )
              )
            ORDER BY c.times_forwarded DESC, c.last_seen_at DESC
            LIMIT 1
            """
        )
    )


def format_source_candidate_poll_message(
    candidate: dict[str, Any],
    _prepared: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Добавляем новый источник мемов?",
            "",
            f"🔗 {candidate['url']}",
            "",
            f"Наши паблики пересылали мемы оттуда {candidate['times_forwarded']} раз.",
            "Откройте ссылку и проголосуйте ниже.",
            "Голосование решит, начнем ли брать оттуда мемы на постоянке.",
        ]
    )


def format_closed_poll_message(result: dict[str, Any]) -> str:
    counts = result["counts"]
    status = result["status"]
    if status == POLL_STATUS_PASSED:
        outcome = "Источник добавлен."
    elif status == POLL_STATUS_REJECTED:
        outcome = "Источник отклонён."
    elif status == POLL_STATUS_EXPIRED_NO_QUORUM:
        outcome = "Недостаточно голосов. Автоматически не возвращаем."
    else:
        outcome = f"Голосование закрыто: {status}."
    return (
        f"{outcome}\n\n"
        f"За: {counts['yes']}\n"
        f"Против: {counts['no']}\n"
        f"Всего голосов: {counts['total']}"
    )


async def create_source_candidate_poll(
    candidate_id: int,
    *,
    prepared_meme_source_id: int,
    chat_id: int,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    now = now or _utcnow()
    stmt = (
        insert(meme_source_candidate_poll)
        .values(
            {
                "candidate_id": candidate_id,
                "prepared_meme_source_id": prepared_meme_source_id,
                "chat_id": chat_id,
                "status": POLL_STATUS_DRAFT,
                "closes_at": now + SOURCE_VOTE_WINDOW,
            }
        )
        .returning(meme_source_candidate_poll)
    )
    return await fetch_one(stmt)


async def mark_source_candidate_poll_open(
    poll_id: int,
    *,
    message_id: int,
    opened_at: datetime | None = None,
) -> dict[str, Any] | None:
    opened_at = opened_at or _utcnow()
    return await fetch_one(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll_id)
        .where(meme_source_candidate_poll.c.status == POLL_STATUS_DRAFT)
        .values(
            message_id=message_id,
            opened_at=opened_at,
            status=POLL_STATUS_OPEN,
            updated_at=_utcnow(),
        )
        .returning(meme_source_candidate_poll)
    )


async def cancel_source_candidate_poll(poll_id: int) -> dict[str, Any] | None:
    return await _set_poll_status(poll_id, status=POLL_STATUS_CANCELLED)


async def post_source_candidate_poll_message(
    bot: Bot,
    poll: dict[str, Any],
    *,
    now: datetime | None = None,
    prepared: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    if poll["chat_id"] != TELEGRAM_MODERATOR_CHAT_ID:
        await cancel_source_candidate_poll(poll["id"])
        return {
            "status": "wrong_chat_target",
            "poll": await get_source_candidate_poll(poll["id"]) or poll,
        }

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == poll["candidate_id"])
    )
    if candidate is None:
        await cancel_source_candidate_poll(poll["id"])
        return {"status": "candidate_not_found", "poll": poll}

    source_id = poll["prepared_meme_source_id"] or candidate["promoted_meme_source_id"]
    if source_id is None:
        await cancel_source_candidate_poll(poll["id"])
        return {"status": "prepared_source_not_found", "poll": poll, "candidate": candidate}

    source = await fetch_one(select(meme_source).where(meme_source.c.id == source_id))
    if source is None:
        await cancel_source_candidate_poll(poll["id"])
        return {"status": "prepared_source_not_found", "poll": poll, "candidate": candidate}

    if poll["message_id"]:
        opened = await mark_source_candidate_poll_open(
            poll["id"],
            message_id=poll["message_id"],
            opened_at=now,
        )
        return {
            "status": "opened_existing_message",
            "poll": opened or await get_source_candidate_poll(poll["id"]),
            "candidate": candidate,
            "prepared": prepared or {"source": source},
        }

    message = await bot.send_message(
        chat_id=poll["chat_id"],
        text=format_source_candidate_poll_message(candidate, prepared or {"source": source}),
        reply_markup=source_candidate_vote_keyboard(poll["id"]),
        disable_web_page_preview=True,
    )
    if hasattr(bot, "pin_chat_message"):
        try:
            await bot.pin_chat_message(
                chat_id=poll["chat_id"],
                message_id=message.message_id,
                disable_notification=True,
            )
        except TelegramError:
            # Best-effort: poll should still stay open even if bot cannot pin.
            pass
    opened = await mark_source_candidate_poll_open(
        poll["id"],
        message_id=message.message_id,
        opened_at=now,
    )
    return {
        "status": "posted",
        "poll": opened or await get_source_candidate_poll(poll["id"]),
        "candidate": candidate,
        "prepared": prepared or {"source": source},
    }


async def post_new_source_candidate_poll(
    bot: Bot,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    draft_poll = await fetch_one(
        select(meme_source_candidate_poll)
        .where(meme_source_candidate_poll.c.status == POLL_STATUS_DRAFT)
        .order_by(meme_source_candidate_poll.c.created_at.asc())
        .limit(1)
    )
    if draft_poll is not None:
        return await post_source_candidate_poll_message(bot, draft_poll, now=now)

    candidate = await select_daily_source_candidate()
    if candidate is None:
        return {"status": "no_candidate"}

    prepared = await prepare_source_candidate(candidate["id"])
    if prepared["status"] != "prepared":
        return {"status": prepared["status"], "candidate": candidate, "prepared": prepared}
    if prepared["source"] is None:
        return {"status": "prepared_source_not_found", "candidate": candidate, "prepared": prepared}

    poll = await create_source_candidate_poll(
        candidate["id"],
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=now,
    )
    if poll is None:
        return {"status": "poll_create_failed", "candidate": candidate}

    return await post_source_candidate_poll_message(bot, poll, now=now, prepared=prepared)


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


async def advance_daily_source_cycle(
    bot: Bot,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _utcnow()
    result: dict[str, Any] = {}

    result["report"] = await post_next_day_source_report(bot, now=now)

    due_poll = await get_due_source_candidate_poll(now)
    if due_poll is not None:
        close_result = await close_source_candidate_poll(due_poll["id"], now=now)
        result["closed_poll"] = close_result
        if due_poll["message_id"]:
            await bot.edit_message_text(
                chat_id=due_poll["chat_id"],
                message_id=due_poll["message_id"],
                text=format_closed_poll_message(close_result),
                disable_web_page_preview=True,
            )

    active_poll = await get_active_source_candidate_poll()
    if active_poll is not None:
        if active_poll["status"] == POLL_STATUS_DRAFT:
            result["new_poll"] = await post_source_candidate_poll_message(
                bot,
                active_poll,
                now=now,
            )
            return result
        result["new_poll"] = {"status": "active_poll_exists", "poll": active_poll}
        return result

    result["new_poll"] = await post_new_source_candidate_poll(bot, now=now)
    return result
