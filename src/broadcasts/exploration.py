"""One randomized content decision inside the existing weekly send opportunity."""

import asyncio
import hashlib
import json
import logging

from sqlalchemy import text
from telegram.error import BadRequest, RetryAfter

from src.config import settings
from src.database import engine, execute, fetch_one
from src.tgbot.bot import bot
from src.tgbot.senders.meme import send_meme_to_user

logger = logging.getLogger(__name__)
CAMPAIGN = "dormant_push_exploration_v1"
MAX_ENROLLMENTS_PER_RUN = 100


def content_variant(user_id: int) -> str:
    bucket = int.from_bytes(hashlib.sha256(f"{CAMPAIGN}:{user_id}".encode()).digest()[:8], "big")
    return "hq" if bucket % 100 < 50 else "explore"


async def reserve_opportunity(user_id: int, allow_enrollment: bool) -> dict | None:
    # A committed unique row owns this opportunity even if the process dies.
    # Do not retry this transaction after an ambiguous commit.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE push_content_control SET enabled = false, "
                "pause_reason = 'stale_sending' WHERE campaign = :campaign AND EXISTS "
                "(SELECT 1 FROM push_content_opportunity WHERE campaign = :campaign "
                "AND (state = 'unknown' OR error_code = 'post_acceptance_bookkeeping' "
                "OR (state = 'sending' AND attempted_at < timezone('UTC', now()) "
                "- interval '2 minutes')))"
            ),
            {"campaign": CAMPAIGN},
        )
        control = (
            (
                await conn.execute(
                    text(
                        "SELECT enabled, ends_at > timezone('UTC', now()) AS open "
                        "FROM push_content_control WHERE campaign = :campaign FOR SHARE"
                    ),
                    {"campaign": CAMPAIGN},
                )
            )
            .mappings()
            .one()
        )
        enrolled = bool(
            allow_enrollment
            and settings.DORMANT_PUSH_EXPLORATION_ENABLED
            and settings.BROADCAST_HIGH_QUALITY_PICK_ENABLED
            and settings.BROADCAST_CADENCE_HOLDOUT_ENABLED
            and control["enabled"]
            and control["open"]
        )
        variant = content_variant(user_id) if enrolled else "hq"
        row = (
            (
                await conn.execute(
                    text("""
                INSERT INTO push_content_opportunity
                    (campaign, user_id, opportunity_at, enrolled, variant)
                SELECT :campaign, u.id, u.last_active_at,
                       :enrolled AND vm.segment = 'user',
                       CASE WHEN :enrolled AND vm.segment = 'user'
                            THEN :variant ELSE 'hq' END
                FROM "user" u JOIN v_metric_user vm ON vm.user_id = u.id
                WHERE u.id = :user_id
                  AND u.blocked_bot_at IS NULL
                  AND u.type NOT IN ('waitlist', 'blocked_bot')
                  AND u.last_active_at BETWEEN
                      timezone('UTC', now()) - interval '7 days 1 hour'
                      AND timezone('UTC', now()) - interval '7 days'
                  AND EXISTS (SELECT 1 FROM user_meme_reaction r WHERE r.user_id = u.id
                      AND r.reacted_at >= timezone('UTC', now()) - interval '7 days 2 hours')
                  AND NOT EXISTS (SELECT 1 FROM user_meme_reaction r WHERE r.user_id = u.id
                      AND r.sent_at >= u.last_active_at + interval '7 days'
                      AND r.recommended_by LIKE 'broadcast%')
                ON CONFLICT (campaign, user_id, opportunity_at) DO NOTHING
                RETURNING *
                """),
                    {
                        "campaign": CAMPAIGN,
                        "user_id": user_id,
                        "enrolled": enrolled,
                        "variant": variant,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        if row["enrolled"]:
            await conn.execute(
                text("""
                INSERT INTO experiment_assignment
                    (experiment_id, user_id, variant, assignment_metadata)
                VALUES (:campaign, :user_id, :variant,
                        CAST(:metadata AS jsonb))
                ON CONFLICT (experiment_id, user_id) DO NOTHING
                """),
                {
                    "campaign": CAMPAIGN,
                    "user_id": user_id,
                    "variant": row["variant"],
                    "metadata": json.dumps(
                        {"arm_probability": 0.5, "step": "1w", "policy": "push_hq_top3_v1"}
                    ),
                },
            )
        return dict(row)


async def _update(opportunity_id: int, state: str, **fields) -> None:
    allowed = {"meme_id", "recommended_by", "selection", "error_code", "telegram_message_id"}
    if fields.keys() - allowed:
        raise ValueError("unsupported opportunity field")
    assignments = ["state = :state"]
    for key in fields:
        assignments.append(
            f"{key} = CAST(:{key} AS jsonb)" if key == "selection" else f"{key} = :{key}"
        )
    if state == "sending":
        assignments.append("attempted_at = timezone('UTC', now())")
    if state == "accepted":
        assignments.append("accepted_at = timezone('UTC', now())")
    # Accepted delivery survives any later failure to record local callbacks.
    expected = "state IN ('reserved', 'selected')"
    if state == "accepted":
        expected = "state IN ('sending', 'unknown')"
    elif state in {"failed", "unknown"}:
        expected = "state = 'sending'"
    result = await execute(
        text(
            f"UPDATE push_content_opportunity SET {', '.join(assignments)} "
            f"WHERE id = :id AND {expected}"
        ),
        {"id": opportunity_id, "state": state, **fields},
    )
    if result.rowcount != 1 and state not in {"failed", "unknown"}:
        raise RuntimeError("opportunity state changed unexpectedly")


async def pause_experiment(reason: str) -> None:
    await execute(
        text(
            "UPDATE push_content_control SET enabled = false, pause_reason = :reason "
            "WHERE campaign = :campaign"
        ),
        {"campaign": CAMPAIGN, "reason": reason},
    )


async def _still_eligible(opportunity: dict, meme_id: int) -> bool:
    row = await fetch_one(
        text("""
        SELECT 1 FROM "user" u JOIN meme m ON m.id = :meme_id
        JOIN user_language ul ON ul.user_id = u.id AND ul.language_code = m.language_code
        WHERE u.id = :user_id AND u.last_active_at = :anchor
          AND u.blocked_bot_at IS NULL AND u.type NOT IN ('waitlist', 'blocked_bot')
          AND u.last_active_at BETWEEN timezone('UTC', now()) - interval '7 days 1 hour'
                                  AND timezone('UTC', now()) - interval '7 days'
          AND m.status = 'ok' AND m.telegram_file_id IS NOT NULL
          AND m.type IN ('image', 'video', 'animation')
          AND NOT EXISTS (SELECT 1 FROM user_meme_reaction r
                          WHERE r.user_id = u.id AND r.meme_id = m.id)
        """),
        {
            "user_id": opportunity["user_id"],
            "anchor": opportunity["opportunity_at"],
            "meme_id": meme_id,
        },
    )
    return row is not None


class EligibilityChanged(Exception):
    pass


async def dispatch_opportunity(user_id: int, allow_enrollment: bool = True) -> str:
    from src.recommendations.broadcast_pick import (
        pick_exploration_meme,
        pick_reengagement_meme,
    )

    opportunity = await reserve_opportunity(user_id, allow_enrollment)
    if opportunity is None:
        return "duplicate_or_ineligible"
    opportunity_id = opportunity["id"]
    try:
        if opportunity["enrolled"]:
            meme, label, selection = await pick_exploration_meme(
                user_id, opportunity["variant"], opportunity["opportunity_at"].isoformat()
            )
        else:
            meme, label = await pick_reengagement_meme(user_id)
            selection = {
                "policy_version": "legacy_outside_experiment",
                "arm_probability": 1.0,
                "selection_probability": None,
                "candidate_ids": [],
                "fallback_reason": "outside_enrollment",
            }
        await _update(
            opportunity_id,
            "selected",
            meme_id=meme.id if meme else None,
            recommended_by=label,
            selection=json.dumps(selection),
        )
        if meme is None:
            await _update(opportunity_id, "skipped", error_code="no_meme")
            return "skipped"
    except Exception:
        await _update(opportunity_id, "skipped", error_code="preparation_error")
        raise

    attempted = False
    message_id = None

    async def sending():
        nonlocal attempted
        if not await _still_eligible(opportunity, meme.id):
            raise EligibilityChanged
        if opportunity["enrolled"]:
            control = await fetch_one(
                text(
                    "SELECT enabled AND ends_at > timezone('UTC', now()) AS active "
                    "FROM push_content_control WHERE campaign = :campaign"
                ),
                {"campaign": CAMPAIGN},
            )
            if not control or not control["active"]:
                raise EligibilityChanged
        await _update(opportunity_id, "sending")
        attempted = True

    async def receipt(message):
        nonlocal message_id
        message_id = message.message_id
        await _update(opportunity_id, "accepted", telegram_message_id=message_id)

    try:
        result = await asyncio.wait_for(
            send_meme_to_user(
                bot,
                user_id,
                meme,
                recommended_by=label,
                on_sending=sending,
                on_accepted=receipt,
            ),
            timeout=20,
        )
        if result is None:
            await _update(opportunity_id, "failed", error_code="forbidden")
    except (Exception, asyncio.CancelledError) as exc:
        if message_id is not None:
            # Telegram acceptance is known even if local persistence failed.
            try:
                await _update(
                    opportunity_id,
                    "accepted",
                    telegram_message_id=message_id,
                    error_code="post_acceptance_bookkeeping",
                )
            except RuntimeError:
                await execute(
                    text(
                        "UPDATE push_content_opportunity SET error_code = "
                        "'post_acceptance_bookkeeping' WHERE id = :id AND state = 'accepted'"
                    ),
                    {"id": opportunity_id},
                )
            await pause_experiment("post_acceptance_bookkeeping")
        elif not attempted:
            await _update(opportunity_id, "skipped", error_code="preparation_or_eligibility")
        elif isinstance(exc, (BadRequest, RetryAfter)):
            await _update(opportunity_id, "failed", error_code=type(exc).__name__)
        else:
            await _update(opportunity_id, "unknown", error_code="ambiguous_or_bookkeeping")
            await pause_experiment("ambiguous_or_bookkeeping")
        if isinstance(exc, asyncio.CancelledError):
            raise
        logger.warning("Opportunity %s ended with %s", opportunity_id, type(exc).__name__)
    await check_harm()
    return "accepted" if message_id is not None else "finished_without_acceptance"


async def check_harm() -> None:
    row = await fetch_one(
        text("""
        WITH arms AS (
            SELECT variant, count(*) FILTER (WHERE attempted_at IS NOT NULL)::float AS attempted,
                   count(*) FILTER (WHERE state IN ('failed', 'unknown'))::float AS failed,
                   count(*) FILTER (WHERE error_code = 'forbidden')::float AS blocked
            FROM push_content_opportunity WHERE campaign = :campaign AND enrolled
            GROUP BY variant
        )
        SELECT 1 FROM arms WHERE attempted >= 20 AND failed / NULLIF(attempted, 0) > 0.05
        UNION ALL
        SELECT 1 FROM arms e JOIN arms h ON h.variant = 'hq'
        WHERE e.variant = 'explore' AND e.attempted >= 50 AND h.attempted >= 50
          AND e.blocked >= 5
          AND e.blocked / NULLIF(e.attempted, 0) - h.blocked / NULLIF(h.attempted, 0) >= 0.03
        LIMIT 1
        """),
        {"campaign": CAMPAIGN},
    )
    if row:
        await pause_experiment("prespecified_delivery_or_block_harm")
