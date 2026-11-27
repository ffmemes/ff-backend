"""Channel model loop: nightly ridge refit and the daily digest to the owner.

Posting ranks by the active ``crossposting_model`` row (src/crossposting/service.py).
Nightly: refit the active row's spec (features, alpha) on every labeled decision (post older
than 36h, zf_24h from snapshots) and store it as an inactive version. It is promoted only by
PROMOTION_RULE, at most once per PROMOTE_EVERY; otherwise the active row stays.
"""

import logging
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from prefect import flow, get_run_logger
from sqlalchemy import func, insert, select, text, update
from telegram.constants import ParseMode

from src.config import settings
from src.crossposting.model import (
    ALPHA,
    FEATURES,
    Model,
    coefs_hash,
    compare,
    features,
    fit_ridge,
    load_model,
    source_prior,
    spec_hash,
    walk_forward,
)
from src.crossposting.service import fetch_labels, fetch_model_static_inputs
from src.database import crossposting_model, fetch_all, fetch_one, run_in_transaction
from src.flows.hooks import notify_telegram_on_failure
from src.tgbot.bot import bot
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_LINK, TELEGRAM_CHANNEL_RU_LINK

logger = logging.getLogger(__name__)

CHANNELS = {"tgchannelru": TELEGRAM_CHANNEL_RU_LINK, "tgchannelen": TELEGRAM_CHANNEL_EN_LINK}
MIN_TRAIN = 150
PROMOTE_EVERY = timedelta(days=7)
# Promote the nightly version when, on the same out-of-sample posts, its walk-forward Spearman
# beats the active model (frozen, on posts after its training window) or, with no active
# model, the logged live score: better in >= 2 of 3 time segments and not worse overall.
PROMOTION_RULE = "wins>=2/3 and delta>=0"

# Latest decision per picked meme (a retried flow can log twice) with its picked candidate.
_PICKED_QUERY = """
    SELECT DISTINCT ON (dl.picked_meme_id)
           dl.picked_meme_id AS meme_id, dl.decided_at, dl.policy, dl.top_n, dl.model_version,
           c AS cand
    FROM crossposting_decision_log dl
    CROSS JOIN LATERAL jsonb_array_elements(dl.candidates) c
    WHERE dl.channel = :channel
      AND dl.decided_at >= :since
      AND (c->>'meme_id')::int = dl.picked_meme_id
    ORDER BY dl.picked_meme_id, dl.decided_at DESC
"""


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _picked(channel: str, labels: list[dict[str, Any]], since: datetime) -> list[dict]:
    """Labeled posts joined to the decision that picked them (decided <= 1h before posting)."""
    by_meme = {r["meme_id"]: r for r in labels}
    out = []
    for d in await fetch_all(text(_PICKED_QUERY), {"channel": channel, "since": since}):
        lab = by_meme.get(d["meme_id"])
        if lab and timedelta(0) <= lab["posted_at"] - d["decided_at"] <= timedelta(hours=1):
            out.append({**d, **lab})
    return out


async def training_rows(channel: str) -> list[dict[str, Any]]:
    """One row per labeled decision: logged bot stats and static inputs (backfilled for rows
    logged before they existed) + the source prior as known at the decision."""
    labels = await fetch_labels(channel, until=_now() - timedelta(hours=36))
    picked = await _picked(channel, labels, since=datetime(2000, 1, 1))
    static = await fetch_model_static_inputs([p["meme_id"] for p in picked])
    rows = []
    for p in picked:
        c = p["cand"]
        prior_z, prior_n = source_prior(labels, p["source_id"], p["decided_at"])
        x = features(
            {
                "nlikes": c.get("nlikes"),
                "ndislikes": c.get("ndislikes"),
                "nmemes_sent": c.get("nmemes_sent"),
                "age_days": c.get("age_days"),
                "has_caption": c.get("caption_present"),
                **static.get(p["meme_id"], {}),
                # logged inputs win; is_upload is None when they failed to load at decision
                **(
                    {k: c.get(k) for k in ("is_upload", "src_views_pct")}
                    if c.get("is_upload") is not None
                    else {}
                ),
                "src_prior_z": prior_z,
                "src_prior_n": prior_n,
            }
        )
        if x is not None:
            rows.append(
                {"posted_at": p["posted_at"], "x": x, "zf": p["zf"], "score": c.get("final_score")}
            )
    return rows


def should_promote(
    metrics: dict[str, Any], last_activated: datetime | None, now: datetime
) -> tuple[bool, str]:
    if last_activated is not None and now - last_activated < PROMOTE_EVERY:
        return False, "cooldown"
    thirds = metrics.get("thirds")
    if not thirds:
        return False, "too_few_posts"
    if sum(d > 0 for d in thirds) >= 2 and metrics["delta"] >= 0:
        return True, "promoted"
    return False, "not_better"


async def _active_row(channel: str) -> dict[str, Any] | None:
    return await fetch_one(
        text("SELECT * FROM crossposting_model WHERE channel = :channel AND is_active"),
        {"channel": channel},
    )


async def _save_model(
    channel: str, fit: dict, alpha: float, rows: list[dict], metrics: dict, promote: bool
) -> int:
    """Store a new version; when promoted it replaces the active one in the same transaction."""
    m = crossposting_model.c
    version = select(func.coalesce(func.max(m.version), 0) + 1).where(m.channel == channel)

    async def tx(conn):
        if promote:
            await conn.execute(
                update(crossposting_model)
                .where(m.channel == channel, m.is_active)
                .values(is_active=False)
            )
        res = await conn.execute(
            insert(crossposting_model)
            .values(
                channel=channel,
                version=version.scalar_subquery(),
                **fit,
                alpha=alpha,
                train_from=min(r["posted_at"] for r in rows),
                train_to=max(r["posted_at"] for r in rows),
                n_train=len(rows),
                metrics=metrics,
                spec_hash=spec_hash(fit["features"], alpha),
                coefs_hash=coefs_hash(fit),
                is_active=promote,
                activated_at=_now() if promote else None,
            )
            .returning(m.version)
        )
        return res.scalar_one()

    return await run_in_transaction(tx)


async def retrain_channel(channel: str) -> str:
    now = _now()
    active_row = await _active_row(channel)
    active: Model | None = None
    feats, alpha = list(FEATURES), ALPHA
    if active_row is not None:
        try:
            active = load_model(active_row)
            feats, alpha = active.features, float(active_row["alpha"])
        except (ValueError, TypeError):
            logger.warning(f"{channel}: active model unusable, refitting the default spec")
    rows = await training_rows(channel)
    if len(rows) < MIN_TRAIN:
        return f"{channel}: {len(rows)} labeled decisions < {MIN_TRAIN}, no refit"
    fit = fit_ridge([r["x"] for r in rows], [r["zf"] for r in rows], feats, alpha)
    load_model({**fit, "version": 0})  # refuse to store what posting would reject
    test = walk_forward(rows, feats, alpha)
    if active is not None:
        # frozen coefficients are out of sample only after their training window
        test = [{**r, "base": active.predict(r["x"])} for r in test]
        trained_to = active_row["train_to"] or active_row["created_at"]
        test = [r for r in test if r["posted_at"] > trained_to]
        baseline = f"v{active.version}"
    else:
        test = [{**r, "base": r["score"]} for r in test]
        baseline = "score"
    metrics = {**compare(test), "baseline": baseline, "rule": PROMOTION_RULE}
    last = (active_row["activated_at"] or active_row["created_at"]) if active else None
    promote, metrics["decision"] = should_promote(metrics, last, now)
    version = await _save_model(channel, fit, alpha, rows, metrics, promote)
    return f"{channel}: v{version} n={len(rows)} {metrics}"


@flow(timeout_seconds=900, on_failure=[notify_telegram_on_failure])
async def retrain_channel_models():
    log = get_run_logger()
    failed = []
    for channel in CHANNELS:
        try:
            log.info(await retrain_channel(channel))
        except Exception:
            log.exception(f"{channel}: refit failed")
            failed.append(channel)
    if failed:
        raise RuntimeError(f"channel model refit failed: {failed}")


# ── Daily digest ──

_HEALTH_QUERY = """
    SELECT
        (SELECT MAX(snapshot_at) FROM crossposting_snapshots
         WHERE channel = :channel AND snapshot_at > NOW() - INTERVAL '3 days') AS last_snapshot,
        (SELECT COUNT(*) FROM crossposting
         WHERE channel = :channel AND created_at > NOW() - INTERVAL '24 hours'
           AND score_version NOT IN (0, 1)) AS posts_24h,
        (SELECT COUNT(*) FROM crossposting_decision_log
         WHERE channel = :channel AND decided_at > NOW() - INTERVAL '24 hours') AS decisions_24h,
        (SELECT COUNT(*) FROM crossposting cp JOIN meme m ON m.id = cp.meme_id
         WHERE cp.channel = :channel AND m.type = 'image' AND cp.score_version NOT IN (0, 1)
           AND cp.created_at BETWEEN NOW() - INTERVAL '48 hours' AND NOW() - INTERVAL '24 hours'
        ) AS posts_to_label
"""
# The active row and the latest nightly version (often the same row).
_MODELS_QUERY = """
    SELECT version, created_at, activated_at, n_train, metrics, is_active
    FROM crossposting_model
    WHERE channel = :channel
      AND (is_active OR version = (SELECT MAX(version) FROM crossposting_model
                                   WHERE channel = :channel))
"""


async def _channel_digest(channel: str) -> dict[str, Any]:
    now = _now()
    # 9 days: the whole MSK week of every post 24-48h old, for its zf mean.
    labels = await fetch_labels(channel, since=now - timedelta(days=9))
    picked = {
        p["meme_id"]: p for p in await _picked(channel, labels, since=now - timedelta(days=3))
    }
    lo, hi = now - timedelta(hours=48), now - timedelta(hours=24)
    posts = [
        picked.get(r["meme_id"], r)
        for r in sorted(labels, key=lambda r: r["posted_at"])
        if lo <= r["posted_at"] < hi
    ]
    return {
        "channel": channel,
        "now": now,
        "posts": posts,
        "models": await fetch_all(text(_MODELS_QUERY), {"channel": channel}),
        "health": await fetch_one(text(_HEALTH_QUERY), {"channel": channel}),
    }


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}"


_DECISIONS = {
    "promoted": "продвинута",
    "cooldown": "не продвинута: активной меньше 7 дней",
    "too_few_posts": "не продвинута: мало постов для сравнения",
    "not_better": "не продвинута: не лучше",
}


def _models_line(models: list[dict[str, Any]]) -> str:
    active = next((m for m in models if m["is_active"]), None)
    latest = max(models, key=lambda m: m["version"], default=None)
    head = "модели нет, ранжирует скор"
    if active is not None:
        since = active["activated_at"] or active["created_at"]
        head = f"модель v{active['version']} активна с {since:%d.%m}"
    if latest is not None and latest is not active:
        mt = latest["metrics"] or {}
        wins = sum(d > 0 for d in mt.get("thirds") or [])
        head += (
            f"; ночная v{latest['version']} (n {latest['n_train']}) против "
            f"{mt.get('baseline', '—')}: Δρ {_fmt(mt.get('delta'))}, лучше в {wins}/3, "
            f"{_DECISIONS.get(mt.get('decision'), '—')}"
        )
    return head


def format_digest(digests: list[dict[str, Any]]) -> str:
    lines = ["📈 <b>Каналы за сутки</b>: посты 24–48 ч назад, метка = форварды за 24 ч"]
    for d in digests:
        ch, h = d["channel"], d["health"]
        name = "RU" if ch == "tgchannelru" else "EN"
        lines += ["", f"<b>{name}</b> · {_models_line(d['models'])}"]
        for p in d["posts"]:
            c = p.get("cand") or {}
            rank, n = c.get("policy_rank"), p.get("top_n")
            draw = "—" if not n else f"{rank}/{n}" + (" (исследование)" if rank > n else "")
            ver = f"v{p['model_version']}" if p.get("model_version") else "скор"
            link = f"{CHANNELS[ch]}/{p['telegram_message_id']}"
            when = (p["posted_at"] + timedelta(hours=3)).strftime("%d.%m %H:%M")
            lines.append(
                f'• <a href="{escape(link)}">{when}</a> f24 {p["f24"]} · zf {_fmt(p["zf"])}'
                f" · жребий {draw} · {ver} прогноз {_fmt(c.get('model_pred'))}"
            )
        if d["posts"]:
            mean = sum(p["zf"] for p in d["posts"]) / len(d["posts"])
            lines.append(f"Среднее zf {_fmt(mean)}")
        snap = h["last_snapshot"]
        age = "нет" if snap is None else f"{int((d['now'] - snap).total_seconds() // 60)} мин назад"
        ok = snap is not None and d["now"] - snap < timedelta(hours=2)
        ok = ok and h["decisions_24h"] >= h["posts_24h"] and len(d["posts"]) >= h["posts_to_label"]
        lines.append(
            f"{'✅' if ok else '⚠️'} снапшот {age}; решений {h['decisions_24h']} "
            f"на {h['posts_24h']} постов за 24 ч; метки {len(d['posts'])}/{h['posts_to_label']}"
        )
    return "\n".join(lines)


@flow(
    retries=1, retry_delay_seconds=60, timeout_seconds=300, on_failure=[notify_telegram_on_failure]
)
async def send_channel_digest():
    text_ = format_digest([await _channel_digest(ch) for ch in CHANNELS])
    await bot.send_message(
        chat_id=settings.CHANNEL_DIGEST_CHAT_ID or settings.ADMIN_LOGS_CHAT_ID,
        text=text_,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
