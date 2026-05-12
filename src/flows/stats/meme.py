import html
import logging

from prefect import flow

from src.flows.events import safe_emit
from src.flows.hooks import notify_telegram_on_failure
from src.stats import meme
from src.tgbot.logs import log

logger = logging.getLogger(__name__)

TELEGRAM_LOG_HTML_MESSAGE_LIMIT = 4000
LOW_SENT_POOL_ALERT_HTML_BUDGET = 3900
LOW_SENT_POOL_ALERT_MAX_ROWS = 10
LOW_SENT_POOL_ALERT_FIELD_HTML_LIMIT = 64
LOW_SENT_POOL_ALERT_SOURCE_URL_HTML_LIMIT = 80


@flow(
    name="Calculate meme_stats",
    retries=2,
    retry_delay_seconds=30,
    timeout_seconds=300,
    on_failure=[notify_telegram_on_failure],
)
async def calculate_meme_stats() -> None:
    # Incremental: only recompute stats for memes active in the last 3 hours.
    # Memes with no recent reactions keep their existing meme_stats rows.
    # Heavy operations (raw_impr_rank, invited_count) run separately every hour
    # via calculate_meme_stats_heavy to avoid blocking this 15-min flow.
    await meme.calculate_meme_reactions_and_engagement(lookback_hours=3)

    safe_emit("ff.stats.meme.completed", "ff.stats.meme")


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _escape_html_ellipsized(value: object, max_html_chars: int) -> str:
    text = str(value or "unknown")
    suffix = "..."
    budget = max_html_chars - len(suffix)
    escaped_parts = []
    used = 0

    for char in text:
        escaped_char = html.escape(char)
        if used + len(escaped_char) > budget:
            return "".join(escaped_parts) + suffix
        escaped_parts.append(escaped_char)
        used += len(escaped_char)

    return "".join(escaped_parts)


def _append_line_with_budget(lines: list[str], line: str, budget: int) -> bool:
    candidate = "\n".join([*lines, line])
    if len(candidate) > budget:
        return False
    lines.append(line)
    return True


def _format_low_sent_pool_skip_rate_alert(
    rows: list[dict],
    skip_rate_threshold: float,
    min_sends: int,
    lookback_days: int,
) -> str:
    ids = " ".join(str(row["meme_id"]) for row in rows[:LOW_SENT_POOL_ALERT_MAX_ROWS])
    lines = [
        "Low-sent pool skip-rate alert",
        (
            "Rule: recommended_by=low_sent_pool, "
            f"last {lookback_days}d, sends >= {min_sends}, "
            f"explicit down/skip rate > {_pct(skip_rate_threshold)}"
        ),
        f"Count: {len(rows)}",
        (
            "Review: use "
            f"<code>/meme {ids}</code> in the moderator chat; "
            "reject/snooze only after manual inspection. No recommendation traffic changed."
        ),
        "",
    ]

    displayed_rows = 0
    for row in rows[:LOW_SENT_POOL_ALERT_MAX_ROWS]:
        action_state = (
            "already_rejected_or_snoozed" if row["already_rejected_or_snoozed"] else "needs_review"
        )
        source_url = _escape_html_ellipsized(
            row["source_url"],
            LOW_SENT_POOL_ALERT_SOURCE_URL_HTML_LIMIT,
        )
        source_type = _escape_html_ellipsized(
            row["source_type"],
            LOW_SENT_POOL_ALERT_FIELD_HTML_LIMIT,
        )
        meme_status = _escape_html_ellipsized(
            row["meme_status"],
            LOW_SENT_POOL_ALERT_FIELD_HTML_LIMIT,
        )
        source_status = _escape_html_ellipsized(
            row["source_status"],
            LOW_SENT_POOL_ALERT_FIELD_HTML_LIMIT,
        )
        last_sent_at = _escape_html_ellipsized(
            row["last_sent_at"],
            LOW_SENT_POOL_ALERT_FIELD_HTML_LIMIT,
        )
        line = (
            "- "
            f"#{row['meme_id']} "
            f"source=#{row['meme_source_id']}:{source_type} "
            f"meme_status={meme_status} "
            f"source_status={source_status} "
            f"action={action_state} "
            f"sends={row['sends']} "
            f"reactions={row['explicit_reactions']} "
            f"likes={row['likes']} "
            f"skips={row['skips']} "
            f"like_rate={_pct(row['like_rate'])} "
            f"skip_rate={_pct(row['skip_rate'])} "
            f"age_days={row['published_age_days']:.1f} "
            f"last_sent={last_sent_at} "
            f"<code>{source_url}</code>"
        )
        if not _append_line_with_budget(lines, line, LOW_SENT_POOL_ALERT_HTML_BUDGET):
            break
        displayed_rows += 1

    remaining_rows = len(rows) - displayed_rows
    if remaining_rows > 0:
        summary = f"...and {remaining_rows} more; rerun the flow with a larger limit."
        _append_line_with_budget(lines, summary, LOW_SENT_POOL_ALERT_HTML_BUDGET)

    message = "\n".join(lines)
    if len(message) >= TELEGRAM_LOG_HTML_MESSAGE_LIMIT:
        logger.warning("Low-sent pool alert exceeded Telegram log budget after formatting")
    return message


@flow(
    name="Alert low_sent_pool skip rate",
    retries=1,
    retry_delay_seconds=60,
    timeout_seconds=180,
    on_failure=[notify_telegram_on_failure],
)
async def alert_low_sent_pool_skip_rate(
    skip_rate_threshold: float = meme.LOW_SENT_POOL_SKIP_RATE_ALERT_THRESHOLD,
    min_sends: int = meme.LOW_SENT_POOL_SKIP_RATE_ALERT_MIN_SENDS,
    lookback_days: int = meme.LOW_SENT_POOL_SKIP_RATE_ALERT_LOOKBACK_DAYS,
    limit: int = meme.LOW_SENT_POOL_SKIP_RATE_ALERT_LIMIT,
) -> dict:
    rows = await meme.get_low_sent_pool_skip_rate_alerts(
        skip_rate_threshold=skip_rate_threshold,
        min_sends=min_sends,
        lookback_days=lookback_days,
        limit=limit,
    )
    summary = {
        "flagged_count": len(rows),
        "meme_ids": [row["meme_id"] for row in rows],
        "skip_rate_threshold": skip_rate_threshold,
        "min_sends": min_sends,
        "lookback_days": lookback_days,
    }

    if rows:
        logger.warning("Flagged %d low_sent_pool memes for skip-rate review", len(rows))
        await log(
            _format_low_sent_pool_skip_rate_alert(
                rows,
                skip_rate_threshold=skip_rate_threshold,
                min_sends=min_sends,
                lookback_days=lookback_days,
            )
        )

    safe_emit(
        "ff.stats.low_sent_pool_skip_rate_alert.completed",
        "ff.stats.low_sent_pool_skip_rate_alert",
        summary,
    )
    return summary
