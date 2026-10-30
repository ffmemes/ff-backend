"""Friend challenge storage: fixed five-meme packs, first answers, assignment and offers.

The rollout flag and Telegram delivery belong to callers.
"""

import hashlib
import secrets
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src import redis
from src.database import (
    execute,
    fetch_all,
    fetch_one,
    friend_challenge_answer,
    friend_challenge_item,
    friend_challenge_pack,
    friend_challenge_participation,
    meme,
    run_in_transaction,
)
from src.recommendations.candidates import (
    COLD_START_EXPLORE_MIN_EXPLICIT_REACTIONS,
    COLD_START_EXPLORE_MIN_LR_SMOOTHED,
    COLD_START_EXPLORE_MIN_RAW_LIKE_RATE,
)
from src.storage.constants import MemeStatus, MemeType
from src.tgbot.repo.experiments import assign_experiment, get_experiment_assignment

PACK_SIZE = 5
EXPERIMENT_ID = "friend_challenge_h12"
TREATMENT = "treatment"
HOLDOUT = "holdout"
HOLDOUT_PERCENT = 10
ELIGIBILITY_CHECK_TTL = 24 * 60 * 60

# Regular users and moderators; admins, blocked and waitlist users are out.
ELIGIBLE_USER_TYPES = ("user", "active_user", "super_user", "moderator")
MIN_ACTIVE_DAYS_28D = 8
MIN_LIKES_28D = 20


def variant_for_user(user_id: int) -> str:
    key = f"{EXPERIMENT_ID}:{user_id}"
    bucket = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % 100
    return HOLDOUT if bucket < HOLDOUT_PERCENT else TREATMENT


async def get_or_assign_variant(user_id: int) -> dict[str, Any] | None:
    """Return the assignment row, assigning eligible users (checked at most daily)."""
    assignment = await get_experiment_assignment(user_id, EXPERIMENT_ID)
    if assignment is not None:
        return assignment
    gate = f"friend_challenge:eligibility_checked:{user_id}"
    if not await redis.redis_client.set(gate, "1", nx=True, ex=ELIGIBILITY_CHECK_TTL):
        return None
    activity = await fetch_one(
        text(
            """
            SELECT count(DISTINCT r.reacted_at::date) AS active_days_28d,
                   count(*) FILTER (WHERE r.reaction_id = 1) AS likes_28d
            FROM "user" u
            JOIN user_meme_reaction r ON r.user_id = u.id
            WHERE u.id = :user_id
              AND u.type = ANY(CAST(:types AS text[])) AND u.blocked_bot_at IS NULL
              AND r.reacted_at >= (NOW() AT TIME ZONE 'UTC') - interval '28 days'
              AND r.reaction_id IN (1, 2)
              AND coalesce(r.recommended_by, '') <> 'friend_challenge'
            """
        ),
        {"user_id": user_id, "types": list(ELIGIBLE_USER_TYPES)},
    )
    if not activity or not (
        activity["active_days_28d"] >= MIN_ACTIVE_DAYS_28D
        and activity["likes_28d"] >= MIN_LIKES_28D
    ):
        return None
    await assign_experiment(
        user_id,
        EXPERIMENT_ID,
        variant_for_user(user_id),
        {
            "assignment_strategy": f"sha256(experiment_id:user_id)%100<{HOLDOUT_PERCENT}=holdout",
            "active_days_28d": activity["active_days_28d"],
            "likes_28d": activity["likes_28d"],
        },
    )
    return await get_experiment_assignment(user_id, EXPERIMENT_ID)


async def claim_offer(user_id: int, meme_id: int) -> bool:
    """Atomically consume the only offer attempt; call mark_offer_sent after delivery."""
    row = await fetch_one(
        text(
            """
            UPDATE experiment_assignment
            SET assignment_metadata = assignment_metadata || jsonb_build_object(
                'offer_attempted_at', NOW(), 'offer_trigger_meme_id', CAST(:meme_id AS bigint)
            )
            WHERE experiment_id = :experiment_id AND user_id = :user_id
              AND variant = :treatment
              AND NOT (assignment_metadata ? 'offer_attempted_at')
            RETURNING user_id
            """
        ),
        {
            "user_id": user_id,
            "meme_id": meme_id,
            "experiment_id": EXPERIMENT_ID,
            "treatment": TREATMENT,
        },
    )
    return row is not None


async def mark_offer_sent(user_id: int) -> None:
    await execute(
        text(
            """
            UPDATE experiment_assignment
            SET assignment_metadata = assignment_metadata || jsonb_build_object('offered_at', NOW())
            WHERE experiment_id = :experiment_id AND user_id = :user_id
              AND NOT (assignment_metadata ? 'offered_at')
            """
        ),
        {"user_id": user_id, "experiment_id": EXPERIMENT_ID},
    )


async def authorized_to_create(user_id: int) -> bool:
    """Treatment users, or unassigned users who finished a friend's five memes.

    An assignment wins over completion, so the holdout never creates packs.
    """
    row = await fetch_one(
        text(
            """
            SELECT COALESCE(
                (SELECT variant = :treatment FROM experiment_assignment
                 WHERE experiment_id = :experiment_id AND user_id = :user_id),
                EXISTS (
                    SELECT 1 FROM friend_challenge_participation
                    WHERE user_id = :user_id AND completed_at IS NOT NULL
                )
            ) AS authorized
            """
        ),
        {"user_id": user_id, "experiment_id": EXPERIMENT_ID, "treatment": TREATMENT},
    )
    return bool(row and row["authorized"])


async def candidate_meme_ids(user_id: int) -> list[int]:
    """Recent personal likes first, then reviewed-quality memes in the user's languages.

    The owner previews and confirms all five. Returns fewer than five on thin inventory.
    """
    rows = await fetch_all(
        text(
            """
            WITH available AS NOT MATERIALIZED (
                SELECT M.id, M.meme_source_id, M.telegram_file_id,
                       R.reaction_id, R.reacted_at
                FROM meme M
                LEFT JOIN user_meme_reaction R
                    ON R.user_id = :user_id AND R.meme_id = M.id
                WHERE M.status = 'ok'
                  AND NULLIF(BTRIM(M.telegram_file_id), '') IS NOT NULL
                  AND M.type IN ('image', 'video', 'animation')
                  AND EXISTS (
                      SELECT 1 FROM user_language L
                      WHERE L.user_id = :user_id AND L.language_code = M.language_code
                  )
                  AND R.reaction_id IS DISTINCT FROM 2
            ), liked AS (
                SELECT A.*, 0 AS tier, 0.0 AS quality
                FROM available A
                WHERE A.reaction_id = 1
                ORDER BY A.reacted_at DESC NULLS LAST, A.id DESC
                LIMIT 100
            ), fallback AS (
                SELECT A.*, 1 AS tier, MS.lr_smoothed AS quality
                FROM available A
                JOIN meme_stats MS ON MS.meme_id = A.id
                WHERE A.reaction_id IS DISTINCT FROM 1
                  AND MS.nlikes + MS.ndislikes >= :min_reactions
                  AND MS.lr_smoothed >= :min_smoothed
                  AND MS.nlikes::double precision / NULLIF(MS.nlikes + MS.ndislikes, 0)
                      >= :min_like_rate
                ORDER BY MS.lr_smoothed DESC, MS.nlikes DESC, A.id DESC
                LIMIT 100
            ), combined AS (
                SELECT * FROM liked
                UNION ALL
                SELECT * FROM fallback
            ), distinct_media AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY telegram_file_id
                    ORDER BY tier, reacted_at DESC NULLS LAST, quality DESC, id DESC
                ) AS media_rank
                FROM combined
            ), varied AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY tier, meme_source_id
                    ORDER BY reacted_at DESC NULLS LAST, quality DESC, id DESC
                ) AS source_rank
                FROM distinct_media
                WHERE media_rank = 1
            )
            SELECT id FROM varied
            ORDER BY tier, source_rank, reacted_at DESC NULLS LAST, quality DESC, id DESC
            LIMIT 5
            """
        ),
        {
            "user_id": user_id,
            "min_reactions": COLD_START_EXPLORE_MIN_EXPLICIT_REACTIONS,
            "min_smoothed": COLD_START_EXPLORE_MIN_LR_SMOOTHED,
            "min_like_rate": COLD_START_EXPLORE_MIN_RAW_LIKE_RATE,
        },
    )
    return [int(row["id"]) for row in rows]


async def seed_answers_as_reactions(pack_id: int, user_id: int) -> None:
    """Expose game answers to the recommender (like=1, pass=2, the feed's skip).

    Never overwrites existing reactions. The row keeps played memes out of the
    friend's own feed and counts toward per-user taste stats; meme and source
    stats (src/stats/meme.py, meme_source.py) filter the label out.
    """
    await execute(
        text(
            """
            INSERT INTO user_meme_reaction
                (user_id, meme_id, recommended_by, sent_at, reaction_id, reacted_at)
            SELECT A.user_id, I.meme_id, 'friend_challenge', A.answered_at,
                   CASE WHEN A.liked THEN 1 ELSE 2 END, A.answered_at
            FROM friend_challenge_answer A
            JOIN friend_challenge_item I ON I.pack_id = A.pack_id AND I.position = A.position
            WHERE A.pack_id = :pack_id AND A.user_id = :user_id AND I.meme_id IS NOT NULL
            ON CONFLICT (user_id, meme_id) DO NOTHING
            """
        ),
        {"pack_id": pack_id, "user_id": user_id},
    )


async def _get_pack(
    conn: AsyncConnection,
    *,
    pack_id: int | None = None,
    owner_id: int | None = None,
    token: str | None = None,
    lock: bool = False,
) -> dict[str, Any] | None:
    query = select(friend_challenge_pack)
    if pack_id is not None:
        query = query.where(friend_challenge_pack.c.id == pack_id)
    elif owner_id is not None:
        query = query.where(friend_challenge_pack.c.owner_id == owner_id)
    else:
        query = query.where(friend_challenge_pack.c.token == token)
    if lock:
        query = query.with_for_update()
    row = (await conn.execute(query)).mappings().first()
    if row is None:
        return None
    pack = dict(row)
    item_rows = await conn.execute(
        select(
            friend_challenge_item.c.position,
            friend_challenge_item.c.meme_id,
            meme.c.type,
            meme.c.telegram_file_id,
            meme.c.caption,
            meme.c.language_code,
            meme.c.status,
        )
        .select_from(friend_challenge_item.outerjoin(meme))
        .where(friend_challenge_item.c.pack_id == pack["id"])
        .order_by(friend_challenge_item.c.position)
    )
    pack["items"] = [dict(item) for item in item_rows.mappings()]
    return pack


def _is_available(pack: dict[str, Any]) -> bool:
    items = pack["items"]
    return [item["position"] for item in items] == list(range(1, PACK_SIZE + 1)) and all(
        item["meme_id"] is not None
        and item["status"] == MemeStatus.OK.value
        and item["telegram_file_id"]
        and item["type"] in {kind.value for kind in MemeType}
        for item in items
    )


async def get_or_create_owner_pack(owner_id: int, meme_ids: list[int]) -> dict[str, Any]:
    """Create five fixed slots atomically, or return the owner's existing pack."""
    if len(meme_ids) != PACK_SIZE or len(set(meme_ids)) != PACK_SIZE:
        raise ValueError("A friend challenge requires five distinct memes")

    async def create(conn: AsyncConnection) -> dict[str, Any]:
        existing = await _get_pack(conn, owner_id=owner_id)
        if existing is not None:
            return existing
        eligible = await conn.execute(
            select(meme.c.id)
            .where(
                meme.c.id.in_(meme_ids),
                meme.c.status == MemeStatus.OK.value,
                meme.c.telegram_file_id.is_not(None),
                meme.c.telegram_file_id != "",
                meme.c.type.in_([kind.value for kind in MemeType]),
            )
            .with_for_update(read=True)
        )
        if set(eligible.scalars()) != set(meme_ids):
            raise ValueError("A friend challenge contains unavailable memes")
        result = await conn.execute(
            insert(friend_challenge_pack)
            .values(owner_id=owner_id, token=secrets.token_urlsafe(18))
            .on_conflict_do_nothing(index_elements=[friend_challenge_pack.c.owner_id])
            .returning(friend_challenge_pack.c.id)
        )
        new_pack_id = result.scalar_one_or_none()
        if new_pack_id is not None:
            await conn.execute(
                insert(friend_challenge_item),
                [
                    {"pack_id": new_pack_id, "position": position, "meme_id": meme_id}
                    for position, meme_id in enumerate(meme_ids, 1)
                ],
            )
        return await _get_pack(conn, owner_id=owner_id)

    return await run_in_transaction(create)


async def get_pack(pack_id: int) -> dict[str, Any] | None:
    """Internal lookup including drafts. Callers enforce owner/confirmed access."""
    return await run_in_transaction(lambda conn: _get_pack(conn, pack_id=pack_id))


async def get_owner_pack(owner_id: int) -> dict[str, Any] | None:
    return await run_in_transaction(lambda conn: _get_pack(conn, owner_id=owner_id))


async def get_public_pack(token: str) -> dict[str, Any] | None:
    """Resolve only confirmed links."""
    pack = await run_in_transaction(lambda conn: _get_pack(conn, token=token))
    return pack if pack and pack["confirmed_at"] is not None else None


async def confirm_owner_pack(owner_id: int, pack_id: int) -> dict[str, Any] | None:
    """Publish this owner's five available items; repeated confirmation is inert."""

    async def confirm(conn: AsyncConnection) -> dict[str, Any] | None:
        pack = await _get_pack(conn, pack_id=pack_id, lock=True)
        if pack is None or pack["owner_id"] != owner_id or not _is_available(pack):
            return None
        if pack["confirmed_at"] is None:
            await conn.execute(
                friend_challenge_pack.update()
                .where(friend_challenge_pack.c.id == pack_id)
                .values(confirmed_at=func.now())
            )
            pack = await _get_pack(conn, pack_id=pack_id)
        return pack

    return await run_in_transaction(confirm)


async def _get_progress(
    conn: AsyncConnection, pack_id: int, user_id: int, *, lock: bool = False
) -> dict[str, Any] | None:
    query = (
        select(friend_challenge_participation)
        .join(friend_challenge_pack)
        .where(
            friend_challenge_participation.c.pack_id == pack_id,
            friend_challenge_participation.c.user_id == user_id,
            friend_challenge_pack.c.confirmed_at.is_not(None),
            friend_challenge_pack.c.owner_id != user_id,
        )
    )
    if lock:
        query = query.with_for_update(of=friend_challenge_participation)
    row = (await conn.execute(query)).mappings().first()
    if row is None:
        return None
    progress = dict(row)
    result = await conn.execute(
        select(friend_challenge_answer.c.position, friend_challenge_answer.c.liked)
        .where(
            friend_challenge_answer.c.pack_id == pack_id,
            friend_challenge_answer.c.user_id == user_id,
        )
        .order_by(friend_challenge_answer.c.position)
    )
    answers = [dict(answer) for answer in result.mappings()]
    answered = {answer["position"] for answer in answers}
    progress.update(
        answered_count=len(answers),
        liked_count=sum(answer["liked"] for answer in answers),
        next_position=next((p for p in range(1, PACK_SIZE + 1) if p not in answered), None),
    )
    return progress


async def start_participation(pack_id: int, user_id: int) -> dict[str, Any] | None:
    """Start or resume a confirmed, available pack; never resets progress."""

    async def start(conn: AsyncConnection) -> dict[str, Any] | None:
        pack = await _get_pack(conn, pack_id=pack_id)
        if (
            pack is None
            or pack["confirmed_at"] is None
            or pack["owner_id"] == user_id
            or not _is_available(pack)
        ):
            return None
        await conn.execute(
            insert(friend_challenge_participation)
            .values(pack_id=pack_id, user_id=user_id)
            .on_conflict_do_nothing()
        )
        return await _get_progress(conn, pack_id, user_id)

    return await run_in_transaction(start)


async def get_progress(pack_id: int, user_id: int) -> dict[str, Any] | None:
    return await run_in_transaction(lambda conn: _get_progress(conn, pack_id, user_id))


async def record_answer(pack_id: int, user_id: int, position: int, liked: bool) -> dict[str, Any]:
    """First answer wins; only the current position can advance."""

    async def record(conn: AsyncConnection) -> dict[str, Any]:
        progress = await _get_progress(conn, pack_id, user_id, lock=True)
        if progress is None or position != progress["next_position"]:
            return {"changed": False, "progress": progress}
        await conn.execute(
            insert(friend_challenge_answer).values(
                pack_id=pack_id, user_id=user_id, position=position, liked=liked
            )
        )
        if progress["answered_count"] + 1 == PACK_SIZE:
            await conn.execute(
                friend_challenge_participation.update()
                .where(
                    friend_challenge_participation.c.pack_id == pack_id,
                    friend_challenge_participation.c.user_id == user_id,
                )
                .values(completed_at=func.now())
            )
        return {"changed": True, "progress": await _get_progress(conn, pack_id, user_id)}

    return await run_in_transaction(record)
