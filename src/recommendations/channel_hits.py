"""A bounded channel-hit experiment; Telegram checks never run in the feed path."""

import asyncio
import json
import logging
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src import redis
from src.config import settings
from src.database import fetch_all, fetch_one
from src.storage.schemas import MemeData
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_CHAT_ID, TELEGRAM_CHANNEL_RU_CHAT_ID

logger = logging.getLogger(__name__)
EXPERIMENT_ID = "channel_hits_v1"
RECOMMENDED_BY = "channel_hit_v1"
POOL_KEY = "channel_hits:v1:pool"
COHORT_KEY = "channel_hits:v1:treatment_users"
CHANNEL_CHAT_IDS = {
    "tgchannelru": TELEGRAM_CHANNEL_RU_CHAT_ID,
    "tgchannelen": TELEGRAM_CHANNEL_EN_CHAT_ID,
}

LABELS_SQL = """
SELECT cp.channel, cp.meme_id AS id, cp.created_at AS posted_at,
       ss.views, ss.forwards
FROM crossposting cp JOIN meme m ON m.id = cp.meme_id
JOIN LATERAL (
    SELECT s.views, s.forwards
    FROM crossposting_snapshots s
    WHERE s.channel = cp.channel AND s.meme_id = cp.meme_id
      AND s.telegram_message_id = cp.telegram_message_id
      AND s.snapshot_at BETWEEN cp.created_at + interval '20 hours'
                            AND cp.created_at + interval '36 hours'
      AND s.views >= 50 AND s.forwards >= 0
    ORDER BY abs(extract(epoch FROM s.snapshot_at -
                        (cp.created_at + interval '24 hours'))), s.snapshot_at
    LIMIT 1
) ss ON TRUE
WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
  AND cp.created_at >= CAST(:as_of AS timestamp) - interval '120 days'
  AND cp.created_at < CAST(:as_of AS timestamp) - interval '36 hours'
  AND m.type = 'image' AND coalesce(cp.score_version, 1) <> 0
"""


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def score_channel_hits(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """P75 supply gate, one typical post of shrinkage, comparable channel ranks.

    This is a ranking heuristic, not a confidence interval: Telegram views and
    forwards are neither unique people nor independent Bernoulli trials.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in labels:
        if row["channel"] in CHANNEL_CHAT_IDS and row["views"] >= 50 and row["forwards"] >= 0:
            groups[row["channel"]].append(dict(row))
    pool = []
    for channel, rows in groups.items():
        if len(rows) < 20:
            continue
        prior_views = statistics.median(row["views"] for row in rows)
        prior_rate = sum(row["forwards"] for row in rows) / sum(row["views"] for row in rows)
        cutoff = _percentile([row["forwards"] / row["views"] for row in rows], 0.75)
        for row in rows:
            row["raw_rate"] = row["forwards"] / row["views"]
            row["smoothed_rate"] = (row["forwards"] + prior_views * prior_rate) / (
                row["views"] + prior_views
            )
        scores = sorted(row["smoothed_rate"] for row in rows)
        for row in rows:
            if row["raw_rate"] < cutoff or row["forwards"] == 0:
                continue
            # Average rank prevents arbitrary ordering of equal one-forward posts.
            below = sum(score < row["smoothed_rate"] for score in scores)
            equal = sum(score == row["smoothed_rate"] for score in scores)
            row.update(
                channel=channel,
                percentile=(below + (equal - 1) / 2) / (len(scores) - 1),
                prior_views=prior_views,
                prior_rate=prior_rate,
                raw_p75=cutoff,
            )
            row["posted_at"] = row["posted_at"].isoformat()
            pool.append(row)
    return pool


async def refresh_channel_hit_pool() -> list[dict[str, Any]]:
    """Called by the background worker or enrollment preview, never by a swipe."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    labels = await fetch_all(text(LABELS_SQL), {"as_of": now})
    pool = score_channel_hits(labels)
    cohort = await fetch_all(
        text("""
        SELECT user_id FROM experiment_assignment
        WHERE experiment_id = :experiment_id AND variant = 'treatment'
          AND CAST(assignment_metadata->>'exposure_end_at' AS timestamptz) > NOW()
    """),
        {"experiment_id": EXPERIMENT_ID},
    )
    async with redis.redis_client.pipeline(transaction=True) as pipe:
        pipe.set(POOL_KEY, json.dumps(pool), ex=3600)
        pipe.set(COHORT_KEY, json.dumps([row["user_id"] for row in cohort]), ex=3600)
        await pipe.execute()
    return pool


async def run_channel_hit_refresh_worker() -> None:
    while True:
        try:
            # Keep this lease until expiry: concurrent app workers share one refresh.
            if await redis.redis_client.set("channel_hits:v1:refresh", "1", nx=True, ex=600):
                await asyncio.wait_for(refresh_channel_hit_pool(), timeout=60)
        except Exception:
            logger.warning("Channel-hit pool refresh failed", exc_info=True)
        await asyncio.sleep(300)


ELIGIBLE_SQL = """
WITH RECURSIVE candidates AS (
    SELECT * FROM jsonb_to_recordset(CAST(:pool AS jsonb))
        AS p(id integer, percentile float, posted_at timestamp)
), family(root, id) AS (
    SELECT DISTINCT id, id FROM candidates
    UNION
    SELECT f.root, m.id FROM family f JOIN meme m ON m.duplicate_of = f.id
), seen_roots AS MATERIALIZED (
    SELECT DISTINCT f.root
    FROM family f JOIN user_meme_reaction r ON r.meme_id = f.id
    WHERE r.user_id = :user_id
), blocked_roots AS MATERIALIZED (
    SELECT DISTINCT f.root
    FROM family f JOIN crossposting cp ON cp.meme_id = f.id
    LEFT JOIN user_channel_membership cm
      ON cm.user_id = :user_id AND cm.chat_id = CASE cp.channel
        WHEN 'tgchannelru' THEN CAST(:ru_chat_id AS bigint)
        ELSE CAST(:en_chat_id AS bigint) END
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
      AND (cm.status IS DISTINCT FROM 'nonmember' OR cm.ever_member
           OR cm.observed_at IS NULL
           OR cm.observed_at < (NOW() AT TIME ZONE 'UTC') - interval '24 hours'
           OR EXISTS (
             SELECT 1 FROM user_tg_chat_membership old
             WHERE old.user_tg_id = :user_id AND old.chat_id = cm.chat_id
           ))
), root_publications AS MATERIALIZED (
    SELECT DISTINCT cp.meme_id
    FROM candidates p JOIN crossposting cp ON cp.meme_id = p.id
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
), scored AS (
    SELECT m.id, m.type, m.telegram_file_id, m.caption, m.language_code,
           :recommended_by AS recommended_by, coalesce(ms.nlikes, 0) AS nlikes,
           max(p.percentile) * (
             0.5 + coalesce((umss.nlikes + 1.0) /
                            nullif(umss.nlikes + umss.ndislikes + 2.0, 0), 0.5)
           ) AS personal_score,
           max(p.posted_at) AS posted_at
    FROM candidates p JOIN meme m ON m.id = p.id
    JOIN root_publications rp ON rp.meme_id = m.id
    JOIN user_language ul ON ul.user_id = :user_id AND ul.language_code = m.language_code
    LEFT JOIN meme_stats ms ON ms.meme_id = m.id
    LEFT JOIN user_meme_source_stats umss
      ON umss.user_id = :user_id AND umss.meme_source_id = m.meme_source_id
    LEFT JOIN seen_roots seen ON seen.root = m.id
    LEFT JOIN blocked_roots blocked ON blocked.root = m.id
    WHERE m.status = 'published' AND m.duplicate_of IS NULL
      AND m.telegram_file_id IS NOT NULL
      AND NOT (m.id = ANY(CAST(:excluded AS integer[])))
      AND seen.root IS NULL AND blocked.root IS NULL
    GROUP BY m.id, ms.nlikes, umss.nlikes, umss.ndislikes
)
SELECT * FROM scored
ORDER BY personal_score DESC, posted_at DESC, id
LIMIT :limit
"""


async def eligible_channel_hits(
    user_id: int,
    limit: int = 1,
    exclude_meme_ids: list[int] | None = None,
    *,
    only_meme_id: int | None = None,
) -> list[dict[str, Any]]:
    payload = await redis.redis_client.get(POOL_KEY)
    if not payload:
        return []
    pool = json.loads(payload)
    if only_meme_id is not None:
        pool = [row for row in pool if row["id"] == only_meme_id]
    if not pool:
        return []
    return await fetch_all(
        text(ELIGIBLE_SQL),
        {
            "pool": json.dumps(pool),
            "user_id": user_id,
            "excluded": exclude_meme_ids or [],
            "recommended_by": RECOMMENDED_BY,
            "ru_chat_id": TELEGRAM_CHANNEL_RU_CHAT_ID,
            "en_chat_id": TELEGRAM_CHANNEL_EN_CHAT_ID,
            "limit": min(max(limit, 0), 400),
        },
    )


DAILY_OPPORTUNITY_SQL = """
WITH sends AS (
    SELECT sent_at, recommended_by,
           lag(sent_at) OVER (ORDER BY sent_at) AS previous_sent_at
    FROM user_meme_reaction
    WHERE user_id = :user_id AND sent_at >= :day_start
      AND coalesce(recommended_by, '') NOT LIKE 'broadcast%'
      AND coalesce(recommended_by, '')
          NOT IN ('share_link', 'last', 'uploaded_meme', 'friend_challenge')
), activity AS (
    SELECT count(*) AS sent, max(sent_at) AS last_sent,
           count(*) FILTER (WHERE recommended_by = :recommended_by) AS hits,
           count(*) FILTER (WHERE sent_at - previous_sent_at > interval '30 minutes') AS gaps
    FROM sends
)
SELECT ea.variant
FROM experiment_assignment ea JOIN "user" u ON u.id = ea.user_id CROSS JOIN activity a
WHERE ea.user_id = :user_id AND ea.experiment_id = :experiment_id
  AND u.type = 'user' AND u.blocked_bot_at IS NULL
  AND CAST(ea.assignment_metadata->>'experiment_start_at' AS timestamptz) <= NOW()
  AND CAST(ea.assignment_metadata->>'exposure_end_at' AS timestamptz) > NOW()
  AND a.sent < 5 AND a.hits = 0 AND a.gaps = 0
  AND (a.last_sent IS NULL
       OR a.last_sent >= (NOW() AT TIME ZONE 'UTC') - interval '30 minutes')
"""


async def maybe_get_channel_hit(
    user_id: int, *, exclude_meme_ids: list[int] | None = None
) -> MemeData | None:
    if not settings.CHANNEL_HITS_ENABLED:
        return None
    try:
        now = datetime.now(timezone.utc)
        key = f"channel_hits:v1:day:{now.date()}:{user_id}"
        reserved, cohort = await redis.redis_client.mget([key, COHORT_KEY])
        if reserved or not cohort or user_id not in json.loads(cohort):
            return None
        row = await fetch_one(
            text(DAILY_OPPORTUNITY_SQL),
            {
                "user_id": user_id,
                "day_start": now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None),
                "recommended_by": RECOMMENDED_BY,
                "experiment_id": EXPERIMENT_ID,
            },
        )
        if not row or row["variant"] != "treatment":
            return None
        candidates = await eligible_channel_hits(user_id, exclude_meme_ids=exclude_meme_ids)
        if not candidates:
            return None
        ttl = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
        if not await redis.redis_client.set(key, "reserved", nx=True, ex=ttl):
            return None
        # Reserve before Telegram; an ambiguous network result must not cause retries.
        return MemeData(**candidates[0])
    except Exception:
        logger.warning("Channel-hit slot unavailable; using regular feed", exc_info=True)
        return None


async def channel_hit_is_sendable(user_id: int, meme_id: int) -> bool:
    if not settings.CHANNEL_HITS_ENABLED:
        return False
    try:
        return bool(await eligible_channel_hits(user_id, only_meme_id=meme_id))
    except Exception:
        logger.warning("Channel-hit delivery check failed", exc_info=True)
        return False
