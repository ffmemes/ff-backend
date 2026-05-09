#!/usr/bin/env python3
"""Comms Manager post-lifecycle contract.

Codifies the draft → approval → publish → close lifecycle that lived as
imperative shell + tribal knowledge in `agents/comms-manager/AGENTS.md`,
so the prompt can shrink to topic taste rules + helper invocation.

Pure module — no Telegram, Paperclip API, or DB I/O. Tests in
`tests/test_paperclip_comms_post.py`.

Contract surface
----------------

- `post_slug(date, topic_slug)`  →  stable `[post:YYYY-MM-DD-slug]`
  prefix used everywhere (Paperclip issue title, log line, archive
  filename, idempotency key).
- `confirmation_idempotency_key(slug)`  →  derived key for
  `paperclipRequestConfirmation` so reruns reuse one card instead of
  stacking new approval cards.
- `archive_path(slug)`  →  `docs/comms/published/<slug>.md` path the
  publish step writes to.
- `lifecycle_state(issue)`  →  enum-like string, one of
  `LIFECYCLE_STATES`.
- `next_action(issue, *, now)`  →  the single concrete next step the
  agent should take given the current state, or `"none"` if the issue
  is terminal.
- `publish_outcome_required_fields()` / `publish_outcome_missing(...)`
  — verifier for the closing comment so an "approved without
  publication" never gets marked `done`.
- `is_stale_draft(issue, *, now)` — 24h staleness check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from paperclip_contracts import (
    nested_state,
)

POST_SLUG_RE = re.compile(r"^\[post:(\d{4}-\d{2}-\d{2})-([a-z0-9][a-z0-9-]*)\]")
TOPIC_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

LIFECYCLE_STATES: tuple[str, ...] = (
    "missing_slug",
    "draft_pending_approval",
    "approved_unpublished",
    "stale_draft",
    "published",
    "blocked",
    "unknown",
)

STALE_AFTER = timedelta(hours=24)

PUBLISH_REQUIRED_FIELDS: tuple[str, ...] = (
    "outcome",
    "channel",
    "telegram_message_id",
    "editorial_post_id",
)


@dataclass(frozen=True)
class NextAction:
    """One concrete step the agent should take next.

    `kind` is the verb the prompt cares about (`create_draft`,
    `request_confirmation`, `publish`, `close_published`,
    `mark_stale`, `none`). `reason` is the one-line explanation that
    goes in the issue comment.
    """

    kind: str
    reason: str
    suggested_payload: Mapping[str, Any] | None = None


def post_slug(date_str: str, topic_slug: str) -> str:
    """Build the canonical `[post:YYYY-MM-DD-slug]` prefix.

    Raises `ValueError` for invalid topic slugs so the caller can't
    accidentally create `[post:test]` / `[post:debug]` clutter.
    """
    if not TOPIC_SLUG_RE.match(topic_slug):
        raise ValueError(f"invalid topic slug: {topic_slug!r}")
    # Validate date shape; we don't normalize because callers occasionally
    # pre-format with locale-specific tzs.
    datetime.strptime(date_str, "%Y-%m-%d")
    return f"[post:{date_str}-{topic_slug}]"


def parse_post_slug(title: str | None) -> tuple[str, str] | None:
    """Return `(date_str, topic_slug)` or `None` if the title doesn't
    start with a well-formed `[post:...]` prefix."""
    if not title:
        return None
    match = POST_SLUG_RE.match(title.strip().lower())
    if not match:
        return None
    return match.group(1), match.group(2)


def confirmation_idempotency_key(slug: str) -> str:
    """Idempotency key for `paperclipRequestConfirmation`.

    The stable key matters because re-running the daily routine after a
    transient Paperclip API error must not stack a second approval card
    on the same draft. The key is derived from the post slug so the
    operator can predict it from the issue title alone.
    """
    parsed = parse_post_slug(slug) if slug.startswith("[post:") else None
    if parsed is None:
        # The slug already came in as `YYYY-MM-DD-topic`, e.g. from
        # archive paths.
        if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$", slug):
            raise ValueError(f"unexpected slug shape: {slug!r}")
        body = slug
    else:
        body = f"{parsed[0]}-{parsed[1]}"
    return f"comms.daily-channel-post.{body}"


def archive_path(slug: str) -> str:
    parsed = parse_post_slug(slug) if slug.startswith("[post:") else None
    if parsed is None:
        if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$", slug):
            raise ValueError(f"unexpected slug shape: {slug!r}")
        body = slug
    else:
        body = f"{parsed[0]}-{parsed[1]}"
    return f"docs/comms/published/{body}.md"


def _issue_text(issue: Mapping[str, Any]) -> str:
    parts = [issue.get("title") or ""]
    parts.append(issue.get("description") or "")
    for comment in issue.get("comments") or []:
        body = comment.get("body") if isinstance(comment, Mapping) else None
        if body:
            parts.append(body)
    return "\n".join(parts)


def _last_event_at(issue: Mapping[str, Any]) -> datetime | None:
    candidates: list[datetime] = []
    for key in ("updatedAt", "createdAt"):
        value = issue.get(key)
        ts = _parse_iso(value)
        if ts is not None:
            candidates.append(ts)
    for comment in issue.get("comments") or []:
        if not isinstance(comment, Mapping):
            continue
        ts = _parse_iso(comment.get("createdAt") or comment.get("updatedAt"))
        if ts is not None:
            candidates.append(ts)
    if not candidates:
        return None
    return max(candidates)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def lifecycle_state(issue: Mapping[str, Any]) -> str:
    """Classify the `[post:...]` issue's lifecycle state.

    The classification is independent of `now`; staleness is layered on
    top by `next_action()` because a 22h-old draft may be `pending`
    today and `stale` tomorrow without any state change inside the
    issue.
    """
    parsed = parse_post_slug(issue.get("title"))
    if parsed is None:
        return "missing_slug"

    status = (issue.get("status") or "").lower()
    if status == "blocked":
        return "blocked"

    text = _issue_text(issue)
    state = nested_state(text, slug="post")

    if state == "published":
        return "published"
    if state == "stale_draft":
        return "stale_draft"
    if state == "blocked_without_access":
        return "blocked"
    if state == "approved_unpublished":
        return "approved_unpublished"
    if state == "pending_approval":
        return "draft_pending_approval"

    # `nested_state` falls back to `unknown` for non-`post` slugs, but
    # we already checked the prefix above. Anything else is a draft we
    # haven't routed to CEO yet.
    return "draft_pending_approval"


def is_stale_draft(issue: Mapping[str, Any], *, now: datetime) -> bool:
    """`True` when the draft has been waiting on approval/publish past
    the 24h cutoff documented in `agents/comms-manager/AGENTS.md`."""
    state = lifecycle_state(issue)
    if state not in {"draft_pending_approval", "approved_unpublished"}:
        return False
    last = _last_event_at(issue)
    if last is None:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last) >= STALE_AFTER


def next_action(issue: Mapping[str, Any], *, now: datetime) -> NextAction:
    """Single next concrete step the comms agent should take.

    Designed so the prompt can collapse "ladder of conditions" prose
    into one helper call. The `kind` string is the only field prompts
    are encouraged to branch on; `reason` is intended for the issue
    comment body.
    """
    state = lifecycle_state(issue)
    if state == "missing_slug":
        return NextAction(
            kind="rename_or_create",
            reason="Issue title does not match [post:YYYY-MM-DD-slug]; rename or recreate",
        )
    if state == "blocked":
        return NextAction(
            kind="resolve_blocker",
            reason="Issue is blocked; resolve underlying blocker before continuing",
        )
    if state == "published":
        if (issue.get("status") or "").lower() not in {"done", "cancelled"}:
            return NextAction(
                kind="close_published",
                reason="Publication confirmed; close the draft issue with outcome=published",
            )
        return NextAction(kind="none", reason="Issue is terminal")

    if state == "stale_draft":
        return NextAction(
            kind="mark_stale",
            reason="Draft has been pending past 24h; comment outcome=stale_draft and refresh data",
        )

    if is_stale_draft(issue, now=now):
        return NextAction(
            kind="mark_stale",
            reason="Draft has been pending past 24h; comment outcome=stale_draft and refresh data",
        )

    if state == "draft_pending_approval":
        parsed = parse_post_slug(issue.get("title"))
        idem = confirmation_idempotency_key(f"[post:{parsed[0]}-{parsed[1]}]") if parsed else None
        return NextAction(
            kind="request_confirmation",
            reason="Open structured CEO confirmation card with stable idempotency key",
            suggested_payload={"idempotencyKey": idem} if idem else None,
        )

    if state == "approved_unpublished":
        return NextAction(
            kind="publish",
            reason="CEO approval present; call publish_editorial_post",
        )

    return NextAction(kind="none", reason="Unknown lifecycle state")


def publish_outcome_required_fields() -> tuple[str, ...]:
    return PUBLISH_REQUIRED_FIELDS


def publish_outcome_missing(payload: Mapping[str, Any]) -> list[str]:
    """Names of required publish-outcome fields that are not present.

    Comms must NEVER close `[post:...]` `done` without `outcome=published`,
    `channel`, `telegram_message_id`, and `editorial_post_id`. This
    helper is the verifier the close step calls before
    `paperclipUpdateIssue(status="done")`.
    """
    missing: list[str] = []
    for field in PUBLISH_REQUIRED_FIELDS:
        value = payload.get(field)
        if value is None or value == "":
            missing.append(field)
    if (payload.get("outcome") or "") != "published":
        if "outcome" not in missing:
            missing.append("outcome")
    return missing


def render_decision_summary(
    issue: Mapping[str, Any],
    *,
    now: datetime,
    publish_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parse_post_slug(issue.get("title"))
    state = lifecycle_state(issue)
    action = next_action(issue, now=now)
    summary: dict[str, Any] = {
        "slug": f"[post:{parsed[0]}-{parsed[1]}]" if parsed else None,
        "state": state,
        "stale": is_stale_draft(issue, now=now),
        "next_action": {
            "kind": action.kind,
            "reason": action.reason,
            "suggested_payload": dict(action.suggested_payload)
            if action.suggested_payload
            else None,
        },
    }
    if parsed:
        summary["idempotency_key"] = confirmation_idempotency_key(f"[post:{parsed[0]}-{parsed[1]}]")
        summary["archive_path"] = archive_path(f"[post:{parsed[0]}-{parsed[1]}]")
    if publish_payload is not None:
        summary["publish_outcome_missing"] = publish_outcome_missing(publish_payload)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Dry-run helper for the Comms Manager post-lifecycle contract.")
    )
    parser.add_argument(
        "--issue",
        help=(
            "Path to issue JSON (title, description, comments[], status, "
            "updatedAt). '-' for stdin."
        ),
    )
    parser.add_argument(
        "--publish",
        help=(
            "Path to publish-outcome JSON (outcome, channel, "
            "telegram_message_id, editorial_post_id)."
        ),
    )
    parser.add_argument(
        "--now",
        help="ISO-8601 timestamp; defaults to current UTC. Useful for deterministic tests.",
    )
    parser.add_argument("--json", action="store_true", help="JSON output (default: pretty)")
    args = parser.parse_args(argv)

    if args.issue is None:
        parser.error("--issue is required")

    issue = (
        json.load(sys.stdin)
        if args.issue == "-"
        else json.loads(open(args.issue, "r", encoding="utf-8").read())
    )
    publish_payload = (
        json.loads(open(args.publish, "r", encoding="utf-8").read()) if args.publish else None
    )

    if args.now:
        now = _parse_iso(args.now) or datetime.now(timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    summary = render_decision_summary(issue, now=now, publish_payload=publish_payload)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
