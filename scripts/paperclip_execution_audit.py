#!/usr/bin/env python3
"""Map Paperclip issues + comments to the six evidence classes.

Classes (from `specs/paperclip-architecture-ralphex-plan.md` Audit Sequence):

    stopped           — open issue idle past the threshold with no concrete
                        owner/next-action signal.
    looping           — agent re-created near-duplicate issues, or a single
                        issue accumulated retry comments with no progress.
    fake_green        — issue closed `done` while a referenced FFM-* child or
                        a publish-flow marker is still non-terminal.
    missing_access    — comments name an env var / token / permission gap.
    stale_instruction — comments reference a deprecated tool, old container,
                        or pinned Paperclip/GStack version that drifted.
    outcome_gap       — issue completed but no `outcome=...` event exists in
                        comments or the experiments log.

The classifier is pure: every heuristic operates on dicts the caller hands
in. `main()` is the only side-effecting entry point. Tests in
`tests/test_paperclip_execution_audit.py` exercise the pure functions
without spinning up a Paperclip client.

Env (only consumed by `main`, not by classifier helpers):
  PAPERCLIP_API_URL (preferred in Paperclip runtime) or PAPERCLIP_URL
  PAPERCLIP_API_KEY
  PAPERCLIP_COMPANY_ID (optional; defaults to the FFmemes prod company)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from paperclip_contracts import (
        DECISION_ACTIONS,
        OUTCOME_ACTIONS,
    )
    from paperclip_http import (
        PaperclipClient,
        parse_ts,
        redact,
        require_credentials,
    )
except ModuleNotFoundError:
    from scripts.paperclip_contracts import (
        DECISION_ACTIONS,
        OUTCOME_ACTIONS,
    )
    from scripts.paperclip_http import (
        PaperclipClient,
        parse_ts,
        redact,
        require_credentials,
    )

DEFAULT_COMPANY_ID = "96ee7b2e-6df2-43c8-bbe3-53e19297308a"
ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "experiments" / "log.jsonl"

OPEN_STATUSES = {"backlog", "todo", "in_progress", "in_review", "blocked"}
TERMINAL_STATUSES = {"done", "cancelled"}
ALL_STATUSES = "backlog,todo,in_progress,in_review,blocked,done,cancelled"

EVIDENCE_CLASSES = (
    "stopped",
    "looping",
    "fake_green",
    "missing_access",
    "stale_instruction",
    "outcome_gap",
)

# Substring markers that indicate the comment is reporting a concrete missing
# capability, not just discussing one. Anchored to lowercased text.
MISSING_ACCESS_MARKERS = (
    "missing env",
    "missing secret",
    "missing token",
    "no token configured",
    "permission denied",
    "forbidden",
    "401 unauthorized",
    "401 ",
    "403 ",
    "403 forbidden",
    "no access to",
    "could not authenticate",
    "set $",  # "set $PAPERCLIP_API_KEY"
    "env var ",
    "$paperclip_",
    "$telegram_",
    "$openrouter",
)

# Substring markers that an instruction/version/skill is stale relative to
# the current pinned Paperclip / GStack ref. Keep additive — do not list
# individual deprecated skill names here; that surface should live next to
# the pinning manifest.
STALE_INSTRUCTION_MARKERS = (
    "deprecated skill",
    "skill not found",
    "skills no longer in upstream",
    "stale ref",
    "stale spec",
    "container name changed",
    "old container",
    "outdated paperclip version",
    "paperclip update available",
    "gstack update available",
    "0 updated",
    "raw trigger url",
    "ssh path",
)

# Built from `paperclip_contracts.OUTCOME_ACTIONS` so this audit and the
# outcome audit count the same set of structured outcome events. The
# generic `outcome=...` regex catches free-form comments.
OUTCOME_MARKERS = (re.compile(r"\boutcome\s*=\s*[a-z0-9_]+", re.IGNORECASE),) + tuple(
    re.compile(rf"\b{re.escape(action)}\b", re.IGNORECASE)
    for action in sorted(OUTCOME_ACTIONS | DECISION_ACTIONS)
)

REFERENCED_FFM_RE = re.compile(r"\bFFM-\d+\b")
RETRY_MARKERS = (
    "retrying",
    "retry attempt",
    "same failure",
    "repeated failure",
    "again failed",
)


def _now_utc() -> datetime:
    """Indirection so tests can pin a stable `now` via the `now` parameter."""
    return datetime.now(timezone.utc)


def _last_activity(issue: dict[str, Any], comments: Iterable[dict[str, Any]]) -> datetime | None:
    candidates: list[datetime] = []
    for key in ("updatedAt", "startedAt", "completedAt", "createdAt"):
        ts = parse_ts(issue.get(key))
        if ts is not None:
            candidates.append(ts)
    for c in comments:
        ts = parse_ts(c.get("createdAt"))
        if ts is not None:
            candidates.append(ts)
    return max(candidates) if candidates else None


def _comment_bodies(comments: Iterable[dict[str, Any]]) -> str:
    return "\n".join((c.get("body") or "") for c in comments)


def _all_text(issue: dict[str, Any], comments: Iterable[dict[str, Any]]) -> str:
    return "\n".join(
        [issue.get("title") or "", issue.get("description") or "", _comment_bodies(comments)]
    )


def _has_outcome_marker(text: str) -> bool:
    return any(p.search(text) for p in OUTCOME_MARKERS)


def _stopped_signal(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    now: datetime,
    threshold: timedelta,
) -> dict[str, Any] | None:
    status = issue.get("status")
    if status not in OPEN_STATUSES:
        return None
    last = _last_activity(issue, comments)
    if not last:
        # Issue exists with no parsable timestamps anywhere — treat as stopped
        # with a clear "no_activity_signal" reason rather than silently
        # passing.
        return {"reason": "no_activity_signal", "idleHours": None}
    idle = now - last
    if idle < threshold:
        return None
    return {
        "reason": "idle_past_threshold",
        "idleHours": round(idle.total_seconds() / 3600, 1),
    }


def _missing_access_signal(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    hits = [marker for marker in MISSING_ACCESS_MARKERS if marker in lowered]
    if not hits:
        return None
    # Surface at most three distinct markers so the report stays compact and
    # there's no risk of an issue body itself being echoed back.
    return {"markers": sorted(set(hits))[:3]}


def _stale_instruction_signal(text: str) -> dict[str, Any] | None:
    lowered = text.lower()
    hits = [marker for marker in STALE_INSTRUCTION_MARKERS if marker in lowered]
    if not hits:
        return None
    return {"markers": sorted(set(hits))[:3]}


def _outcome_gap_signal(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    log_outcome_ids: set[str],
) -> dict[str, Any] | None:
    if issue.get("status") != "done":
        return None
    text = _all_text(issue, comments)
    if _has_outcome_marker(text):
        return None
    issue_ident = issue.get("identifier")
    if issue_ident and issue_ident in log_outcome_ids:
        return None
    return {"reason": "no_outcome_marker"}


def _fake_green_signal(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    issues_by_identifier: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    if issue.get("status") not in TERMINAL_STATUSES:
        return None
    text = _all_text(issue, comments)
    referenced = sorted(set(REFERENCED_FFM_RE.findall(text)))
    self_ident = issue.get("identifier")
    non_terminal: list[str] = []
    for ident in referenced:
        if self_ident and ident == self_ident:
            continue
        ref = issues_by_identifier.get(ident)
        # If we can't see the referenced issue at all, don't fire — we'd be
        # guessing. The routine audit owns the publish-flow specific check;
        # this is the generic "closed parent, open child" detector.
        if ref is None:
            continue
        if ref.get("status") not in TERMINAL_STATUSES:
            non_terminal.append(ident)
    if not non_terminal:
        return None
    return {"reason": "child_non_terminal", "children": non_terminal[:5]}


def _looping_signal_per_issue(
    comments: list[dict[str, Any]],
    *,
    threshold: int = 3,
) -> dict[str, Any] | None:
    body = " ".join((c.get("body") or "") for c in comments).lower()
    hits = [marker for marker in RETRY_MARKERS if marker in body]
    # Only count retries when there are at least `threshold` distinct retry-style
    # signals (or one marker repeated across `threshold` comments).
    retry_comments = sum(
        1
        for c in comments
        if any(marker in (c.get("body") or "").lower() for marker in RETRY_MARKERS)
    )
    if retry_comments < threshold and not hits:
        return None
    if retry_comments < threshold:
        return None
    return {
        "reason": "retry_loop",
        "retryComments": retry_comments,
        "markers": sorted(set(hits))[:3],
    }


def _looping_signal_across_issues(
    issues: list[dict[str, Any]], *, threshold: int = 3
) -> list[dict[str, Any]]:
    """Detect duplicate issue creation by `(creatorAgentId, normalized_title)`.

    Only fire when the same agent created `threshold` or more issues whose
    titles collapse to the same key — that's the signature of an agent that
    keeps re-opening the same problem instead of resolving it.
    """
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        creator = issue.get("createdByAgentId") or "unknown"
        title = (issue.get("title") or "").strip()
        # Strip trailing date / counter suffixes that some templates append.
        normalized = re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$", "", title.lower())
        normalized = re.sub(r"\s+#\d+\s*$", "", normalized)
        if not normalized:
            continue
        grouped[(creator, normalized)].append(issue)
    out: list[dict[str, Any]] = []
    for (creator, normalized), group in grouped.items():
        if len(group) < threshold:
            continue
        out.append(
            {
                "creatorAgentId": creator,
                "normalizedTitle": normalized,
                "count": len(group),
                "identifiers": [g.get("identifier") for g in group][:10],
            }
        )
    return out


def classify_issue(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    *,
    issues_by_identifier: dict[str, dict[str, Any]],
    log_outcome_ids: set[str],
    now: datetime,
    stopped_threshold: timedelta = timedelta(hours=24),
) -> dict[str, Any]:
    """Return the evidence classes that apply to a single issue.

    The result is a flat dict so JSON consumers can render it directly. Each
    class key is present only when the heuristic fired; absence means
    "no signal." That asymmetry keeps the JSON ledger compact.
    """
    text = _all_text(issue, comments)
    classes: dict[str, Any] = {}
    if signal := _stopped_signal(issue, comments, now=now, threshold=stopped_threshold):
        classes["stopped"] = signal
    if signal := _missing_access_signal(text):
        classes["missing_access"] = signal
    if signal := _stale_instruction_signal(text):
        classes["stale_instruction"] = signal
    if signal := _fake_green_signal(issue, comments, issues_by_identifier=issues_by_identifier):
        classes["fake_green"] = signal
    if signal := _outcome_gap_signal(issue, comments, log_outcome_ids=log_outcome_ids):
        classes["outcome_gap"] = signal
    if signal := _looping_signal_per_issue(comments):
        classes["looping"] = signal
    return classes


def load_log_outcome_ids(log_path: Path = LOG_PATH) -> set[str]:
    """Pull `issue_identifier` markers out of `experiments/log.jsonl`.

    Anything an agent recorded as a structured outcome counts as evidence that
    the matching issue was actually decisioned, even if the issue itself
    forgot to comment `outcome=...`.
    """
    if not log_path.exists():
        return set()
    out: set[str] = set()
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        details = entry.get("details") or {}
        if isinstance(details, dict):
            ident = details.get("issue_identifier") or details.get("issue")
            if isinstance(ident, str):
                out.add(ident)
    return out


def build_report(
    issues: list[dict[str, Any]],
    comments_by_id: dict[str, list[dict[str, Any]]],
    *,
    log_outcome_ids: set[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or _now_utc()
    by_identifier = {i.get("identifier"): i for i in issues if i.get("identifier")}
    rows: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    for issue in issues:
        classes = classify_issue(
            issue,
            comments_by_id.get(issue.get("id") or "", []),
            issues_by_identifier=by_identifier,
            log_outcome_ids=log_outcome_ids,
            now=now,
        )
        if not classes:
            continue
        for cls in classes:
            counter[cls] += 1
        rows.append(
            {
                "identifier": issue.get("identifier"),
                "status": issue.get("status"),
                "title": redact(issue.get("title") or "", limit=160),
                "classes": classes,
            }
        )
    looping_groups = _looping_signal_across_issues(issues)
    if looping_groups:
        # Cross-issue loop counts go into the same bucket so callers see one
        # number per evidence class.
        counter["looping"] += sum(g["count"] for g in looping_groups)
    return {
        "generatedAt": now.isoformat(),
        "counts": {cls: counter.get(cls, 0) for cls in EVIDENCE_CLASSES},
        "issues": rows,
        "loopingGroups": looping_groups,
    }


def fetch_inputs(
    client: PaperclipClient, company_id: str, *, limit: int
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Live fetch path. Pure helpers above are what tests target."""
    issues, _trunc = client.paginate(
        f"/api/companies/{company_id}/issues",
        query={"status": ALL_STATUSES},
        limit=limit,
    )
    comments_by_id: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        issue_id = issue.get("id")
        if not issue_id:
            continue
        try:
            response = client.get(f"/api/issues/{issue_id}/comments", {"limit": "100"})
        except Exception as exc:  # noqa: BLE001 — degrade per-issue, not the whole audit
            print(
                f"warning: comments fetch failed for {issue.get('identifier')}: {exc}",
                file=sys.stderr,
            )
            continue
        if not isinstance(response, list):
            continue
        comments_by_id[issue_id] = [c for c in response if isinstance(c, dict)]
    return issues, comments_by_id


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company-id",
        default=os.getenv("PAPERCLIP_COMPANY_ID", DEFAULT_COMPANY_ID),
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    creds = require_credentials()
    if creds is None:
        print("Set PAPERCLIP_API_URL (or PAPERCLIP_URL) and PAPERCLIP_API_KEY", file=sys.stderr)
        return 2
    base_url, api_key = creds
    client = PaperclipClient(base_url, api_key, user_agent="ffmemes-paperclip-execution-audit/1.0")
    issues, comments_by_id = fetch_inputs(client, args.company_id, limit=args.limit)
    report = build_report(issues, comments_by_id, log_outcome_ids=load_log_outcome_ids())
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"paperclip_execution_audit generated_at={report['generatedAt']}")
        for cls, count in report["counts"].items():
            print(f"  {cls}: {count}")
        if report["loopingGroups"]:
            print()
            print("looping_groups:")
            for group in report["loopingGroups"]:
                print(
                    f"  creator={group['creatorAgentId']} count={group['count']} "
                    f"title={group['normalizedTitle']!r}"
                )
        if report["issues"]:
            print()
            print("issues:")
            for row in report["issues"]:
                classes = ",".join(sorted(row["classes"]))
                print(f"  {row['identifier']} [{row['status']}] {classes}: {row['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
