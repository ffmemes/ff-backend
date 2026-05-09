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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

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
PUBLISHED_MARKER_PATTERNS = (
    re.compile(r"\boutcome\s*=\s*published\b", re.IGNORECASE),
    re.compile(r"\b(?:editorial_post_id|editorial post id)\b", re.IGNORECASE),
    re.compile(r"\b(?:telegram_message_id|telegram message id)\b", re.IGNORECASE),
)
INTERACTION_LIST_KEYS = ("interactions", "items", "data")
CONFIRMATION_KIND_MARKERS = ("confirmation", "request_confirmation")
ACCEPTED_MARKERS = {"accepted", "approved", "confirmed", "yes"}
VERIFIED_PAPERCLIP_DEPLOY_PATTERNS = (
    re.compile(r"\bverified_deployed_commit\b", re.IGNORECASE),
    re.compile(r"\bcoolify_deployment_commit\b", re.IGNORECASE),
    re.compile(r"\bactual_deployed_commit\b", re.IGNORECASE),
)
SENSITIVE_PATTERNS = (
    (
        re.compile(r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]{20,}"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(https?://)[^@\s/:]+:[^@\s@]+@"),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(
            r"(?i)\b([a-z0-9_]*(?:token|secret|api_key|auth)[a-z0-9_]*\s*[:=]\s*)"
            r"([^\s,;]+)"
        ),
        r"\1[REDACTED]",
    ),
)


class Paperclip:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        url = self.base_url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("User-Agent", "ffmemes-paperclip-routine-audit/1.0")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = compact_body(exc.read().decode("utf-8", errors="replace"), limit=500)
            raise RuntimeError(f"HTTP {exc.code} for {path}: {body}") from exc


def paperclip_base_url() -> str | None:
    base_url = os.getenv("PAPERCLIP_API_URL") or os.getenv("PAPERCLIP_URL")
    if base_url and base_url.rstrip("/").endswith("/api"):
        return base_url.rstrip("/")[:-4]
    return base_url


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def minutes_between(start: str | None, end: str | None) -> float | None:
    a = parse_ts(start)
    b = parse_ts(end)
    if not a or not b:
        return None
    return round((b - a).total_seconds() / 60, 1)


def compact_body(body: str, limit: int = 240) -> str:
    body = " ".join(body.split())
    for pattern, replacement in SENSITIVE_PATTERNS:
        body = pattern.sub(replacement, body)
    return body if len(body) <= limit else body[: limit - 1] + "…"


def issue_comments(client: Paperclip, issue_id: str) -> list[dict[str, Any]]:
    comments = client.get(f"/api/issues/{issue_id}/comments", {"limit": "100"})
    if not isinstance(comments, list):
        return []
    return sorted(comments, key=lambda item: item.get("createdAt") or "")


def issue_interactions(client: Paperclip, issue_id: str) -> list[dict[str, Any]]:
    try:
        interactions = client.get(f"/api/issues/{issue_id}/interactions", {"limit": "100"})
    except RuntimeError:
        return []
    if isinstance(interactions, list):
        return interactions
    if isinstance(interactions, dict):
        for key in INTERACTION_LIST_KEYS:
            value = interactions.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def get_issue(client: Paperclip, issue_id: str) -> dict[str, Any] | None:
    try:
        issue = client.get(f"/api/issues/{issue_id}")
    except RuntimeError:
        return None
    return issue if isinstance(issue, dict) else None


def list_issues(client: Paperclip, company_id: str, status: str, limit: int = 100) -> list[dict]:
    issues = client.get(
        f"/api/companies/{company_id}/issues",
        {"status": status, "limit": str(limit)},
    )
    return issues if isinstance(issues, list) else []


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
        (
            "deployed paperclip update" in lower
            or "coolify deployment queued" in lower
            or "state file updated" in lower
            or "deployed paperclip" in lower
        )
        and not any(pattern.search(text) for pattern in VERIFIED_PAPERCLIP_DEPLOY_PATTERNS)
    ):
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
    if is_publish_flow and has_approval_signal and not all(
        pattern.search(text) for pattern in PUBLISHED_MARKER_PATTERNS
    ):
        flags.append("approved_without_publish_marker")
    # Generic stall / no-comment / zombie-run classification is intentionally
    # delegated to Paperclip v2026.428+ productivity review and liveness
    # recovery; this audit only flags FFmemes business-outcome mismatches.
    latest = comments[-1].get("body", "") if comments else issue.get("description", "")
    return flags, compact_body(latest or "")


def referenced_post_issues(
    client: Paperclip,
    issue: dict[str, Any],
    comments: list[dict],
) -> list[dict]:
    text = "\n".join([issue.get("description") or ""] + [c.get("body") or "" for c in comments])
    found: list[dict] = []
    for ident in sorted(set(POST_RE.findall(text))):
        ref = get_issue(client, ident)
        if ref and (ref.get("title") or "").startswith("[post:"):
            ref_comments = issue_comments(client, ref["id"])
            ref_interactions = issue_interactions(client, ref["id"])
            flags, latest = classify_issue(ref, ref_comments, ref_interactions)
            found.append(
                {
                    "identifier": ref.get("identifier"),
                    "title": ref.get("title"),
                    "status": ref.get("status"),
                    "assigneeAgentId": ref.get("assigneeAgentId"),
                    "updatedAt": ref.get("updatedAt"),
                    "flags": flags,
                    "latest": latest,
                }
            )
    return found


def audit_routines(client: Paperclip, company_id: str, focus: str) -> list[dict[str, Any]]:
    routines = client.get(f"/api/companies/{company_id}/routines")
    if not isinstance(routines, list):
        raise RuntimeError("Unexpected routines response")

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
        issue = get_issue(client, issue_id) if issue_id else None
        comments = issue_comments(client, issue_id) if issue_id else []
        interactions = issue_interactions(client, issue_id) if issue_id else []
        flags, latest = classify_issue(issue or {}, comments, interactions)
        payload_pr = str(((run.get("triggerPayload") or {}).get("pr_number")) or "")
        issue_title = (
            ((run.get("linkedIssue") or {}).get("title")) or (issue or {}).get("title") or ""
        )
        if payload_pr and f"[pr:{payload_pr}]" not in issue_title:
            flags.append("coalesced_pr_review_mismatch")
        row = {
            "routine": name,
            "routineId": routine.get("id"),
            "runStatus": run.get("status"),
            "triggeredAt": run.get("triggeredAt"),
            "completedAt": run.get("completedAt"),
            "durationMin": minutes_between(run.get("triggeredAt"), run.get("completedAt")),
            "issue": linked.get("identifier") or (issue or {}).get("identifier"),
            "issueStatus": linked.get("status") or (issue or {}).get("status"),
            "flags": flags,
            "latest": latest,
        }
        refs = referenced_post_issues(client, issue or {}, comments)
        if refs:
            row["referencedPostIssues"] = refs
        rows.append(row)
    return rows


def stale_post_drafts(client: Paperclip, company_id: str) -> list[dict[str, Any]]:
    statuses = "todo,in_progress,in_review,blocked,done"
    rows: list[dict[str, Any]] = []
    for issue in list_issues(client, company_id, statuses):
        title = issue.get("title") or ""
        if not title.startswith("[post:"):
            continue
        comments = issue_comments(client, issue["id"])
        interactions = issue_interactions(client, issue["id"])
        flags, latest = classify_issue(issue, comments, interactions)
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
    return rows


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
            print(f"  ref {ref['identifier']} {ref['status']} flags={ref_flags}: {ref['title']}")
            if ref["latest"]:
                print(f"    latest: {ref['latest']}")
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
    post_drafts = (
        stale_post_drafts(client, args.company_id) if args.focus in {"all", "comms"} else []
    )
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "companyId": args.company_id,
        "focus": args.focus,
        "routines": audit_routines(client, args.company_id, args.focus),
        "postDrafts": post_drafts,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
