import heapq
import logging
import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.config import settings
from src.crossposting.constants import Channel
from src.crossposting.model import Model, add_zf, features, load_model, source_prior
from src.crossposting.scoring import (
    AB_ARMS,
    CHANNEL_PARAMS,
    LIVE,
    MODEL_SCORE_VERSION,
    PRESELECT,
    SCORE_VERSION,
    SCORES,
    score,
    score_all,
)
from src.database import (
    crossposting,
    crossposting_decision_log,
    execute,
    fetch_all,
    fetch_one,
)

logger = logging.getLogger(__name__)


async def log_meme_sent(
    meme_id: int,
    channel: Channel,
    telegram_message_id: int | None = None,
    caption_text: str | None = None,
    score_version: int = 1,
) -> None:
    # ON CONFLICT DO NOTHING: rewrite-on-repost would corrupt source-quality
    # measurements (drop the original mature sample out of the [30d, 48h]
    # window and overwrite its views/forwards with the reward post's stats).
    # Reward reposts of already-crossposted memes therefore don't refresh
    # the diversity cap — acceptable since rewards run weekly.
    insert_statement = (
        insert(crossposting)
        .values(
            meme_id=meme_id,
            channel=channel.value,
            telegram_message_id=telegram_message_id,
            caption_text=caption_text,
            score_version=score_version,
        )
        .on_conflict_do_nothing()
    )

    await execute(insert_statement)


# Scheduled slots are >= 2h apart; a newer post means late runs are catching up.
CATCH_UP_GAP_MINUTES = 60


async def posted_recently(channel: Channel, minutes: int = CATCH_UP_GAP_MINUTES) -> bool:
    """True if this channel got a post within ``minutes`` (stops catch-up bursts)."""
    row = await fetch_one(
        text(
            """
            SELECT 1 FROM crossposting
            WHERE channel = :channel
              AND created_at > NOW() - make_interval(mins => :minutes)
              -- weekly reward albums (REWARD_ALBUM_SCORE_VERSION = 0) are not ranked slots
              AND score_version IS DISTINCT FROM 0
            LIMIT 1
            """
        ),
        {"channel": channel.value, "minutes": minutes},
    )
    return row is not None


# Shadow inputs for the top-N, one bounded query per decision (~1.3s on prod).
# Labels: zf = ln(1+forwards) - channel×MSK-week mean over image posts 48h..365d old.
# ``crossposting.forwards`` is the latest Telethon snapshot (frozen once the post
# leaves the 30d sweep) — the same field the 2026-10-30 study used, not a 24h snapshot.
# theta_src: Beta(hits + 4·p̄, misses + 4·(1−p̄)) posterior mean / p̄, clip 0.5–2,
#   hit = top quartile of ln(1+forwards) within its week.
# user_taste_z: user weight w = Σ zf of liked posts (liked before the post) / (n + 20);
#   meme taste = Σ w of its likers / n_likes / stddev(w).
# src_fwd_pct: PERCENT_RANK of forwards/views among the source's posts with a
#   Telethon read in the last 30d (meme_raw_telegram.stats_fetched_at); NULL when
#   the post has no read or the source has < 10 reference posts.
# ponytail: likes limited to sent_at > now()-90d — user_meme_reaction has no valid
#   meme_id-leading index on prod, so this window keeps the scan bounded. Widen it
#   (or precompute weights) if user coverage proves too thin.
_SHADOW_INPUTS_QUERY = """
    WITH posts AS MATERIALIZED (
        SELECT cp.meme_id, cp.created_at, m.meme_source_id AS src,
               LN(1 + cp.forwards) AS lfw,
               date_trunc('week', cp.created_at + INTERVAL '3 hours') AS wk
        FROM crossposting cp
        JOIN meme m ON m.id = cp.meme_id
        WHERE cp.channel = :channel
          AND cp.telegram_message_id IS NOT NULL
          AND cp.views > 0
          AND cp.forwards IS NOT NULL
          AND m.type = 'image'
          AND cp.created_at < NOW() - INTERVAL '48 hours'
          AND cp.created_at > NOW() - INTERVAL '365 days'
    ),
    weeks AS (
        SELECT wk, AVG(lfw) AS mu,
               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY lfw) AS q75
        FROM posts GROUP BY wk
    ),
    labeled AS MATERIALIZED (
        SELECT p.meme_id, p.created_at, p.src,
               p.lfw - w.mu AS zf, (p.lfw >= w.q75)::int AS hit
        FROM posts p JOIN weeks w USING (wk)
    ),
    pbar AS (SELECT AVG(hit) AS p FROM labeled),
    src AS (SELECT src, SUM(hit) AS h, COUNT(*) AS n FROM labeled GROUP BY src),
    likes AS MATERIALIZED (
        SELECT r.meme_id, r.user_id, r.reacted_at
        FROM user_meme_reaction r
        WHERE r.sent_at > NOW() - INTERVAL '90 days'
          AND r.reaction_id = 1
    ),
    users AS MATERIALIZED (
        SELECT lk.user_id, SUM(l.zf) / (COUNT(*) + 20) AS w
        FROM labeled l
        JOIN likes lk ON lk.meme_id = l.meme_id AND lk.reacted_at < l.created_at
        GROUP BY lk.user_id
    ),
    wsd AS (SELECT NULLIF(STDDEV_POP(w), 0) AS sd FROM users),
    src_fwd AS (
        SELECT r.id, r.meme_source_id,
               PERCENT_RANK() OVER w AS pct, COUNT(*) OVER w AS n_ref
        FROM meme_raw_telegram r
        WHERE r.meme_source_id IN (SELECT meme_source_id FROM meme WHERE id = ANY(:meme_ids))
          AND r.stats_fetched_at > NOW() - INTERVAL '30 days'
          AND r.forwards IS NOT NULL
          AND r.views > 0
        WINDOW w AS (PARTITION BY r.meme_source_id ORDER BY r.forwards::float / r.views
                     ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
    ),
    taste AS (
        SELECT lk.meme_id, COUNT(*) AS n_likes, SUM(COALESCE(u.w, 0)) AS wsum
        FROM likes lk LEFT JOIN users u USING (user_id)
        WHERE lk.meme_id = ANY(:meme_ids)
        GROUP BY lk.meme_id
    )
    SELECT m.id AS meme_id,
           LEAST(2.0, GREATEST(0.5,
               (COALESCE(s.h, 0) + 4 * pbar.p) / (COALESCE(s.n, 0) + 4) / pbar.p
           ))::float AS theta_src,
           COALESCE(t.wsum / GREATEST(t.n_likes, 1) / wsd.sd, 0)::float AS user_taste_z,
           -- Describe Memes content tags (null for memes described before 2026-10-31)
           m.ocr_result->>'format' AS content_format,
           CASE WHEN jsonb_typeof(m.ocr_result->'relatable') = 'boolean'
                THEN (m.ocr_result->>'relatable')::boolean END AS relatable,
           CASE WHEN jsonb_typeof(m.ocr_result->'politics_news') = 'boolean'
                THEN (m.ocr_result->>'politics_news')::boolean END AS politics_news,
           CASE WHEN sf.n_ref >= 10 THEN sf.pct END::float AS src_fwd_pct,
           share_clicks.pre_inbot_share_clicks,
           share_clicks.pre_inbot_share_click_users
    FROM meme m
    CROSS JOIN pbar CROSS JOIN wsd
    LEFT JOIN src s ON s.src = m.meme_source_id
    LEFT JOIN taste t ON t.meme_id = m.id
    LEFT JOIN src_fwd sf ON sf.id = m.raw_meme_id AND sf.meme_source_id = m.meme_source_id
    -- in-bot share-link clicks by non-sharers before this decision
    CROSS JOIN LATERAL (
        SELECT
            COUNT(*) AS pre_inbot_share_clicks,
            COUNT(DISTINCT user_id) AS pre_inbot_share_click_users
        FROM user_deep_link_log udll
        CROSS JOIN LATERAL (
            SELECT substring(
                udll.deep_link FROM ('^[ms]_([1-9][0-9]{0,18})_' || m.id || '$')
            ) AS sharer_id
        ) share_link
        WHERE udll.created_at < NOW()
          AND CASE
              WHEN share_link.sharer_id IS NULL THEN false
              WHEN length(share_link.sharer_id) = 19
                AND share_link.sharer_id > '9223372036854775807' THEN false
              ELSE udll.user_id <> share_link.sharer_id::bigint
          END
    ) share_clicks
    WHERE m.id = ANY(:meme_ids)
"""


async def _attach_shadow_inputs(candidates: list[dict[str, Any]], channel: str) -> None:
    """Attach v5/v5c/v5f inputs + share-click counts to the top-N in place."""
    meme_ids = [int(c["id"]) for c in candidates]
    rows = await fetch_all(text(_SHADOW_INPUTS_QUERY), {"channel": channel, "meme_ids": meme_ids})
    by_id = {int(r["meme_id"]): r for r in rows}
    for c in candidates:
        r = by_id.get(int(c["id"]))
        if r is not None:
            c["theta_src"] = round(float(r["theta_src"]), 4)
            c["user_taste_z"] = round(float(r["user_taste_z"]), 4)
            c["content_format"] = r["content_format"]
            c["relatable"] = r["relatable"]
            c["politics_news"] = r["politics_news"]
            pct = r["src_fwd_pct"]
            c["src_fwd_pct"] = round(float(pct), 4) if pct is not None else None
            c["pre_inbot_share_clicks"] = r["pre_inbot_share_clicks"]
            c["pre_inbot_share_click_users"] = r["pre_inbot_share_click_users"]


# zf_24h labels: forwards at the snapshot nearest +24h (20-36h window), ranked image posts.
# Shared by posting (source prior), the nightly refit and the daily digest.
_LABELS_QUERY = """
    SELECT cp.meme_id, m.meme_source_id AS source_id, cp.created_at AS posted_at,
           cp.telegram_message_id, s.forwards AS f24
    FROM crossposting cp
    JOIN meme m ON m.id = cp.meme_id
    JOIN LATERAL (
        SELECT s.forwards
        FROM crossposting_snapshots s
        WHERE s.channel = cp.channel
          AND s.telegram_message_id = cp.telegram_message_id
          AND s.snapshot_at BETWEEN cp.created_at + INTERVAL '20 hours'
                                AND cp.created_at + INTERVAL '36 hours'
          AND s.views > 0
          AND s.forwards IS NOT NULL
        ORDER BY ABS(EXTRACT(EPOCH FROM s.snapshot_at - cp.created_at) - 86400)
        LIMIT 1
    ) s ON true
    WHERE cp.channel = :channel
      AND cp.telegram_message_id IS NOT NULL
      AND cp.score_version NOT IN (0, 1)  -- reward albums, unranked/default posts
      AND m.type = 'image'
      AND cp.created_at >= :since
      AND cp.created_at < :until
"""


async def fetch_labels(
    channel: str, since: datetime = datetime(2000, 1, 1), until: datetime = datetime(2100, 1, 1)
) -> list[dict[str, Any]]:
    """Labeled posts of ``channel`` with zf (week means over the fetched range)."""
    params = {"channel": channel, "since": since, "until": until}
    return add_zf(await fetch_all(text(_LABELS_QUERY), params))


# Model inputs that do not depend on decision time: user upload, and the source post's views
# percentile among its source's posts within ±45 days (NULL without a Telegram post or with
# < 10 reference posts). The same query serves posting and the nightly refit.
_MODEL_STATIC_QUERY = """
    SELECT m.id AS meme_id, (ms.type = 'user upload') AS is_upload, v.pct AS src_views_pct
    FROM meme m
    JOIN meme_source ms ON ms.id = m.meme_source_id
    LEFT JOIN meme_raw_telegram r
        ON r.id = m.raw_meme_id AND r.meme_source_id = m.meme_source_id
    LEFT JOIN LATERAL (
        SELECT (COUNT(*) FILTER (WHERE o.views < r.views)
                + 0.5 * COUNT(*) FILTER (WHERE o.views = r.views))::float / COUNT(*) AS pct,
               COUNT(*) AS n
        FROM meme_raw_telegram o
        WHERE o.meme_source_id = r.meme_source_id
          AND o.views > 0
          AND o.date BETWEEN r.date - INTERVAL '45 days' AND r.date + INTERVAL '45 days'
    ) v ON r.views > 0 AND v.n >= 10
    WHERE m.id = ANY(:meme_ids)
"""


async def fetch_model_static_inputs(meme_ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = await fetch_all(text(_MODEL_STATIC_QUERY), {"meme_ids": meme_ids})
    return {
        int(r["meme_id"]): {
            "is_upload": bool(r["is_upload"]),
            "src_views_pct": _round(r["src_views_pct"], 4),
        }
        for r in rows
    }


async def _attach_model_inputs(candidates: list[dict[str, Any]], channel: str) -> None:
    """Attach model.MODEL_INPUTS to the top-N in place."""
    static = await fetch_model_static_inputs([int(c["id"]) for c in candidates])
    now = datetime.now(UTC).replace(tzinfo=None)
    # 190d: the prior reads 180d back; whole MSK weeks keep its zf equal to the refit's.
    labels = await fetch_labels(channel, since=now - timedelta(days=190))
    for c in candidates:
        if int(c["id"]) in static:
            c.update(static[int(c["id"])])
            c["src_prior_z"], c["src_prior_n"] = source_prior(labels, c["meme_source_id"], now)


async def get_active_model(channel: str) -> Model | None:
    """Active crossposting_model row, validated (raises when it is unusable)."""
    row = await fetch_one(
        text("SELECT * FROM crossposting_model WHERE channel = :channel AND is_active"),
        {"channel": channel},
    )
    return None if row is None else load_model(row)


async def log_ranker_decision(
    channel: str,
    picked_meme_id: int | None,
    score_version: int,
    median_signal: float | None,
    pool_size: int | None,
    candidates: list[dict[str, Any]],
    policy: str | None = None,
    top_n: int | None = None,
    explore_eps: float | None = None,
    model_version: int | None = None,
) -> None:
    """Insert one row into crossposting_decision_log. Failures must be wrapped
    in try/except by the caller (logging miss << duplicate album publish).
    """
    insert_stmt = insert(crossposting_decision_log).values(
        channel=channel,
        picked_meme_id=picked_meme_id,
        score_version=score_version,
        median_signal=median_signal,
        candidate_pool_size=pool_size,
        candidates=candidates,
        policy=policy,
        top_n=top_n,
        explore_eps=explore_eps,
        model_version=model_version,
    )
    await execute(insert_stmt)


# Columns exposed for MemeData construction. Keep narrow — adding fields here
# would require matching changes in src/storage/schemas.py:MemeData.
_PICKED_FIELDS = ("id", "type", "telegram_file_id", "caption")


async def _picked_meme_dict(meme_id: int) -> dict[str, Any]:
    row = await fetch_one(
        text(f"SELECT {', '.join(_PICKED_FIELDS)} FROM meme WHERE id = :id"), {"id": meme_id}
    )
    return dict(row)


# Eligible pool, unordered: ranking lives in scoring.py.
_POOL_QUERY = """
    WITH src_quality AS (
        SELECT
            m.meme_source_id,
            AVG(cp.forwards * SQRT(GREATEST(cp.views, 1) / 100.0)) AS signal
        FROM crossposting cp
        JOIN meme m ON m.id = cp.meme_id
        WHERE cp.channel = :channel
          AND cp.created_at > NOW() - INTERVAL '30 days'
          AND cp.created_at < NOW() - INTERVAL '48 hours'
          AND cp.views IS NOT NULL
          AND cp.views > 0
          AND m.type = 'image'
        GROUP BY m.meme_source_id
        HAVING COUNT(*) >= 5
    ),
    src_median AS (
        SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY signal) AS m_signal
        FROM src_quality
    ),
    recent_src AS (
        SELECT DISTINCT m2.meme_source_id
        FROM crossposting cp2
        JOIN meme m2 ON m2.id = cp2.meme_id
        WHERE cp2.channel = :channel
          AND cp2.created_at > NOW() - INTERVAL '24 hours'
          AND cp2.telegram_message_id IS NOT NULL
    )
    SELECT
        -- Scoring columns only: the pool is ~130k rows; picked fields load by id.
        M.id, M.meme_source_id, (M.caption IS NOT NULL) AS has_caption,
        MS.nlikes, MS.ndislikes, MS.raw_impr_rank,
        MS.age_days, MS.nmemes_sent, MS.invited_count,
        SQ.signal AS src_signal,
        (SELECT m_signal FROM src_median) AS median_signal
    FROM meme M
    INNER JOIN meme_stats MS ON MS.meme_id = M.id
    LEFT JOIN crossposting CP ON CP.meme_id = M.id AND CP.channel = :channel
    LEFT JOIN src_quality SQ ON SQ.meme_source_id = M.meme_source_id
    WHERE CP.meme_id IS NULL
      AND M.status = 'ok'
      AND M.language_code = :language_code
      AND M.type = 'image'
      AND MS.nlikes >= 5
      AND M.meme_source_id NOT IN (SELECT meme_source_id FROM recent_src)
"""

# Random pool memes outside the top-N preselect, logged and drawable for exploration.
POOL_SAMPLE = 5

# Flat per-candidate keys still read by docs/analyst/crossposting-*.sql readouts.
_LEGACY_SHADOWS = ("v5", "v5c", "v5f")


def _round(x: float | None, nd: int) -> float | None:
    return None if x is None else round(float(x), nd)


def _model_preds(model: Model | None, top: list[dict[str, Any]]) -> list[float] | None:
    if model is None:
        return None
    try:
        xs = [features(r) for r in top]
        preds = None if None in xs else [model.predict(x) for x in xs]
    except Exception:
        logger.warning("crosspost model v%s scoring failed", model.version, exc_info=True)
        preds = None
    if preds is None or not all(map(math.isfinite, preds)):
        logger.warning("crosspost model v%s cannot score these inputs; using score", model.version)
        return None
    return preds


def _build_decision_log(
    channel: str,
    top: list[dict[str, Any]],
    pool_size: int,
    live: str,
    pre: str,
    model: Model | None = None,
    top_n: int = 1,
    explore_eps: float = 0.0,
    rng: Any = random,
) -> dict[str, Any]:
    """Score the logged candidates with every score; return log_ranker_decision kwargs.

    The policy ranks all K candidates by ``model`` (else the live score), then draws
    uniformly from all K with probability ``explore_eps``, else from its first ``top_n``.
    Each candidate logs its policy rank and selection probability (they sum to 1).
    """
    scored = [score_all(r, channel) for r in top]
    picks: dict[str, int] = {}
    ranks: list[dict[str, int]] = [{} for _ in top]
    for name in SCORES:
        vals = [s[name] for _, s in scored]
        if None in vals:
            continue
        order = sorted(range(len(top)), key=lambda i: (-vals[i], top[i]["id"]))
        for rank, i in enumerate(order, start=1):
            ranks[i][name] = rank
        picks[name] = top[order[0]]["id"]
    # LIVE may need shadow inputs; if they failed to load, fall back to PRESELECT.
    picked_by = live if live in picks else pre
    preds = _model_preds(model, top)
    key = preds if preds is not None else [s[picked_by] for _, s in scored]
    order = sorted(range(len(top)), key=lambda i: (-key[i], top[i]["id"]))
    policy_rank = {i: rank for rank, i in enumerate(order, start=1)}
    k, n = len(top), max(1, min(top_n, len(top)))
    explore_eps = min(max(float(explore_eps), 0.0), 1.0)
    drawn = top[order[rng.randrange(k) if rng.random() < explore_eps else rng.randrange(n)]]

    log_candidates = []
    for i, (row, (factors, scores)) in enumerate(zip(top, scored, strict=True)):
        factors = {k: _round(v, 4) for k, v in factors.items()}
        scores = {k: _round(v, 6) for k, v in scores.items()}
        log_candidates.append(
            {
                "rank": None if row.get("pool_sample") else i + 1,  # PRESELECT order
                "pool_sample": bool(row.get("pool_sample")),
                "meme_id": row["id"],
                "source_id": row.get("meme_source_id"),
                "nlikes": row.get("nlikes"),
                "ndislikes": row.get("ndislikes"),
                "raw_impr_rank": row.get("raw_impr_rank"),
                "age_days": row.get("age_days"),
                "nmemes_sent": row.get("nmemes_sent"),
                "invited_count": row.get("invited_count"),
                "pre_inbot_share_clicks": row.get("pre_inbot_share_clicks") or 0,
                "pre_inbot_share_click_users": row.get("pre_inbot_share_click_users") or 0,
                "caption_present": bool(row.get("has_caption")),
                "src_signal": _round(row.get("src_signal"), 4),
                "theta_src": row.get("theta_src"),
                "user_taste_z": row.get("user_taste_z"),
                "content_format": row.get("content_format"),
                "relatable": row.get("relatable"),
                "politics_news": row.get("politics_news"),
                "src_fwd_pct": row.get("src_fwd_pct"),
                "is_upload": row.get("is_upload"),
                "src_views_pct": row.get("src_views_pct"),
                "src_prior_z": _round(row.get("src_prior_z"), 4),
                "src_prior_n": row.get("src_prior_n"),
                "model_pred": _round(preds[i], 4) if preds else None,
                "policy_rank": policy_rank[i],
                "propensity": (1 - explore_eps) / n * (policy_rank[i] <= n) + explore_eps / k,
                "factors": factors,
                "scores": scores,
                "ranks": ranks[i],
                "picks": picks,
                "picked_by": picked_by,
                # legacy flat keys (the only shape on rows before this refactor)
                **factors,
                "final_score": scores[picked_by],
                "like_volume_enabled": "like_volume_factor" in SCORES[picked_by],
                **{f"score_{n}": scores[n] for n in _LEGACY_SHADOWS},
                **{f"shadow_{n}_rank": ranks[i][n] for n in _LEGACY_SHADOWS if n in picks},
                **{f"shadow_{n}_pick_meme_id": picks[n] for n in _LEGACY_SHADOWS if n in picks},
            }
        )

    return {
        "channel": channel,
        "picked_meme_id": drawn["id"],
        "score_version": MODEL_SCORE_VERSION if preds else SCORE_VERSION[picked_by],
        "median_signal": _round(top[0].get("median_signal"), 4),
        "pool_size": pool_size,
        "candidates": log_candidates,
        "policy": "model_topN_v1" if preds else "score_topN_v1",
        "top_n": n,
        "explore_eps": explore_eps,
        "model_version": model.version if preds else None,
    }


async def get_next_meme_for_channel(
    channel: str, log_top_n: int = 20
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Pick the crosspost meme for ``channel`` (tgchannelru / tgchannelen).

    Returns ``(picked_meme, decision_log)``: ``picked_meme`` is a narrow dict for
    ``MemeData(**...)``; ``decision_log`` is kwargs for ``log_ranker_decision``
    (its ``score_version`` is also what ``log_meme_sent`` records).
    Both ``None`` when no candidate passes the filters.
    """
    params = {"channel": channel, "language_code": CHANNEL_PARAMS[channel]["language_code"]}
    rows = await fetch_all(text(_POOL_QUERY), params)
    if not rows:
        return None, None
    pre, live = PRESELECT[channel], LIVE[channel]
    if channel in AB_ARMS:
        pre = live = random.choice(AB_ARMS[channel])
    top = heapq.nsmallest(log_top_n, rows, key=lambda r: (-score(r, channel, pre), r["id"]))
    # A few random pool memes outside the top give exploration (and IPS) support off the top.
    top_ids = {r["id"] for r in top}
    sample = random.sample(rows, min(len(rows), log_top_n + POOL_SAMPLE))
    for r in [r for r in sample if r["id"] not in top_ids][:POOL_SAMPLE]:
        top.append({**r, "pool_sample": True})
    # Shadow inputs and the model must never block posting: failures rank by score.
    try:
        await _attach_shadow_inputs(top, channel)
    except Exception:
        logger.warning("crosspost shadow inputs failed", exc_info=True)
    try:
        await _attach_model_inputs(top, channel)
    except Exception:
        logger.warning("crosspost model inputs failed", exc_info=True)
    try:
        model = await get_active_model(channel)
    except Exception:
        logger.warning("crosspost model unusable, ranking by score", exc_info=True)
        model = None
    decision = _build_decision_log(
        channel,
        top,
        pool_size=len(rows),
        live=live,
        pre=pre,
        model=model,
        top_n=settings.CROSSPOST_TOP_N,
        explore_eps=settings.CROSSPOST_EXPLORE_EPS,
    )
    return await _picked_meme_dict(decision["picked_meme_id"]), decision
