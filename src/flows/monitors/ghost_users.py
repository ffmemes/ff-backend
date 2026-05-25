"""Ghost user monitor.

Catches the FFM-907 / Sega failure mode automatically: a new user
presses /start, gets a `user` row, but never receives a meme. Before
this monitor existed we only learned about ghosts when a friend of
@ohld complained.

Definition: a ghost is a `user` row created N seconds ago with no
`user_meme_reaction` row, excluding users who have blocked the bot.
Two severities, both filtered by
`user_tg.deep_link` to exclude blocked acquisition channels (where
silent drop is by design):

  - 60s ≤ age ≤ 300s        → WARN
  - 300s < age ≤ 1500s      → ERROR (something stayed broken for 5+ min)

Runs every minute. The 25-minute trailing window is wide enough that
a couple of minutes of Prefect downtime won't lose the signal, narrow
enough that a single regression spike fires 5+ ERROR runs in a row
(easy to spot in the admin chat).
"""

import logging

from prefect import flow
from sqlalchemy import text

from src.database import fetch_one
from src.flows.hooks import notify_telegram_on_failure
from src.tgbot.handlers.start import BLOCKED_ACQUISITION_CHANNELS
from src.tgbot.logs import log

logger = logging.getLogger(__name__)


# Anything that early-returns BEFORE save_user_data must NOT contribute
# to ghost counts. Today the only such path is the blocked-acquisition
# branch (which doesn't insert a `user` row at all, so it's already
# excluded). If a future deep_link branch inserts a row but intentionally
# never serves a meme on first /start, add its prefix here.
GHOST_EXEMPT_DEEP_LINK_PREFIXES: tuple[str, ...] = ("tapps",)
GHOST_EXEMPT_DEEP_LINKS: frozenset[str] = BLOCKED_ACQUISITION_CHANNELS


def _build_exempt_clause() -> str:
    # Constants only — these come from Python source, never user input.
    exempt_eq = ", ".join(f"'{name}'" for name in sorted(GHOST_EXEMPT_DEEP_LINKS))
    prefix_clauses = " OR ".join(
        f"deep_link LIKE '{prefix}%'" for prefix in GHOST_EXEMPT_DEEP_LINK_PREFIXES
    )
    parts = []
    if exempt_eq:
        parts.append(f"deep_link IN ({exempt_eq})")
    if prefix_clauses:
        parts.append(f"({prefix_clauses})")
    if not parts:
        return "FALSE"
    return " OR ".join(parts)


def _ghost_count_sql() -> str:
    exempt = _build_exempt_clause()
    return f"""
        WITH candidates AS (
            SELECT
                u.id,
                u.created_at,
                ut.deep_link,
                EXTRACT(EPOCH FROM (NOW() - u.created_at)) AS age_sec
            FROM "user" u
            LEFT JOIN user_tg ut ON ut.id = u.id
            WHERE u.created_at BETWEEN NOW() - INTERVAL '25 minutes'
                                  AND NOW() - INTERVAL '60 seconds'
              AND u.type NOT IN ('blocked_bot', 'banned', 'waitlist')
              AND u.blocked_bot_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM user_meme_reaction r WHERE r.user_id = u.id
              )
              AND NOT COALESCE({exempt}, FALSE)
        )
        SELECT
            COUNT(*) FILTER (WHERE age_sec BETWEEN 60 AND 300) AS warn_count,
            COUNT(*) FILTER (WHERE age_sec > 300) AS error_count,
            COUNT(*) AS total_in_window,
            ARRAY_AGG(id ORDER BY age_sec DESC)
                FILTER (WHERE age_sec > 300) AS error_user_ids
        FROM candidates
    """


def _format_alert(warn_count: int, error_count: int, sample_ids: list[int]) -> str:
    sample = sample_ids[:5] if sample_ids else []
    sample_str = ", ".join(f"#{uid}" for uid in sample)
    parts = ["👻 Ghost-user monitor"]
    if error_count:
        parts.append(f"🔴 ERROR: {error_count} new users without a meme >5min")
        if sample_str:
            parts.append(f"   sample: {sample_str}")
    if warn_count:
        parts.append(f"🟡 WARN: {warn_count} new users without a meme 1–5min")
    return "\n".join(parts)


@flow(
    name="Monitor ghost users",
    retries=1,
    retry_delay_seconds=15,
    timeout_seconds=60,
    on_failure=[notify_telegram_on_failure],
)
async def monitor_ghost_users() -> dict:
    """Count new users who never got a meme; alert if any."""
    row = await fetch_one(text(_ghost_count_sql()))
    warn_count = int(row["warn_count"] or 0)
    error_count = int(row["error_count"] or 0)
    error_ids = [int(uid) for uid in (row["error_user_ids"] or [])]

    summary = {
        "warn_count": warn_count,
        "error_count": error_count,
        "total_in_window": int(row["total_in_window"] or 0),
        "error_user_ids": error_ids,
    }

    if error_count:
        logger.error("Ghost users (>5min): %d (sample %s)", error_count, error_ids[:5])
    if warn_count:
        logger.warning("Ghost users (1–5min): %d", warn_count)

    if error_count or warn_count:
        await log(_format_alert(warn_count, error_count, error_ids))

    return summary
