#!/usr/bin/env python3
"""Read-only audit for Paperclip outcome throughput.

This separates agent activity from product learning. It is intentionally
compact enough to paste into a CEO weekly review without dumping raw issue JSON.

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
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from paperclip_contracts import (
        EXECUTION_CATEGORIES,
        ISSUE_CLASSES,
        canonical_action,
        is_decision_action,
        is_outcome_action,
        issue_slug,
    )
    from paperclip_http import (
        PaperclipAPIError,
        PaperclipClient,
        paperclip_base_url,
        parse_ts,
        redact,
    )
except ModuleNotFoundError:
    from scripts.paperclip_contracts import (
        EXECUTION_CATEGORIES,
        ISSUE_CLASSES,
        canonical_action,
        is_decision_action,
        is_outcome_action,
        issue_slug,
    )
    from scripts.paperclip_http import (
        PaperclipAPIError,
        PaperclipClient,
        paperclip_base_url,
        parse_ts,
        redact,
    )

DEFAULT_COMPANY_ID = "96ee7b2e-6df2-43c8-bbe3-53e19297308a"
ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "experiments" / "log.jsonl"
ACTIVE_EXPERIMENTS_DIR = ROOT / "experiments" / "active"

OPEN_STATUSES = {"backlog", "todo", "in_progress", "in_review", "blocked"}
ALL_STATUSES = "backlog,todo,in_progress,in_review,blocked,done,cancelled"


class Paperclip:
    """Backwards-compatible facade over the shared `PaperclipClient`."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._client = PaperclipClient(
            base_url,
            api_key,
            user_agent="ffmemes-paperclip-outcome-audit/1.0",
        )
        self.base_url = self._client.base_url
        self.api_key = api_key

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        try:
            return self._client.get(path, query=query)
        except PaperclipAPIError as exc:
            raise RuntimeError(str(exc)) from exc

    def paginate(self, path: str, **kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return self._client.paginate(path, **kwargs)


def compact_body(body: str, limit: int = 240) -> str:
    return redact(body, limit=limit)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"\d{4}-\d{2}-\d{2}", value)
    if not match:
        return None
    return date.fromisoformat(match.group(0))


def age_days(day: date | None, today: date) -> int | None:
    if not day:
        return None
    return (today - day).days


def in_window(value: str | None, since: datetime) -> bool:
    parsed = parse_ts(value)
    return bool(parsed and parsed >= since)


def list_agents(client: Paperclip, company_id: str) -> dict[str, str]:
    agents = client.get(f"/api/companies/{company_id}/agents")
    if not isinstance(agents, list):
        return {}
    return {
        item.get("id"): (
            item.get("name") or item.get("title") or item.get("urlKey") or item.get("id")
        )
        for item in agents
        if item.get("id")
    }


def list_issues(
    client: Paperclip, company_id: str, limit: int | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Paginate every status so the audit doesn't silently undercount once the
    company crosses the API's per-request cap.

    Deduplication, shape-drift detection, duplicate-page bail, and the
    ceiling probe live in `PaperclipClient.paginate`; this wrapper just
    binds the FFmemes-specific path and status filter.
    """
    path = f"/api/companies/{company_id}/issues"
    query = {"status": ALL_STATUSES}
    issues, truncation = client.paginate(
        path,
        query=query,
        limit=limit,
    )
    return issues, {
        **truncation,
        "path": path,
        "query": query,
        "requestedLimit": limit,
    }


def classify_issue(issue: dict[str, Any], agents: dict[str, str]) -> str:
    """Map an issue to one of `paperclip_contracts.ALLOWED_ISSUE_CLASSES`.

    The slug → class mapping comes from `ISSUE_CLASSES`; creator/title
    fallbacks (Analyst report, QA scan, CEO routing, untyped experiment)
    stay here because they depend on per-company agent names.
    """
    title = issue.get("title") or ""
    lower = title.lower()
    slug = issue_slug(title)
    creator = agents.get(issue.get("createdByAgentId"), "")
    assignee = agents.get(issue.get("assigneeAgentId"), "")

    if slug and slug in ISSUE_CLASSES:
        return ISSUE_CLASSES[slug]
    if lower == "pr review" or "pr review" in lower:
        return "pr_review"
    if "analyst report" in lower or creator == "Analyst":
        return "analyst_report"
    if "experiment" in lower:
        return "experiment"
    if creator == "QA Engineer" or assignee == "QA Engineer":
        return "qa_scan"
    if creator == "CEO":
        return "ceo_routing"
    return "other"


def creator_label(issue: dict[str, Any], agents: dict[str, str]) -> str:
    agent_id = issue.get("createdByAgentId")
    if agent_id and agent_id in agents:
        return agents[agent_id]
    if issue.get("createdByUserId"):
        return "human"
    if issue.get("originKind") == "routine_execution":
        return "routine_execution"
    return "unknown"


def assignee_label(issue: dict[str, Any], agents: dict[str, str]) -> str:
    agent_id = issue.get("assigneeAgentId")
    if agent_id and agent_id in agents:
        return agents[agent_id]
    if issue.get("assigneeUserId"):
        return "human"
    return "unassigned"


def parse_log_entry(line: str) -> dict[str, Any] | None:
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return None
    return entry if isinstance(entry, dict) else None


def entry_contains_product_decision(entry: dict[str, Any]) -> bool:
    if is_decision_action(entry.get("action")):
        return True
    text = json.dumps(entry.get("details") or {}, ensure_ascii=True).lower()
    return any(
        marker in text
        for marker in (
            "product_decision",
            "experiment_continue",
            "experiment_blocked",
            "experiment_archived",
            "experiment_cancelled",
            "next_experiment_priority",
        )
    )


def log_events(since: datetime, limit: int = 12) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    alias_drift: Counter[str] = Counter()
    mapped_aliases: Counter[str] = Counter()
    if not LOG_PATH.exists():
        return {
            "events": [],
            "decisions": [],
            "outcomes": [],
            "aliasDrift": {},
            "mappedAliases": {},
            "counts": {"events": 0, "decisions": 0, "outcomes": 0},
        }

    for line in LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        entry = parse_log_entry(line)
        if not entry:
            continue
        ts = parse_ts(entry.get("timestamp"))
        if not ts or ts < since:
            continue
        events.append(entry)
        action = entry.get("action")
        if isinstance(action, str):
            canonical = canonical_action(action)
            if canonical and canonical != action:
                mapped_aliases[f"{action}->{canonical}"] += 1
        if entry_contains_product_decision(entry):
            decisions.append(entry)
        if is_outcome_action(action) or entry_contains_product_decision(entry):
            outcomes.append(entry)

    def compact(entry: dict[str, Any]) -> dict[str, Any]:
        action = entry.get("action")
        canonical = canonical_action(action) if isinstance(action, str) else None
        return {
            "timestamp": entry.get("timestamp"),
            "agent": entry.get("agent"),
            "action": action,
            "canonicalAction": canonical if canonical and canonical != action else None,
            "summary": compact_body(entry.get("summary") or "", limit=180),
        }

    return {
        "events": [compact(e) for e in events[-limit:]],
        "decisions": [compact(e) for e in decisions[-limit:]],
        "outcomes": [compact(e) for e in outcomes[-limit:]],
        "aliasDrift": dict(alias_drift),
        "mappedAliases": dict(mapped_aliases),
        "counts": {
            "events": len(events),
            "decisions": len(decisions),
            "outcomes": len(outcomes),
        },
    }


def read_field(text: str, field: str) -> str | None:
    patterns = (
        rf"^\*\*{re.escape(field)}:\*\*\s*(.+)$",
        rf"^{re.escape(field)}:\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def active_experiments(today: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not ACTIVE_EXPERIMENTS_DIR.exists():
        return rows

    for path in sorted(ACTIVE_EXPERIMENTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        created_raw = read_field(text, "Created")
        deployed_raw = read_field(text, "Deployed")
        measure_raw = read_field(text, "Measure after")
        created = parse_date(created_raw)
        deployed = parse_date(deployed_raw)
        measure_after = parse_date(measure_raw)
        flags: list[str] = []

        if measure_after and measure_after < today:
            flags.append(f"measurement_overdue_by_{(today - measure_after).days}d")
        if deployed_raw and "pending" in deployed_raw.lower():
            created_age = age_days(created, today)
            if created_age is not None and created_age > 7:
                flags.append(f"deploy_pending_{created_age}d")
        if created and not measure_after and (today - created).days > 21:
            flags.append(f"no_parseable_measurement_date_{(today - created).days}d")

        rows.append(
            {
                "file": str(path.relative_to(ROOT)),
                "name": path.stem,
                "created": created.isoformat() if created else None,
                "deployed": deployed.isoformat() if deployed else deployed_raw,
                "measureAfter": measure_after.isoformat() if measure_after else measure_raw,
                "ageDays": age_days(created, today),
                "flags": flags,
            }
        )
    return rows


def build_report(
    client: Paperclip, company_id: str, days: int, limit: int | None
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc)
    since = generated - timedelta(days=days)
    agents = list_agents(client, company_id)
    issues, issues_truncation = list_issues(client, company_id, limit)

    touched = [
        issue
        for issue in issues
        if in_window(issue.get("createdAt"), since)
        or in_window(issue.get("startedAt"), since)
        or in_window(issue.get("completedAt"), since)
        or in_window(issue.get("updatedAt"), since)
    ]
    created = [issue for issue in issues if in_window(issue.get("createdAt"), since)]
    completed = [issue for issue in issues if in_window(issue.get("completedAt"), since)]
    open_now = [issue for issue in issues if issue.get("status") in OPEN_STATUSES]

    category_counts = Counter(classify_issue(issue, agents) for issue in touched)
    status_counts = Counter(issue.get("status") or "unknown" for issue in touched)
    creator_counts = Counter(creator_label(issue, agents) for issue in created)
    assignee_counts = Counter(assignee_label(issue, agents) for issue in touched)
    log = log_events(since)
    experiments = active_experiments(generated.date())
    stale_experiments = [row for row in experiments if row["flags"]]

    completed_count = len(completed)
    decision_count = log["counts"]["decisions"]
    outcome_count = log["counts"]["outcomes"]
    decision_yield = round(decision_count / completed_count, 3) if completed_count else None
    outcome_yield = round(outcome_count / completed_count, 3) if completed_count else None
    execution_count = sum(category_counts[name] for name in EXECUTION_CATEGORIES)
    execution_share = round(execution_count / len(touched), 3) if touched else None

    flags: list[str] = []
    if completed_count >= 50 and decision_count < 3:
        flags.append("activity_without_decisions")
    if completed_count >= 10 and decision_yield is not None and decision_yield < 0.05:
        flags.append("low_decision_yield")
    if execution_share is not None and execution_share >= 0.7 and len(touched) >= 20:
        flags.append("execution_heavy_week")
    if stale_experiments:
        flags.append("stale_active_experiments")
    if len(experiments) > 2:
        flags.append("too_many_active_experiments")
    if issues_truncation["truncated"]:
        flags.append("issue_list_truncated")
        if issues_truncation.get("reason") == "unexpected_response_shape":
            flags.append("issue_list_shape_degraded")
    if log["aliasDrift"]:
        flags.append("outcome_alias_drift")

    return {
        "generatedAt": generated.isoformat(),
        "companyId": company_id,
        "window": {
            "days": days,
            "since": since.isoformat(),
            "until": generated.isoformat(),
        },
        "issueLimit": limit,
        "issueListTruncation": issues_truncation,
        "issues": {
            "touched": len(touched),
            "created": len(created),
            "completed": completed_count,
            "openNow": len(open_now),
            "byCategory": dict(category_counts.most_common()),
            "byStatus": dict(status_counts.most_common()),
            "createdBy": dict(creator_counts.most_common()),
            "assignedTo": dict(assignee_counts.most_common()),
        },
        "events": {
            "decisionCount": decision_count,
            "outcomeCount": outcome_count,
            "decisionYield": decision_yield,
            "outcomeYield": outcome_yield,
            "recentDecisions": log["decisions"],
            "recentOutcomes": log["outcomes"],
            "aliasDrift": log["aliasDrift"],
            "mappedAliases": log["mappedAliases"],
        },
        "activeExperiments": experiments,
        "flags": flags,
        "recommendedCeoActions": recommended_actions(flags),
    }


def recommended_actions(flags: list[str]) -> list[str]:
    actions: list[str] = []
    if "stale_active_experiments" in flags:
        actions.append(
            "Conclude, cancel, or explicitly re-date stale active experiments "
            "before opening new bets."
        )
    if "activity_without_decisions" in flags or "low_decision_yield" in flags:
        actions.append(
            "Convert the week into decisions: one keep, one kill, one change, and one next bet."
        )
    if "execution_heavy_week" in flags:
        actions.append(
            "Throttle new execution tickets unless they trace to a named product "
            "decision or incident threshold."
        )
    if "too_many_active_experiments" in flags:
        actions.append("Reduce to at most two active experiments so attribution stays readable.")
    if "issue_list_shape_degraded" in flags:
        actions.append(
            "Issue list response shape changed; counts are unreliable until the "
            "audit pagination is updated to the new schema."
        )
    elif "issue_list_truncated" in flags:
        actions.append(
            "Issue list is truncated; raise --limit or fix API offset handling before "
            "trusting completion/decision counts."
        )
    if "outcome_alias_drift" in flags:
        actions.append(
            "experiments/log.jsonl contains unmapped legacy outcome aliases; add "
            "an explicit contract mapping or rename them to canonical actions."
        )
    if not actions:
        actions.append(
            "Record the top decision, shipped outcome, stopped work, and next bet "
            "in the weekly outcome issue."
        )
    return actions


def print_text(report: dict[str, Any]) -> None:
    window = report["window"]
    issues = report["issues"]
    events = report["events"]
    print(f"paperclip_outcome_audit generated_at={report['generatedAt']}")
    print(f"window_days={window['days']} since={window['since']} until={window['until']}")
    print()
    print(
        "issues "
        f"touched={issues['touched']} created={issues['created']} "
        f"completed={issues['completed']} open_now={issues['openNow']}"
    )
    print(
        "events "
        f"decisions={events['decisionCount']} outcomes={events['outcomeCount']} "
        f"decision_yield={events['decisionYield']} outcome_yield={events['outcomeYield']}"
    )
    print()
    print("category_mix:")
    for category, count in issues["byCategory"].items():
        print(f"  {category}: {count}")
    print()
    print("created_by:")
    for creator, count in issues["createdBy"].items():
        print(f"  {creator}: {count}")
    if report["activeExperiments"]:
        print()
        print("active_experiments:")
        for experiment in report["activeExperiments"]:
            flags = ",".join(experiment["flags"]) if experiment["flags"] else "ok"
            print(
                f"  {experiment['name']}: created={experiment['created']} "
                f"deployed={experiment['deployed']} measure_after={experiment['measureAfter']} "
                f"flags={flags}"
            )
    if report["flags"]:
        print()
        print("flags:")
        for flag in report["flags"]:
            print(f"  {flag}")
    if events["recentDecisions"]:
        print()
        print("recent_decisions:")
        for event in events["recentDecisions"]:
            print(f"  {event['timestamp']} {event['action']}: {event['summary']}")
    print()
    print("recommended_ceo_actions:")
    for action in report["recommendedCeoActions"]:
        print(f"  - {action}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--company-id",
        default=os.getenv("PAPERCLIP_COMPANY_ID", DEFAULT_COMPANY_ID),
    )
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "optional maximum issues to scan; by default the audit follows "
            "pagination until the API returns a clean end-of-list"
        ),
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    base_url = paperclip_base_url()
    api_key = os.getenv("PAPERCLIP_API_KEY")
    if not base_url or not api_key:
        print("Set PAPERCLIP_API_URL (or PAPERCLIP_URL) and PAPERCLIP_API_KEY", file=sys.stderr)
        return 2

    client = Paperclip(base_url, api_key)
    report = build_report(client, args.company_id, args.days, args.limit)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)
    if report["issueListTruncation"]["truncated"]:
        truncation = report["issueListTruncation"]
        print(
            "error: issue pagination incomplete "
            f"path={truncation.get('path')} query={truncation.get('query')} "
            f"requested_limit={truncation.get('requestedLimit')} "
            f"reason={truncation.get('reason')} at_offset={truncation.get('atOffset')}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
