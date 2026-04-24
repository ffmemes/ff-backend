"""
Editorial post performance helpers.

Two layers:
  1. `get_recent_editorial_performance(channel, days)` — DB query returning
     rows with category, entity_id, text preview, views, forwards, reactions.
  2. `write_channel_stats_report(channel, days, output_dir)` — materializes
     `experiments/reports/channel-stats-YYYY-MM-DD.md`. The Comms Agent reads
     this file as its first input of the day (Step 0 of its routine).

The report is deliberately short (LLM-friendly): top/bottom by views,
reaction-mix summary, category/entity frequency. Numbers are the source of
truth; the markdown is a curated snapshot.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from prefect import flow, get_run_logger
from sqlalchemy import desc, select

from src.database import editorial_posts, fetch_all
from src.flows.hooks import notify_telegram_on_failure

REPORTS_DIR = Path("experiments/reports")


@dataclass
class EditorialRow:
    id: int
    channel: str
    created_at: datetime
    category: str | None
    entity_id: str | None
    topic_slug: str | None
    text: str
    views: int
    forwards: int
    reactions: int
    reactions_detail: dict[str, int] | None
    telegram_message_id: int


async def get_recent_editorial_performance(
    channel: str = "ru",
    days: int = 30,
) -> list[EditorialRow]:
    """Return editorial posts for `channel`, newest first, within `days`."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = await fetch_all(
        select(
            editorial_posts.c.id,
            editorial_posts.c.channel,
            editorial_posts.c.created_at,
            editorial_posts.c.category,
            editorial_posts.c.entity_id,
            editorial_posts.c.topic_slug,
            editorial_posts.c.text,
            editorial_posts.c.views,
            editorial_posts.c.forwards,
            editorial_posts.c.reactions,
            editorial_posts.c.reactions_detail,
            editorial_posts.c.telegram_message_id,
        )
        .where(editorial_posts.c.channel == channel)
        .where(editorial_posts.c.created_at >= cutoff)
        .order_by(desc(editorial_posts.c.created_at))
    )
    return [
        EditorialRow(
            id=r["id"],
            channel=r["channel"],
            created_at=r["created_at"],
            category=r["category"],
            entity_id=r["entity_id"],
            topic_slug=r["topic_slug"],
            text=r["text"],
            views=r["views"] or 0,
            forwards=r["forwards"] or 0,
            reactions=r["reactions"] or 0,
            reactions_detail=r["reactions_detail"],
            telegram_message_id=r["telegram_message_id"],
        )
        for r in (rows or [])
    ]


def _first_line(text: str, limit: int = 120) -> str:
    first = text.strip().split("\n", 1)[0]
    # Strip simple HTML tags for preview (readability only).
    cleaned = []
    in_tag = False
    for ch in first:
        if ch == "<":
            in_tag = True
        elif ch == ">":
            in_tag = False
        elif not in_tag:
            cleaned.append(ch)
    out = "".join(cleaned).strip()
    return out[:limit] + ("…" if len(out) > limit else "")


def _median(values: list[int]) -> int:
    if not values:
        return 0
    sorted_vals = sorted(values)
    mid = len(sorted_vals) // 2
    if len(sorted_vals) % 2:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) // 2


def format_channel_stats_report(
    rows: list[EditorialRow],
    channel: str,
    days: int,
    as_of: datetime,
) -> str:
    if not rows:
        return (
            f"# Channel stats — @{channel} — {as_of.date().isoformat()}\n\n"
            f"No editorial posts in the last {days} days.\n"
        )

    views = [r.views for r in rows]
    median_views = _median(views)
    top_views = sorted(rows, key=lambda r: r.views, reverse=True)[:5]
    # Only include posts that had at least 24h to accumulate views.
    cutoff_24h = as_of - timedelta(hours=24)
    mature = [r for r in rows if r.created_at <= cutoff_24h]
    bottom_views = sorted(mature, key=lambda r: r.views)[:3]

    # Reaction emoji summary (top 5 across all posts).
    reaction_counter: Counter[str] = Counter()
    for r in rows:
        for emoji, count in (r.reactions_detail or {}).items():
            reaction_counter[emoji] += count

    # Category / entity frequency for rotation awareness.
    categories = Counter(r.category or "?" for r in rows)
    entities = Counter(r.entity_id or "?" for r in rows)
    recent_keys = [(r.category, r.entity_id) for r in rows[:7]]

    lines = [
        f"# Channel stats — @{channel} — {as_of.date().isoformat()}",
        "",
        f"Window: last {days} days. Posts: {len(rows)}. Median views: {median_views}.",
        "",
        "## Top 5 by views",
        "",
    ]
    for r in top_views:
        lines.append(
            f"- **{r.views}** views, {r.reactions} react, {r.forwards} fwd — "
            f"`{r.category or '?'}/{r.entity_id or '?'}` — {_first_line(r.text)}"
        )

    if bottom_views:
        lines += ["", "## Weakest 3 (≥24h old)", ""]
        for r in bottom_views:
            lines.append(
                f"- **{r.views}** views, {r.reactions} react — "
                f"`{r.category or '?'}/{r.entity_id or '?'}` — {_first_line(r.text)}"
            )

    lines += ["", "## Reaction mix (top 5)", ""]
    for emoji, count in reaction_counter.most_common(5):
        lines.append(f"- {emoji} × {count}")

    lines += ["", "## Category frequency", ""]
    for cat, count in categories.most_common():
        lines.append(f"- {cat}: {count}")

    lines += ["", "## Last 7 (category / entity — don't repeat these)", ""]
    for cat, ent in recent_keys:
        lines.append(f"- `{cat or '?'}` / `{ent or '?'}`")

    lines += [
        "",
        "## Top 5 entity_ids by frequency",
        "",
    ]
    for ent, count in entities.most_common(5):
        lines.append(f"- {ent}: {count}")

    lines += [
        "",
        "_Generated by `src/comms/performance.py`. Regenerates daily at 06:55 UTC._",
        "",
    ]
    return "\n".join(lines)


@flow(
    retries=1,
    retry_delay_seconds=30,
    timeout_seconds=60,
    on_failure=[notify_telegram_on_failure],
)
async def write_channel_stats_report(
    channel: str = "ru",
    days: int = 30,
    output_dir: str | None = None,
) -> str:
    """Write the daily channel stats markdown snapshot. Returns the file path."""
    log = get_run_logger()
    rows = await get_recent_editorial_performance(channel=channel, days=days)
    as_of = datetime.utcnow()
    report = format_channel_stats_report(rows, channel=channel, days=days, as_of=as_of)

    out_dir = Path(output_dir) if output_dir else REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"channel-stats-{as_of.date().isoformat()}.md"
    path.write_text(report, encoding="utf-8")
    log.info(f"Wrote {path} with {len(rows)} posts")
    return str(path)


__all__ = [
    "EditorialRow",
    "REPORTS_DIR",
    "format_channel_stats_report",
    "get_recent_editorial_performance",
    "write_channel_stats_report",
]
