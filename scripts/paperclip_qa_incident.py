#!/usr/bin/env python3
"""QA Engineer runtime + incident-dedupe contract.

Codifies the "do not file these recurring incidents", per-scan cap, and
incident-class slug rules that lived as long prose in
`agents/qa-engineer/AGENTS.md`. The prompt can shrink to "scan, classify,
call helper, escalate critical" while every dedupe decision is covered
by a fixture test.

Pure module — no Sentry, Coolify, or DB I/O. Tests in
`tests/test_paperclip_qa_incident.py`.

Contract surface
----------------

- `qa_runtime_probe(env)`  →  `RuntimeProbe` describing whether the run
  should be GREEN / YELLOW / RED before the scan starts. Mirrors the
  "Access Unblock Rule" in the prompt.
- `MAINTENANCE_ACCESS_SLUG`  →  canonical
  `[maintenance:qa-runtime-access]` slug used to dedupe access issues
  across runs.
- `incident_decision(event)`  →  one of
  `INCIDENT_DECISIONS`. Encodes the "do not file" / "comment on existing"
  / "skip entirely" / "create new" rules.
- `scan_summary(events, *, scan_slug)`  →  `ScanSummary` with the cap-
  per-scan rule applied (max 3 new issues; rest go into one
  `[scan:YYYY-MM-DD-HHmm]` batch).
- `incident_slug_for(event)`  →  the canonical `[incident:<slug>]` for
  known recurring classes; the dedupe target the QA agent reuses
  instead of opening a fresh ticket.

Required env vars are listed once and shared with
`scripts/paperclip_runtime_probe.py` so the per-agent probe and the QA
runbook agree on the same names.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

REQUIRED_ENV_VARS: tuple[str, ...] = (
    "ANALYST_DATABASE_URL",
    "COOLIFY_BASE_URL",
    "COOLIFY_ACCESS_TOKEN",
    "SENTRY_AUTH_TOKEN",
    "PREFECT_API_URL",
    "PREFECT_AUTH_STRING",
)

REQUIRED_PATH_FRAGMENTS: tuple[str, ...] = ("/paperclip/bin",)

MAINTENANCE_ACCESS_SLUG: str = "[maintenance:qa-runtime-access]"

INCIDENT_DECISIONS: tuple[str, ...] = (
    "skip",  # drop on the floor
    "skip_known",  # known noise (e.g. describe_memes); never file
    "comment_existing",  # known recurring class with a canonical slug
    "create_new",  # genuinely new incident; goes to the cap-per-scan budget
    "escalate_critical",  # production down → immediate CTO escalation
)

# Canonical incident slugs the prompt reuses across scans. Any event
# that maps to one of these MUST `comment_existing` instead of opening
# a new ticket.
KNOWN_INCIDENT_SLUGS: Mapping[str, str] = {
    "db-pool": "[incident:db-pool]",
    "goat-score-column": "[incident:goat-score-column]",
}

# Exception classes / phrases that map to "skip_known" — i.e. tracked
# elsewhere or filtered upstream, must not become new QA tickets.
SKIP_KNOWN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"describe_memes", re.IGNORECASE),
    re.compile(r"openrouter", re.IGNORECASE),
    re.compile(r"free[\s-]*tier", re.IGNORECASE),
    re.compile(r"\b402\b"),
    re.compile(r"circuit\s+breaker", re.IGNORECASE),
    re.compile(r"telegram\.error\.Forbidden|TelegramError\.Forbidden|\bForbidden\b", re.IGNORECASE),
)

# Recurring exceptions that DO get a canonical slug and `comment_existing`.
# Each entry maps a regex → known incident key.
RECURRING_INCIDENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"TooManyConnectionsError|InterfaceError|connection pool", re.IGNORECASE),
        "db-pool",
    ),
    (re.compile(r"score\s+column\s+does\s+not\s+exist", re.IGNORECASE), "goat-score-column"),
)

# Critical-class severity. We mirror the prompt's "Critical: production
# down" rule conservatively — only events the agent flagged as
# `level == "fatal"` AND in the bot hot path are auto-escalated.
CRITICAL_LEVELS: frozenset[str] = frozenset({"fatal"})

# Default per-scan cap on new issues. Anything above the cap goes into
# a single `[scan:YYYY-MM-DD-HHmm]` summary issue.
DEFAULT_NEW_ISSUE_CAP: int = 3


@dataclass(frozen=True)
class RuntimeProbe:
    """Result of the access-unblock check.

    `status` is one of `"green"` (all required env present) /
    `"yellow"` (one or more missing — run continues degraded) /
    `"red"` (no observability surface available; run aborts and the
    canonical maintenance issue is opened/updated).
    """

    status: str
    missing_env: tuple[str, ...]
    missing_path_fragments: tuple[str, ...]
    maintenance_slug: str = MAINTENANCE_ACCESS_SLUG


@dataclass(frozen=True)
class IncidentDecision:
    decision: str
    incident_slug: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class ScanSummary:
    new_issues: tuple[Mapping[str, Any], ...]
    deduped: tuple[Mapping[str, Any], ...]
    skipped: tuple[Mapping[str, Any], ...]
    batch_slug: str | None
    batch_items: tuple[Mapping[str, Any], ...]
    critical: tuple[Mapping[str, Any], ...]


def qa_runtime_probe(env: Mapping[str, str | None]) -> RuntimeProbe:
    """Verify required observability env vars are present.

    Caller passes a `dict`-like; missing or empty-string values count as
    missing. Path fragments are checked against the `PATH` env var
    because the prompt explicitly requires `/paperclip/bin` in `PATH`
    so the native skill can find the `paperclip` CLI.

    Status:
      `"green"`  — every required env var has a non-empty value AND
                   every required PATH fragment is present.
      `"yellow"` — some env or path missing but the run can still
                   gather partial evidence (e.g. Sentry token present,
                   Coolify token absent → degraded scan).
      `"red"`    — every env var is missing; there is no observability
                   surface at all.
    """
    missing_env = tuple(name for name in REQUIRED_ENV_VARS if not env.get(name))
    path = env.get("PATH") or ""
    missing_path = tuple(frag for frag in REQUIRED_PATH_FRAGMENTS if frag not in path)

    if len(missing_env) == len(REQUIRED_ENV_VARS):
        status = "red"
    elif missing_env or missing_path:
        status = "yellow"
    else:
        status = "green"

    return RuntimeProbe(
        status=status,
        missing_env=missing_env,
        missing_path_fragments=missing_path,
    )


def incident_slug_for(event: Mapping[str, Any]) -> str | None:
    """Return the canonical `[incident:<slug>]` if `event` matches a
    known recurring class, else `None`."""
    text = _event_text(event)
    for pattern, key in RECURRING_INCIDENT_PATTERNS:
        if pattern.search(text):
            return KNOWN_INCIDENT_SLUGS[key]
    return None


def _event_text(event: Mapping[str, Any]) -> str:
    parts = [
        str(event.get("title") or ""),
        str(event.get("message") or ""),
        str(event.get("culprit") or ""),
        str(event.get("type") or ""),
    ]
    return "\n".join(p for p in parts if p)


def _matches_skip_known(text: str) -> bool:
    return any(p.search(text) for p in SKIP_KNOWN_PATTERNS)


def incident_decision(event: Mapping[str, Any]) -> IncidentDecision:
    """Decide whether `event` becomes a Paperclip issue.

    Rules, in order:
      1. `event["level"] == "fatal"` (and not a known noise pattern) →
         `escalate_critical`.
      2. Matches a `RECURRING_INCIDENT_PATTERNS` regex → `comment_existing`
         on the canonical slug.
      3. Matches a `SKIP_KNOWN_PATTERNS` regex → `skip_known`.
      4. Anything else → `create_new`.
    """
    text = _event_text(event)
    level = (event.get("level") or "").lower()

    canonical = incident_slug_for(event)
    if canonical:
        return IncidentDecision(
            decision="comment_existing",
            incident_slug=canonical,
            reason="Recurring incident class with canonical slug",
        )

    if level in CRITICAL_LEVELS:
        # Escalate even if the message has noise terms — `fatal`
        # outranks the noise list. Production-down is never silenced.
        return IncidentDecision(
            decision="escalate_critical",
            reason="level=fatal — production-impact, escalate to CTO",
        )

    if _matches_skip_known(text):
        return IncidentDecision(
            decision="skip_known",
            reason="Tracked elsewhere or expected noise (describe_memes, Forbidden, OpenRouter)",
        )

    return IncidentDecision(decision="create_new", reason="No matching dedupe rule")


def scan_summary(
    events: Sequence[Mapping[str, Any]],
    *,
    scan_slug: str | None = None,
    cap: int = DEFAULT_NEW_ISSUE_CAP,
) -> ScanSummary:
    """Apply the per-scan cap and split events into the four buckets.

    `scan_slug` should be `[scan:YYYY-MM-DD-HHmm]` — required when more
    than `cap` events would otherwise become new issues. Returns a
    `ScanSummary` whose four tuples are disjoint (each event appears in
    exactly one bucket) so the prompt can comment on / file / batch the
    right slice.
    """
    new_issues: list[Mapping[str, Any]] = []
    deduped: list[Mapping[str, Any]] = []
    skipped: list[Mapping[str, Any]] = []
    critical: list[Mapping[str, Any]] = []

    for event in events:
        decision = incident_decision(event)
        record = dict(event)
        record["_decision"] = decision.decision
        if decision.incident_slug:
            record["_incident_slug"] = decision.incident_slug
        if decision.decision == "escalate_critical":
            critical.append(record)
        elif decision.decision == "comment_existing":
            deduped.append(record)
        elif decision.decision in {"skip", "skip_known"}:
            skipped.append(record)
        else:
            new_issues.append(record)

    batch_items: tuple[Mapping[str, Any], ...] = ()
    batch_slug: str | None = None
    if len(new_issues) > cap:
        if not scan_slug:
            raise ValueError(
                f"scan_summary received {len(new_issues)} new issues > cap={cap} "
                "but no scan_slug was provided to batch the overflow"
            )
        batch_items = tuple(new_issues[cap:])
        new_issues = new_issues[:cap]
        batch_slug = scan_slug

    return ScanSummary(
        new_issues=tuple(new_issues),
        deduped=tuple(deduped),
        skipped=tuple(skipped),
        batch_slug=batch_slug,
        batch_items=batch_items,
        critical=tuple(critical),
    )


def render_decision_summary(
    env: Mapping[str, str | None],
    events: Sequence[Mapping[str, Any]],
    *,
    scan_slug: str | None = None,
    cap: int = DEFAULT_NEW_ISSUE_CAP,
) -> dict[str, Any]:
    probe = qa_runtime_probe(env)
    summary = scan_summary(events, scan_slug=scan_slug, cap=cap)
    return {
        "runtime": {
            "status": probe.status,
            "missing_env": list(probe.missing_env),
            "missing_path_fragments": list(probe.missing_path_fragments),
            "maintenance_slug": probe.maintenance_slug,
        },
        "counts": {
            "new_issues": len(summary.new_issues),
            "deduped": len(summary.deduped),
            "skipped": len(summary.skipped),
            "critical": len(summary.critical),
            "batched": len(summary.batch_items),
        },
        "batch_slug": summary.batch_slug,
        "deduped_slugs": sorted(
            {e.get("_incident_slug") for e in summary.deduped if e.get("_incident_slug")}
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run helper for the QA runtime probe + incident-dedupe "
            "contract. Prints the decision a real wake would make."
        )
    )
    parser.add_argument("--events", help="Path to events JSON list, '-' for stdin", required=True)
    parser.add_argument("--scan-slug", help="[scan:YYYY-MM-DD-HHmm] for batched overflow")
    parser.add_argument("--cap", type=int, default=DEFAULT_NEW_ISSUE_CAP)
    parser.add_argument("--env", help="Path to env JSON (mapping of env-var → value)")
    args = parser.parse_args(argv)

    events_blob = (
        json.load(sys.stdin)
        if args.events == "-"
        else json.loads(open(args.events, "r", encoding="utf-8").read())
    )
    if isinstance(events_blob, Mapping):
        events_blob = events_blob.get("events") or []
    if not isinstance(events_blob, list):
        parser.error("events JSON must be a list of objects")

    if args.env:
        with open(args.env, "r", encoding="utf-8") as fh:
            env = json.load(fh)
    else:
        env = {name: "" for name in REQUIRED_ENV_VARS}
    if not isinstance(env, Mapping):
        parser.error("env JSON must be a mapping of env-var → value")

    summary = render_decision_summary(env, events_blob, scan_slug=args.scan_slug, cap=args.cap)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
