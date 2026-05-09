#!/usr/bin/env python3
"""Backlog hygiene classifier for open Paperclip issues.

Classifies open issues into the eight backlog classes named in
`specs/paperclip-architecture-ralphex-plan.md` Task 9, then derives a
closure decision per issue. Auto-close is gated to four "safe" classes
that each require an explicit proof artifact:

    merged_pr_parent       — `[pr:NNN]` issue whose PR is MERGED on GitHub.
    duplicate              — same canonical slug as a still-open canonical
                              issue (e.g. several `[maintenance:access-…]`
                              against the same agent).
    superseded             — explicit "superseded by FFM-…" comment naming
                              an open or closed successor.
    stale_report           — `[report:family-DATE]` whose family already has
                              a newer report; only the newest is kept.

Everything else falls through to `leave_open` or `needs_human` so that
strategic, product, experiment, active-implementation, approval-waiting,
and access-blocked issues are never closed by accident.

The module is pure: no Paperclip API, no `gh`, no env reads. Callers
hand in already-fetched issue dicts plus a `BacklogContext` carrying
external proof (merged PR numbers, the latest report per family, the
canonical maintenance slug per agent). Tests in
`tests/test_paperclip_backlog_hygiene.py`.

Contract surface
----------------

- `BACKLOG_CLASSES` — tuple of every class label `classify_issue` may
  emit. Stable for JSON consumers.
- `AUTO_CLOSE_CLASSES` / `NEVER_AUTO_CLOSE_CLASSES` — closure-decision
  guard rails. The intersection is empty, the union is `BACKLOG_CLASSES`.
- `BacklogContext` — external evidence the classifier needs.
- `classify_issue(issue, *, context)` — returns a `Classification` with
  the chosen class, a one-line reason, and any proof keys.
- `closure_decision(issue, classification, *, context)` — returns a
  `ClosureDecision` with action / reason / proof.
- `build_report(issues, *, context)` — runs both passes and returns a
  ledger dict ready for JSON output. Idempotent: same input → same
  output (lists are sorted on identifier).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_contracts import issue_slug as bracket_class  # noqa: E402
from paperclip_contracts import parse_bracket_slug  # noqa: E402

BACKLOG_CLASSES: tuple[str, ...] = (
    "duplicate",
    "superseded",
    "stale_report",
    "active_implementation",
    "approval_waiting",
    "access_blocked",
    "merged_pr_parent",
    "strategic_product",
    "unknown",
)

# Classes the closure-decision pass may auto-close. Each requires an
# explicit proof artifact in the `Classification.proof` mapping.
AUTO_CLOSE_CLASSES: frozenset[str] = frozenset(
    {"merged_pr_parent", "duplicate", "superseded", "stale_report"}
)

# Classes that must never be auto-closed by this script. Any of these
# returns `leave_open` from `closure_decision`.
NEVER_AUTO_CLOSE_CLASSES: frozenset[str] = frozenset(BACKLOG_CLASSES) - AUTO_CLOSE_CLASSES

OPEN_STATUSES: frozenset[str] = frozenset(
    {"backlog", "todo", "in_progress", "in_review", "blocked"}
)
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "cancelled"})

CLOSURE_ACTIONS: tuple[str, ...] = ("auto_close", "leave_open", "needs_human")

# Bracket slugs whose semantics are inherently strategic/product/
# experiment work — never auto-close from this script.
STRATEGIC_BRACKET_CLASSES: frozenset[str] = frozenset({"strategy", "experiment"})

# Maintenance slug prefix used by the per-agent runtime probe. Multiple
# `[maintenance:access-<agent>]` issues for the same agent collapse to
# the canonical one (whichever appears first in `context.canonical_slugs`).
MAINTENANCE_ACCESS_SLUG_RE = re.compile(r"^\[maintenance:access-([a-z0-9][a-z0-9-]*)\]")

# Reports use a `[report:family-YYYY-MM-DD]` shape; family is everything
# before the ISO date suffix. We separate them so a fresher report
# supersedes the older one for the same family.
REPORT_SLUG_RE = re.compile(
    r"^\[report:([a-z0-9][a-z0-9_-]*?)-(\d{4}-\d{2}-\d{2})\]",
    re.IGNORECASE,
)

# Free-form "superseded by FFM-NNN" / "superseded by [post:...]" comment
# detector. The captured group is the successor identifier, used as
# proof when closing.
SUPERSEDED_BY_RE = re.compile(
    r"superseded\s+by\s+(\[[^\]]+\]|FFM-\d+|#\d+)",
    re.IGNORECASE,
)

APPROVAL_WAITING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bawaiting approval\b", re.IGNORECASE),
    re.compile(r"\bpending approval\b", re.IGNORECASE),
    re.compile(r"\boutcome\s*=\s*draft_created\b", re.IGNORECASE),
    re.compile(r"\bAPPROVED_TO_PUBLISH\b"),
    re.compile(r"\brequest_confirmation\b", re.IGNORECASE),
)

ACCESS_BLOCKED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bmissing\s+(?:env|secret|token|access|role)\b", re.IGNORECASE),
    re.compile(r"\bblocked_without_access\b", re.IGNORECASE),
    re.compile(r"\b401\s+unauthorized\b", re.IGNORECASE),
    re.compile(r"\b403\s+forbidden\b", re.IGNORECASE),
    re.compile(r"\bpermission denied\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class BacklogContext:
    """External evidence the classifier consults.

    All fields are pre-collected by the caller so this module stays
    free of network/I/O. Each field is intentionally narrow:

      `merged_pr_numbers`   — set of PR numbers already MERGED on GitHub.
                              Drives `merged_pr_parent`.
      `latest_report_dates` — `family → ISO date string` of the newest
                              report seen across the open backlog. A
                              report whose date is older than the family
                              entry is `stale_report`.
      `canonical_access_slugs` — `agent → identifier` of the canonical
                              `[maintenance:access-<agent>]` issue. Other
                              issues with the same agent slug are
                              `duplicate`. Callers typically pull this
                              from `paperclip_runtime_probe.build_report`.
      `known_identifiers`   — every identifier the caller has seen, used
                              to validate "superseded by FFM-…" proofs
                              before closing.
    """

    merged_pr_numbers: frozenset[int] = frozenset()
    latest_report_dates: Mapping[str, str] = field(default_factory=dict)
    canonical_access_slugs: Mapping[str, str] = field(default_factory=dict)
    known_identifiers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Classification:
    """Result of `classify_issue` for a single issue.

    `proof` carries the artifact the closure-decision pass needs:
      - `merged_pr_parent`: `{"pr_number": int}`
      - `duplicate`:        `{"canonical": "FFM-…"}`
      - `superseded`:       `{"successor": "FFM-… | [post:…]"}`
      - `stale_report`:     `{"family": "...", "latest": "YYYY-MM-DD",
                              "this": "YYYY-MM-DD"}`
    """

    backlog_class: str
    reason: str
    proof: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClosureDecision:
    """Closure-pass output for the ledger.

    `action` is one of `CLOSURE_ACTIONS`. `proof` echoes the
    classifier's proof so the ledger row is self-contained.
    """

    action: str
    reason: str
    proof: Mapping[str, Any] = field(default_factory=dict)


# --- helpers ----------------------------------------------------------------


def _comment_bodies(issue: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for c in issue.get("comments") or []:
        if isinstance(c, Mapping):
            body = c.get("body")
            if isinstance(body, str):
                out.append(body)
    return out


def _all_text(issue: Mapping[str, Any]) -> str:
    parts = [issue.get("title") or "", issue.get("description") or ""]
    parts.extend(_comment_bodies(issue))
    return "\n".join(p for p in parts if p)


def _pr_number_from_slug(title: str | None) -> int | None:
    parsed = parse_bracket_slug(title or "")
    if not parsed:
        return None
    if parsed[0] != "pr":
        return None
    try:
        return int(parsed[1])
    except (TypeError, ValueError):
        return None


def _maintenance_access_agent(title: str | None) -> str | None:
    if not title:
        return None
    match = MAINTENANCE_ACCESS_SLUG_RE.match(title.strip().lower())
    return match.group(1) if match else None


def _report_family_and_date(title: str | None) -> tuple[str, str] | None:
    if not title:
        return None
    match = REPORT_SLUG_RE.match(title.strip().lower())
    if not match:
        return None
    return match.group(1), match.group(2)


def _is_strategic(issue: Mapping[str, Any]) -> bool:
    cls = bracket_class(issue.get("title") or "")
    return cls in STRATEGIC_BRACKET_CLASSES


def _superseded_successor(issue: Mapping[str, Any]) -> str | None:
    """Return the successor identifier if a comment names one."""
    for body in _comment_bodies(issue):
        match = SUPERSEDED_BY_RE.search(body)
        if match:
            return match.group(1)
    description = issue.get("description") or ""
    match = SUPERSEDED_BY_RE.search(description)
    if match:
        return match.group(1)
    return None


def _has_approval_waiting_signal(text: str) -> bool:
    return any(p.search(text) for p in APPROVAL_WAITING_PATTERNS)


def _has_access_blocked_signal(text: str) -> bool:
    return any(p.search(text) for p in ACCESS_BLOCKED_PATTERNS)


def _is_active_implementation(issue: Mapping[str, Any]) -> bool:
    """Conservative active-impl signal.

    Returns True only when the issue is in an actively-worked status
    AND has either an assignee or a non-empty `currentAgentId` /
    `assignedAgentId` field. The caller's job is to bail out before
    auto-closing — over-flagging here is harmless because all paths
    converge on `leave_open`.
    """
    if issue.get("status") not in {"in_progress", "in_review"}:
        return False
    for key in ("assignedAgentId", "currentAgentId", "assigneeId"):
        if issue.get(key):
            return True
    if issue.get("assignee"):
        return True
    return False


# --- classification ---------------------------------------------------------


def classify_issue(
    issue: Mapping[str, Any],
    *,
    context: BacklogContext,
) -> Classification:
    """Pick the single best-fit backlog class for `issue`.

    Order matters. Strategic/product comes first so an
    `[experiment:...]` titled issue is never classified as
    `active_implementation` even if it has an assignee. Merged-PR
    parent comes next because it has the strongest external proof.
    Duplicate / stale_report / superseded follow because each carries
    its own proof artifact. Approval / access / active are the
    `leave_open` family. Everything else falls to `unknown`.
    """
    title = issue.get("title") or ""

    if _is_strategic(issue):
        return Classification(
            backlog_class="strategic_product",
            reason="Strategic / experiment slug — never auto-close",
        )

    pr_number = _pr_number_from_slug(title)
    if pr_number is not None and pr_number in context.merged_pr_numbers:
        return Classification(
            backlog_class="merged_pr_parent",
            reason=f"Parent of PR #{pr_number} which is already MERGED on GitHub",
            proof={"pr_number": pr_number},
        )

    successor = _superseded_successor(issue)
    if successor and successor in context.known_identifiers:
        return Classification(
            backlog_class="superseded",
            reason=f"Comment names successor {successor}",
            proof={"successor": successor},
        )

    agent = _maintenance_access_agent(title)
    if agent:
        canonical = context.canonical_access_slugs.get(agent)
        ident = issue.get("identifier")
        if canonical and ident and canonical != ident:
            return Classification(
                backlog_class="duplicate",
                reason=(
                    f"Maintenance-access issue duplicate for agent {agent!r}; "
                    f"canonical is {canonical}"
                ),
                proof={"canonical": canonical, "agent": agent},
            )
        return Classification(
            backlog_class="access_blocked",
            reason=f"Canonical maintenance-access issue for agent {agent!r}",
        )

    report = _report_family_and_date(title)
    if report:
        family, this_date = report
        latest = context.latest_report_dates.get(family)
        if latest and latest > this_date:
            return Classification(
                backlog_class="stale_report",
                reason=(
                    f"Report family {family!r} has a newer report "
                    f"({latest}) than this one ({this_date})"
                ),
                proof={"family": family, "latest": latest, "this": this_date},
            )

    text = _all_text(issue)

    # `[post:...]` issues that surface a request_confirmation marker are
    # approval-waiting regardless of status; otherwise comment text
    # decides.
    if _has_approval_waiting_signal(text):
        return Classification(
            backlog_class="approval_waiting",
            reason="Issue text shows a pending approval / confirmation card",
        )

    if _has_access_blocked_signal(text):
        return Classification(
            backlog_class="access_blocked",
            reason="Issue text reports a missing env / token / role",
        )

    if _is_active_implementation(issue):
        return Classification(
            backlog_class="active_implementation",
            reason=f"Status={issue.get('status')!r} with an assigned agent",
        )

    return Classification(
        backlog_class="unknown",
        reason="No backlog-class signal matched — leave for a human",
    )


# --- closure decision -------------------------------------------------------


def closure_decision(
    issue: Mapping[str, Any],
    classification: Classification,
    *,
    context: BacklogContext,
) -> ClosureDecision:
    """Map a `Classification` to one of `CLOSURE_ACTIONS`.

    Auto-close fires only when:
      1. `classification.backlog_class` ∈ `AUTO_CLOSE_CLASSES`.
      2. The classifier produced the proof artifact required for that
         class. Missing proof → `needs_human` so the operator can
         eyeball the case.
    """
    cls = classification.backlog_class

    if issue.get("status") in TERMINAL_STATUSES:
        return ClosureDecision(
            action="leave_open",
            reason="Issue is already terminal — nothing to close",
            proof=dict(classification.proof),
        )

    if cls in NEVER_AUTO_CLOSE_CLASSES:
        return ClosureDecision(
            action="leave_open",
            reason=classification.reason,
            proof=dict(classification.proof),
        )

    if cls not in AUTO_CLOSE_CLASSES:
        # Defensive: should be impossible because the union covers every
        # class, but keep the check so a future class addition fails
        # closed.
        return ClosureDecision(
            action="needs_human",
            reason=f"Unknown closure rule for class {cls!r}",
            proof=dict(classification.proof),
        )

    proof = dict(classification.proof)

    if cls == "merged_pr_parent":
        if proof.get("pr_number") not in context.merged_pr_numbers:
            return ClosureDecision(
                action="needs_human",
                reason="Merged-PR proof did not round-trip against context",
                proof=proof,
            )

    if cls == "duplicate":
        canonical = proof.get("canonical")
        if not canonical or canonical == issue.get("identifier"):
            return ClosureDecision(
                action="needs_human",
                reason="Duplicate proof missing or self-referential",
                proof=proof,
            )

    if cls == "superseded":
        successor = proof.get("successor")
        if not successor or successor not in context.known_identifiers:
            return ClosureDecision(
                action="needs_human",
                reason="Superseded successor not visible in known_identifiers",
                proof=proof,
            )

    if cls == "stale_report":
        family = proof.get("family")
        latest = proof.get("latest")
        this = proof.get("this")
        if not family or not latest or not this or latest <= this:
            return ClosureDecision(
                action="needs_human",
                reason="Stale-report proof inconsistent (latest must be > this)",
                proof=proof,
            )

    return ClosureDecision(
        action="auto_close",
        reason=classification.reason,
        proof=proof,
    )


# --- report -----------------------------------------------------------------


def _open_subset(issues: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [i for i in issues if i.get("status") in OPEN_STATUSES]


def derive_report_context_from_issues(
    issues: Iterable[Mapping[str, Any]],
    *,
    base: BacklogContext | None = None,
) -> BacklogContext:
    """Convenience: walk `issues` and pre-fill `latest_report_dates` and
    `known_identifiers` so a caller doesn't have to compute them twice.

    Anything passed in `base` wins; only the missing fields are
    derived. Useful for dry-run and tests.
    """
    base = base or BacklogContext()
    latest: dict[str, str] = dict(base.latest_report_dates)
    idents: set[str] = set(base.known_identifiers)
    for issue in issues:
        ident = issue.get("identifier")
        if isinstance(ident, str):
            idents.add(ident)
        report = _report_family_and_date(issue.get("title") or "")
        if report:
            family, date_str = report
            current = latest.get(family)
            if not current or date_str > current:
                latest[family] = date_str
    return BacklogContext(
        merged_pr_numbers=base.merged_pr_numbers,
        latest_report_dates=latest,
        canonical_access_slugs=base.canonical_access_slugs,
        known_identifiers=frozenset(idents),
    )


def build_report(
    issues: Sequence[Mapping[str, Any]],
    *,
    context: BacklogContext | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run classification + closure-decision over `issues`.

    Returns a JSON-shaped ledger:

        {
          "generatedAt": "2026-…Z",
          "counts": {<class>: int, ...},
          "actionCounts": {"auto_close": int, "leave_open": int,
                           "needs_human": int},
          "rows": [
            {"identifier": "FFM-…", "status": "...", "class": "...",
             "action": "...", "reason": "...", "proof": {...}},
            ...
          ],
        }

    Idempotent for unchanged inputs: rows are sorted by identifier and
    every count maps to a stable class label.
    """
    context = context or derive_report_context_from_issues(issues)
    open_issues = _open_subset(issues)

    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {cls: 0 for cls in BACKLOG_CLASSES}
    action_counts: dict[str, int] = {action: 0 for action in CLOSURE_ACTIONS}

    for issue in open_issues:
        classification = classify_issue(issue, context=context)
        decision = closure_decision(issue, classification, context=context)
        counts[classification.backlog_class] += 1
        action_counts[decision.action] += 1
        rows.append(
            {
                "identifier": issue.get("identifier"),
                "status": issue.get("status"),
                "class": classification.backlog_class,
                "action": decision.action,
                "reason": decision.reason,
                "proof": dict(decision.proof),
            }
        )

    rows.sort(key=lambda r: (r["identifier"] or "", r["class"]))

    return {
        "generatedAt": (now or datetime.now(timezone.utc)).isoformat(),
        "counts": counts,
        "actionCounts": action_counts,
        "rows": rows,
    }


# --- CLI --------------------------------------------------------------------


def _load_json(path: str) -> Any:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run classifier for open Paperclip issues. Reads issue "
            "JSON + an optional context JSON and prints the closure "
            "ledger. Never mutates Paperclip."
        )
    )
    parser.add_argument(
        "--issues",
        required=True,
        help="Path to issues JSON list, '-' for stdin",
    )
    parser.add_argument(
        "--context",
        help=(
            "Path to context JSON with optional keys "
            "'merged_pr_numbers', 'latest_report_dates', "
            "'canonical_access_slugs', 'known_identifiers'"
        ),
    )
    args = parser.parse_args(argv)

    issues_blob = _load_json(args.issues)
    if isinstance(issues_blob, Mapping):
        issues_blob = issues_blob.get("issues") or []
    if not isinstance(issues_blob, list):
        parser.error("issues JSON must be a list of issue objects")

    context: BacklogContext | None = None
    if args.context:
        ctx_raw = _load_json(args.context)
        if not isinstance(ctx_raw, Mapping):
            parser.error("context JSON must be an object")
        context = BacklogContext(
            merged_pr_numbers=frozenset(int(n) for n in ctx_raw.get("merged_pr_numbers") or []),
            latest_report_dates=dict(ctx_raw.get("latest_report_dates") or {}),
            canonical_access_slugs=dict(ctx_raw.get("canonical_access_slugs") or {}),
            known_identifiers=frozenset(ctx_raw.get("known_identifiers") or []),
        )

    report = build_report(issues_blob, context=context)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
