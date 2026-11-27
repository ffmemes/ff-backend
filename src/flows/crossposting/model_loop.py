"""Channel model loop: nightly ridge refit and the daily digest to the owner.

Posting ranks by the active ``crossposting_model`` row and draws from its top-N
(src/crossposting/service.py). Here: refit on every labeled decision (post older than 36h,
zf_24h from snapshots), store a new version, activate it; send a short daily summary.
"""

from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from prefect import flow, get_run_logger
from sqlalchemy import func, insert, select, text, update
from telegram.constants import ParseMode

from src.config import settings
from src.crossposting.model import (
    ALPHA,
    features,
    fit_ridge,
    load_model,
    source_prior,
    walk_forward,
)
from src.crossposting.service import fetch_labels, fetch_model_static_inputs
from src.database import crossposting_model, fetch_all, fetch_one, run_in_transaction
from src.flows.hooks import notify_telegram_on_failure
from src.tgbot.bot import bot
from src.tgbot.constants import TELEGRAM_CHANNEL_EN_LINK, TELEGRAM_CHANNEL_RU_LINK

CHANNELS = {"tgchannelru": TELEGRAM_CHANNEL_RU_LINK, "tgchannelen": TELEGRAM_CHANNEL_EN_LINK}
MIN_TRAIN = 150
# EN labels are mostly noise (median 1 forward): its model goes live only when walk-forward
# is not worse than the current score; otherwise EN stays on score_topN (2026-11-27 readout).
WF_GATED = {"tgchannelen"}

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
    """One row per labeled decision: logged bot stats + static inputs + source prior at decision."""
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
                "src_prior_z": prior_z,
                "src_prior_n": prior_n,
            }
        )
        if x is not None:
            rows.append(
                {"posted_at": p["posted_at"], "x": x, "zf": p["zf"], "score": c.get("final_score")}
            )
    return rows


def should_activate(channel: str, wf: dict[str, Any]) -> bool:
    return channel not in WF_GATED or wf.get("delta", -1.0) >= 0


async def _save_model(channel: str, fit: dict, rows: list[dict], wf: dict, active: bool) -> int:
    """New version; the newest decides whether the channel has an active model at all."""
    m = crossposting_model.c
    version = select(func.coalesce(func.max(m.version), 0) + 1).where(m.channel == channel)

    async def tx(conn):
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
                alpha=ALPHA,
                train_from=min(r["posted_at"] for r in rows),
                train_to=max(r["posted_at"] for r in rows),
                n_train=len(rows),
                metrics=wf,
                is_active=active,
            )
            .returning(m.version)
        )
        return res.scalar_one()

    return await run_in_transaction(tx)


@flow(timeout_seconds=900, on_failure=[notify_telegram_on_failure])
async def retrain_channel_models():
    logger = get_run_logger()
    for channel in CHANNELS:
        rows = await training_rows(channel)
        if len(rows) < MIN_TRAIN:
            logger.warning(f"{channel}: {len(rows)} labeled decisions < {MIN_TRAIN}, no refit")
            continue
        fit = fit_ridge([r["x"] for r in rows], [r["zf"] for r in rows])
        load_model({**fit, "version": 0})  # refuse to store what posting would reject
        wf = walk_forward(rows)
        active = should_activate(channel, wf)
        version = await _save_model(channel, fit, rows, wf, active)
        logger.info(f"{channel}: model v{version} n={len(rows)} active={active} wf={wf}")


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
_MODEL_QUERY = """
    SELECT version, created_at, n_train, metrics, is_active FROM crossposting_model
    WHERE channel = :channel ORDER BY version DESC LIMIT 1
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
        "model": await fetch_one(text(_MODEL_QUERY), {"channel": channel}),
        "health": await fetch_one(text(_HEALTH_QUERY), {"channel": channel}),
    }


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}"


def format_digest(digests: list[dict[str, Any]]) -> str:
    lines = ["📈 <b>Каналы за сутки</b>: посты 24–48 ч назад, метка = форварды за 24 ч"]
    for d in digests:
        ch, m, h = d["channel"], d["model"], d["health"]
        name = "RU" if ch == "tgchannelru" else "EN"
        if m is None:
            head = "модели нет, ранжирует скор"
        else:
            delta = (m["metrics"] or {}).get("delta")
            state = "активна" if m["is_active"] else "не активна, ранжирует скор"
            head = (
                f"модель v{m['version']} от {m['created_at']:%d.%m}, n {m['n_train']}, "
                f"wf Δρ {_fmt(delta)}, {state}"
            )
        lines += ["", f"<b>{name}</b> · {head}"]
        for p in d["posts"]:
            c = p.get("cand") or {}
            rank = f"{c['policy_rank']}/{p['top_n']}" if p.get("top_n") else "—"
            ver = f"v{p['model_version']}" if p.get("model_version") else "скор"
            link = f"{CHANNELS[ch]}/{p['telegram_message_id']}"
            when = (p["posted_at"] + timedelta(hours=3)).strftime("%d.%m %H:%M")
            lines.append(
                f'• <a href="{escape(link)}">{when}</a> f24 {p["f24"]} · zf {_fmt(p["zf"])}'
                f" · жребий {rank} · {ver} прогноз {_fmt(c.get('model_pred'))}"
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
