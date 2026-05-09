#!/usr/bin/env python3
"""Compact read-only audit for FFmemes-specific Paperclip routine outcomes.

This is intentionally narrow and business-focused: it turns routine
issues/comments into a small report of FFmemes outcome-contract mismatches
(post publication markers, update-check content, deploy verification,
gstack update path, draft handoff state, PR payload mismatch) so agents
do not spend context manually spelunking Paperclip JSON.

Generic liveness, stall / zombie-run detection, and no-comment classification
are intentionally NOT covered here — those are owned by Paperclip v2026.428+
productivity review / liveness recovery in the native runtime.

Env:
  PAPERCLIP_API_URL (preferred in Paperclip runtime) or PAPERCLIP_URL
  PAPERCLIP_API_KEY
  PAPERCLIP_COMPANY_ID (optional, defaults to FFmemes prod company)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from paperclip_contracts import (
    PUBLISHED_MARKERS as PUBLISHED_MARKER_PATTERNS,
)
from paperclip_contracts import (
    issue_slug,
    nested_state,
    parent_child_status_violation,
)
from paperclip_http import (
    PaperclipAPIError,
    PaperclipClient,
    paperclip_base_url,
    parse_ts,
    redact,
)

DEFAULT_COMPANY_ID = "96ee7b2e-6df2-43c8-bbe3-53e19297308a"
POST_RE = re.compile(r"FFM-\d+")
DEGRADED_PATTERNS = (
    "rate-limited",
    "transient failure",
    "persistent 404",
    "no local gstack install",
    "0 updated",
    "skills no longer in upstream",
)
INTERACTION_LIST_KEYS = ("interactions", "items", "data")
CONFIRMATION_KIND_MARKERS = ("confirmation", "request_confirmation")
ACCEPTED_MARKERS = {"accepted", "approved", "confirmed", "yes"}
VERIFIED_PAPERCLIP_DEPLOY_PATTERNS = (
    re.compile(r"\bverified_deployed_commit\b", re.IGNORECASE),
    re.compile(r"\bcoolify_deployment_commit\b", re.IGNORECASE),
    re.compile(r"\bactual_deployed_commit\b", re.IGNORECASE),
)


class Paperclip:
    """Backwards-compatible facade over the shared `PaperclipClient`.

    Preserves the `RuntimeError("HTTP {code} for {path}: ...")` shape so
    the audit's `message.startswith("HTTP 404 for ")` branches stay
    untouched.
    """

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = PaperclipClient(
            base_url,
            api_key,
            user_agent="ffmemes-paperclip-routine-audit/1.0",
        )
        self.base_url = self._client.base_url
        self.api_key = api_key

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        try:
            return self._client.get(path, query=query)
        except PaperclipAPIError as exc:
            raise RuntimeError(str(exc)) from exc


def minutes_between(start: str | None, end: str | None) -> float | None:
    a = parse_ts(start)
    b = parse_ts(end)
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60, 1)


def compact_body(body: str, limit: int = 240) -> str:
    return redact(body, limit=limit)


def issue_comments(client: Paperclip, issue_id: str) -> tuple[list[dict[str, Any]], bool]:
    # Mirror `issue_interactions` / `get_issue`: 404 = no comments yet
    # (expected, not degraded). Anything else (401, 5xx, transport, decode) is
    # audit-degraded — without comments we can lose approval signals
    # (`outcome=...`, `APPROVED_TO_PUBLISH`) and the publish-flow classifier
    # would silently pass instead of flagging `publish_check_degraded`. A
    # single failed comments fetch must not crash the whole audit.
    try:
        comments = client.get(f"/api/issues/{issue_id}/comments", {"limit": "100"})
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("HTTP 404 for "):
            return [], False
        print(
            f"warning: comments fetch degraded for {issue_id}: {message}",
            file=sys.stderr,
        )
        return [], True
    if not isinstance(comments, list):
        print(
            f"warning: comments response shape unrecognized for {issue_id}; treating as degraded",
            file=sys.stderr,
        )
        return [], True
    dict_items = [item for item in comments if isinstance(item, dict)]
    degraded = len(dict_items) != len(comments)
    if degraded:
        print(
            f"warning: comments list for {issue_id} contained "
            f"{len(comments) - len(dict_items)} non-dict element(s); "
            f"treating as degraded",
            file=sys.stderr,
        )
    return sorted(dict_items, key=lambda item: item.get("createdAt") or ""), degraded


def issue_interactions(client: Paperclip, issue_id: str) -> tuple[list[dict[str, Any]], bool]:
    # 404 = no interactions for this issue (expected, not degraded). Anything
    # else (401, 5xx, transport error, decode error) is audit-degraded: we
    # surface it on stderr AND return degraded=True so callers can flag the
    # issue in the JSON report. Without this, an approval-only publish flow
    # could lose its sole approval signal and silently skip
    # `approved_without_publish_marker`.
    try:
        interactions = client.get(f"/api/issues/{issue_id}/interactions", {"limit": "100"})
    except RuntimeError as exc:
        message = str(exc)
        # Anchor to the prefix `Paperclip.get` produces (`HTTP {code} for `) so a
        # 5xx whose response body happens to mention "HTTP 404" doesn't get
        # silently swallowed as "no interactions for this issue".
        if message.startswith("HTTP 404 for "):
            return [], False
        print(
            f"warning: interactions fetch degraded for {issue_id}: {message}",
            file=sys.stderr,
        )
        return [], True
    if isinstance(interactions, list):
        # Filter to dicts so downstream `.get()` calls can't crash on shape
        # drift (mixed-type lists). If anything was filtered out, surface it
        # as degraded rather than silently dropping interactions and risking
        # a missed approval signal.
        dict_items = [item for item in interactions if isinstance(item, dict)]
        if len(dict_items) != len(interactions):
            print(
                f"warning: interactions list for {issue_id} contained "
                f"{len(interactions) - len(dict_items)} non-dict element(s); "
                f"treating as degraded",
                file=sys.stderr,
            )
            return dict_items, True
        return dict_items, False
    if isinstance(interactions, dict):
        for key in INTERACTION_LIST_KEYS:
            value = interactions.get(key)
            if isinstance(value, list):
                dict_items = [item for item in value if isinstance(item, dict)]
                if len(dict_items) != len(value):
                    # Mirror the top-level-list branch: filtering non-dicts can
                    # silently drop an approval signal, so flag as degraded
                    # rather than returning a clean list.
                    print(
                        f"warning: interactions[{key}] for {issue_id} contained "
                        f"{len(value) - len(dict_items)} non-dict element(s); "
                        f"treating as degraded",
                        file=sys.stderr,
                    )
                    return dict_items, True
                return dict_items, False
    # Unexpected response shape (200 OK but neither a list nor a dict whose
    # known keys hold a list). Treat as degraded so approval-only `[post:...]`
    # issues surface `publish_check_degraded` instead of silently passing.
    print(
        f"warning: interactions response shape unrecognized for {issue_id}; treating as degraded",
        file=sys.stderr,
    )
    return [], True


def get_issue(client: Paperclip, issue_id: str) -> tuple[dict[str, Any] | None, bool]:
    # 404 = the issue id genuinely doesn't exist (expected in
    # `referenced_post_issues` where we probe FFM-XXX strings extracted from
    # text). Anything else (401, 5xx, transport, decode) is audit-degraded:
    # without the issue body we can't read the title and would silently lose
    # publish-flow detection (`title.startswith("[post:")`), masking
    # `approved_without_publish_marker` / `publish_check_degraded`.
    try:
        issue = client.get(f"/api/issues/{issue_id}")
    except RuntimeError as exc:
        message = str(exc)
        if message.startswith("HTTP 404 for "):
            return None, False
        print(
            f"warning: issue fetch degraded for {issue_id}: {message}",
            file=sys.stderr,
        )
        return None, True
    if isinstance(issue, dict):
        return issue, False
    # 200 OK but unexpected shape (list, string, None, etc). Treat as degraded
    # so we don't silently skip referenced [post:...] issues and lose
    # `publish_check_degraded` / `approved_without_publish_marker` signals.
    print(
        f"warning: issue response shape unrecognized for {issue_id}; treating as degraded",
        file=sys.stderr,
    )
    return None, True


def list_issues(
    client: Paperclip, company_id: str, status: str, limit: int = 200
) -> tuple[list[dict], bool]:
    # Returns (issues, truncated). Warn on shape drift instead of silently
    # returning [] — a wrapped 200 response would otherwise hide every
    # `[post:...]` draft with no signal to the caller. Also surface a
    # truncation flag when the page is full so consumers know there may be
    # more issues beyond what we read (the route does not paginate, so a
    # full page == "we don't know what we missed").
    issues = client.get(
        f"/api/companies/{company_id}/issues",
        {"status": status, "limit": str(limit)},
    )
    if not isinstance(issues, list):
        print(
            f"warning: list_issues got unexpected response shape "
            f"{type(issues).__name__}; treating as degraded",
            file=sys.stderr,
        )
        return [], True
    truncated = len(issues) >= limit
    if truncated:
        print(
            f"warning: list_issues hit limit={limit}; results may be truncated",
            file=sys.stderr,
        )
    return issues, truncated


def routine_matches(name: str, focus: str) -> bool:
    lower = name.lower()
    if focus == "all":
        return True
    if focus == "comms":
        return "channel post" in lower or "comms" in lower
    if focus == "updates":
        return "update check" in lower or "gstack" in lower or "paperclip" in lower
    return focus.lower() in lower


def interaction_value(interaction: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = interaction.get(key)
        if value is not None:
            return str(value).lower()
    return ""


def has_accepted_confirmation(interactions: list[dict[str, Any]]) -> bool:
    for interaction in interactions:
        kind = interaction_value(interaction, "kind", "type", "interactionType", "name")
        if not any(marker in kind for marker in CONFIRMATION_KIND_MARKERS):
            continue
        state = interaction_value(
            interaction,
            "status",
            "state",
            "outcome",
            "decision",
            "response",
            "answer",
            "value",
        )
        if state in ACCEPTED_MARKERS:
            return True
        if interaction.get("acceptedAt") or interaction.get("confirmedAt"):
            return True
        result = interaction.get("result")
        if isinstance(result, dict):
            result_state = interaction_value(
                result,
                "status",
                "state",
                "outcome",
                "decision",
                "response",
                "answer",
                "value",
            )
            if result_state in ACCEPTED_MARKERS:
                return True
    return False


def classify_issue(
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
    interactions: list[dict[str, Any]] | None = None,
    interactions_degraded: bool = False,
) -> tuple[list[str], str]:
    text = "\n".join([issue.get("description") or ""] + [c.get("body") or "" for c in comments])
    lower = text.lower()
    title = (issue.get("title") or "").lower()
    flags: list[str] = []
    if any(pattern in lower for pattern in DEGRADED_PATTERNS):
        flags.append("degraded_green")
    if "last deployed sha" in lower and "current master sha" in lower:
        if "latest stable" not in lower and "changelog" not in lower:
            flags.append("sha_only_update_check")
    if (
        "deployed paperclip update" in lower
        or "coolify deployment queued" in lower
        or "state file updated" in lower
        or "deployed paperclip" in lower
    ) and not any(pattern.search(text) for pattern in VERIFIED_PAPERCLIP_DEPLOY_PATTERNS):
        flags.append("unverified_paperclip_deploy")
    if "gstack-derived skills" in lower and "paperclip skills runtime" in lower:
        flags.append("unknown_gstack_update_path")
    if "draft issue exists" in lower or "awaiting ceo approval" in lower:
        flags.append("draft_handoff")
    is_publish_flow = (
        title.startswith("[post:")
        or "daily channel post" in title
        or "outcome=draft_created" in lower
        or "outcome=published" in lower
        or "ceo approval" in lower
    )
    has_approval_signal = "approved" in lower or has_accepted_confirmation(interactions or [])
    has_publish_marker = all(pattern.search(text) for pattern in PUBLISHED_MARKER_PATTERNS)
    if is_publish_flow and has_approval_signal and not has_publish_marker:
        flags.append("approved_without_publish_marker")
    elif is_publish_flow and interactions_degraded and not has_publish_marker:
        # We couldn't read interactions, so we can't tell if approval happened.
        # Surface that uncertainty rather than silently passing the issue.
        flags.append("publish_check_degraded")
    # Generic stall / no-comment / zombie-run classification is intentionally
    # delegated to Paperclip v2026.428+ productivity review and liveness
    # recovery; this audit only flags FFmemes business-outcome mismatches.
    latest = comments[-1].get("body", "") if comments else issue.get("description", "")
    return flags, compact_body(latest or "")


def derive_nested_state(
    ref: dict[str, Any],
    comments: list[dict[str, Any]],
) -> str:
    """Project an issue + its comments onto `paperclip_contracts.NESTED_STATES`.

    Used to surface `published` / `approved_unpublished` / `pending_approval`
    / `stale_draft` / `blocked_without_access` / `missing_smoke` /
    `merged_without_close` / `unknown` per referenced child so a routine
    cannot report green while a child is non-terminal.
    """
    text = "\n".join(
        [ref.get("title") or "", ref.get("description") or ""]
        + [c.get("body") or "" for c in comments]
    )
    return nested_state(text, slug=issue_slug(ref.get("title") or ""))


def referenced_post_issues(
    client: Paperclip,
    issue: dict[str, Any],
    comments: list[dict],
) -> list[dict]:
    text = "\n".join([issue.get("description") or ""] + [c.get("body") or "" for c in comments])
    found: list[dict] = []
    for ident in sorted(set(POST_RE.findall(text))):
        ref, ref_issue_degraded = get_issue(client, ident)
        if not ref:
            if ref_issue_degraded:
                # Issue fetch failed (5xx, transport, or shape drift). We can't
                # tell if this is a [post:...] issue or read its publish state,
                # so surface a degraded entry instead of silently dropping it.
                found.append(
                    {
                        "identifier": ident,
                        "title": None,
                        "status": None,
                        "assigneeAgentId": None,
                        "updatedAt": None,
                        "flags": ["publish_check_degraded"],
                        "nestedState": "unknown",
                        "latest": "",
                    }
                )
            continue
        if not (ref.get("title") or "").startswith("[post:"):
            continue
        ref_comments, ref_comments_degraded = issue_comments(client, ref["id"])
        ref_interactions, ref_degraded = issue_interactions(client, ref["id"])
        flags, latest = classify_issue(
            ref,
            ref_comments,
            ref_interactions,
            ref_degraded or ref_issue_degraded or ref_comments_degraded,
        )
        found.append(
            {
                "identifier": ref.get("identifier"),
                "title": ref.get("title"),
                "status": ref.get("status"),
                "assigneeAgentId": ref.get("assigneeAgentId"),
                "updatedAt": ref.get("updatedAt"),
                "flags": flags,
                "nestedState": derive_nested_state(ref, ref_comments),
                "latest": latest,
            }
        )
    return found


def audit_routines(client: Paperclip, company_id: str, focus: str) -> list[dict[str, Any]]:
    routines = client.get(f"/api/companies/{company_id}/routines")
    if not isinstance(routines, list):
        # Mirror list_issues: warn instead of raising. A wrapped/shape-drifted
        # 200 from /api/companies/<id>/routines used to crash the whole audit,
        # which means a single API drift wiped all routine signal from the
        # JSON report — a strictly worse failure mode than "no routines found".
        print(
            f"warning: audit_routines got unexpected response shape "
            f"{type(routines).__name__}; treating as degraded",
            file=sys.stderr,
        )
        return []

    rows: list[dict[str, Any]] = []
    for routine in routines:
        if routine.get("status") != "active":
            continue
        name = routine.get("title") or routine.get("name") or ""
        if not routine_matches(name, focus):
            continue
        run = routine.get("lastRun") or {}
        linked = run.get("linkedIssue") or {}
        issue_id = run.get("linkedIssueId")
        if issue_id:
            issue, issue_degraded = get_issue(client, issue_id)
        else:
            issue, issue_degraded = None, False
        if issue_id:
            comments, comments_degraded = issue_comments(client, issue_id)
            interactions, interactions_degraded = issue_interactions(client, issue_id)
        else:
            comments, comments_degraded = [], False
            interactions, interactions_degraded = [], False
        # When the issue fetch is degraded, fall back to the routine's embedded
        # `linkedIssue` so publish-flow detection (driven by title prefix) still
        # fires, and propagate the degradation so we surface
        # `publish_check_degraded` instead of silently passing.
        issue_for_classify = issue or (linked if issue_degraded else {})
        flags, latest = classify_issue(
            issue_for_classify,
            comments,
            interactions,
            interactions_degraded or issue_degraded or comments_degraded,
        )
        payload_pr = str(((run.get("triggerPayload") or {}).get("pr_number")) or "")
        issue_title = (
            ((run.get("linkedIssue") or {}).get("title")) or (issue or {}).get("title") or ""
        )
        if payload_pr and f"[pr:{payload_pr}]" not in issue_title:
            flags.append("coalesced_pr_review_mismatch")
        parent_status = linked.get("status") or (issue or {}).get("status")
        row = {
            "routine": name,
            "routineId": routine.get("id"),
            "runStatus": run.get("status"),
            "triggeredAt": run.get("triggeredAt"),
            "completedAt": run.get("completedAt"),
            "durationMin": minutes_between(run.get("triggeredAt"), run.get("completedAt")),
            "issue": linked.get("identifier") or (issue or {}).get("identifier"),
            "issueStatus": parent_status,
            "flags": flags,
            "latest": latest,
        }
        refs = referenced_post_issues(client, issue or {}, comments)
        if refs:
            row["referencedPostIssues"] = refs
            # Parent cannot be reported green while a referenced child is
            # non-terminal. Surface the child identifiers explicitly so
            # downstream consumers can route them.
            non_terminal = parent_child_status_violation(parent_status, refs)
            if non_terminal:
                row["flags"].append("parent_done_child_non_terminal")
                row["nonTerminalChildren"] = non_terminal
        rows.append(row)
    return rows


def stale_post_drafts(client: Paperclip, company_id: str) -> tuple[list[dict[str, Any]], bool]:
    statuses = "todo,in_progress,in_review,blocked,done"
    rows: list[dict[str, Any]] = []
    issues, truncated = list_issues(client, company_id, statuses)
    for issue in issues:
        title = issue.get("title") or ""
        if not title.startswith("[post:"):
            continue
        comments, comments_degraded = issue_comments(client, issue["id"])
        interactions, interactions_degraded = issue_interactions(client, issue["id"])
        flags, latest = classify_issue(
            issue, comments, interactions, interactions_degraded or comments_degraded
        )
        if flags or issue.get("status") != "done":
            rows.append(
                {
                    "identifier": issue.get("identifier"),
                    "title": title,
                    "status": issue.get("status"),
                    "updatedAt": issue.get("updatedAt"),
                    "flags": flags,
                    "latest": latest,
                }
            )
    return rows, truncated


def print_text(report: dict[str, Any]) -> None:
    print(f"paperclip_routine_audit generated_at={report['generatedAt']}")
    print()
    for row in report["routines"]:
        flags = ",".join(row["flags"]) if row["flags"] else "ok"
        print(
            f"{row['routine']}: run={row['runStatus']} issue={row['issue']} "
            f"issue_status={row['issueStatus']} duration_min={row['durationMin']} flags={flags}"
        )
        if row["latest"]:
            print(f"  latest: {row['latest']}")
        for ref in row.get("referencedPostIssues", []):
            ref_flags = ",".join(ref["flags"]) if ref["flags"] else "ok"
            nested = ref.get("nestedState") or "unknown"
            print(
                f"  ref {ref['identifier']} {ref['status']} nested={nested} "
                f"flags={ref_flags}: {ref['title']}"
            )
            if ref["latest"]:
                print(f"    latest: {ref['latest']}")
    if report.get("postDraftsTruncated"):
        print()
        print("warning: post draft list truncated; raise --limit or paginate")
    if report["postDrafts"]:
        print()
        print("post_drafts:")
        for draft in report["postDrafts"]:
            flags = ",".join(draft["flags"]) if draft["flags"] else "ok"
            print(f"  {draft['identifier']} {draft['status']} flags={flags}: {draft['title']}")
            if draft["latest"]:
                print(f"    latest: {draft['latest']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company-id",
        default=os.getenv("PAPERCLIP_COMPANY_ID", DEFAULT_COMPANY_ID),
    )
    parser.add_argument("--focus", default="all", help="all, comms, updates, or name substring")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    base_url = paperclip_base_url()
    api_key = os.getenv("PAPERCLIP_API_KEY")
    if not base_url or not api_key:
        print("Set PAPERCLIP_API_URL (or PAPERCLIP_URL) and PAPERCLIP_API_KEY", file=sys.stderr)
        return 2

    client = Paperclip(base_url, api_key)
    if args.focus in {"all", "comms"}:
        post_drafts, post_drafts_truncated = stale_post_drafts(client, args.company_id)
    else:
        post_drafts, post_drafts_truncated = [], False
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "companyId": args.company_id,
        "focus": args.focus,
        "routines": audit_routines(client, args.company_id, args.focus),
        "postDrafts": post_drafts,
        "postDraftsTruncated": post_drafts_truncated,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
