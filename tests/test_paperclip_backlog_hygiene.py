"""Fixture tests for `scripts/paperclip_backlog_hygiene.py`.

Cover every branch of the classifier and the closure-decision pass:

  - Strategic / experiment issues never auto-close even when they have
    an assignee.
  - `[pr:NNN]` parents auto-close only when the PR is in
    `merged_pr_numbers`.
  - `[maintenance:access-<agent>]` duplicates collapse to the canonical
    issue; the canonical itself stays open.
  - `[report:family-DATE]` becomes `stale_report` only when a newer
    family entry exists; the newest stays open.
  - "Superseded by FFM-…" closes only when the successor is in
    `known_identifiers`.
  - `approval_waiting` / `access_blocked` / `active_implementation`
    always return `leave_open`, regardless of bracket prefix.
  - `build_report` is idempotent across reruns and emits the full
    `counts` map keyed by `BACKLOG_CLASSES` even when zero.
  - Dry-run CLI produces the same ledger end-to-end without network
    access.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_backlog_hygiene import (  # noqa: E402
    AUTO_CLOSE_CLASSES,
    BACKLOG_CLASSES,
    CLOSURE_ACTIONS,
    NEVER_AUTO_CLOSE_CLASSES,
    BacklogContext,
    build_report,
    classify_issue,
    closure_decision,
    derive_report_context_from_issues,
)

# --- contract invariants ----------------------------------------------------


def test_auto_close_and_never_close_partition_backlog_classes():
    assert AUTO_CLOSE_CLASSES.isdisjoint(NEVER_AUTO_CLOSE_CLASSES)
    assert AUTO_CLOSE_CLASSES | NEVER_AUTO_CLOSE_CLASSES == frozenset(BACKLOG_CLASSES)


def test_closure_actions_are_stable():
    assert CLOSURE_ACTIONS == ("auto_close", "leave_open", "needs_human")


# --- strategic / experiment never close ------------------------------------


def test_strategy_slug_is_strategic_product():
    issue = {
        "identifier": "FFM-100",
        "status": "in_progress",
        "title": "[strategy:north-star] Push session length north",
        "assignedAgentId": "ceo",
    }
    classification = classify_issue(issue, context=BacklogContext())
    assert classification.backlog_class == "strategic_product"
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "leave_open"


def test_experiment_slug_is_strategic_product_even_with_assignee():
    issue = {
        "identifier": "FFM-101",
        "status": "in_progress",
        "title": "[experiment:cold-start-v3] try ML cold start",
        "assignedAgentId": "analyst",
    }
    classification = classify_issue(issue, context=BacklogContext())
    assert classification.backlog_class == "strategic_product"


# --- merged PR parent --------------------------------------------------------


def test_pr_issue_is_merged_pr_parent_when_pr_merged():
    issue = {
        "identifier": "FFM-200",
        "status": "in_review",
        "title": "[pr:204] localize crossposting query",
    }
    context = BacklogContext(merged_pr_numbers=frozenset({204}))
    classification = classify_issue(issue, context=context)
    assert classification.backlog_class == "merged_pr_parent"
    assert classification.proof == {"pr_number": 204}
    decision = closure_decision(issue, classification, context=context)
    assert decision.action == "auto_close"
    assert decision.proof == {"pr_number": 204}


def test_pr_issue_is_unknown_when_pr_not_merged():
    issue = {
        "identifier": "FFM-201",
        "status": "in_review",
        "title": "[pr:300] not yet merged",
    }
    classification = classify_issue(issue, context=BacklogContext())
    # No proof of merge — falls through to unknown.
    assert classification.backlog_class == "unknown"
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "leave_open"


def test_pr_proof_must_round_trip_against_context():
    """Defensive: a hand-crafted classification with a proof that no
    longer matches the context must NOT auto-close."""
    from paperclip_backlog_hygiene import Classification

    issue = {
        "identifier": "FFM-202",
        "status": "in_review",
        "title": "[pr:999] phantom proof",
    }
    classification = Classification(
        backlog_class="merged_pr_parent",
        reason="phantom",
        proof={"pr_number": 999},
    )
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "needs_human"


# --- duplicate maintenance-access ------------------------------------------


def test_duplicate_maintenance_access_collapses_to_canonical():
    canonical = {
        "identifier": "FFM-300",
        "status": "todo",
        "title": "[maintenance:access-qa-engineer] missing $SENTRY_AUTH_TOKEN",
    }
    duplicate = {
        "identifier": "FFM-301",
        "status": "todo",
        "title": "[maintenance:access-qa-engineer] missing access (re-filed)",
    }
    context = BacklogContext(canonical_access_slugs={"qa-engineer": "FFM-300"})
    canonical_class = classify_issue(canonical, context=context)
    duplicate_class = classify_issue(duplicate, context=context)

    assert canonical_class.backlog_class == "access_blocked"
    assert duplicate_class.backlog_class == "duplicate"
    assert duplicate_class.proof == {
        "canonical": "FFM-300",
        "agent": "qa-engineer",
    }

    canonical_decision = closure_decision(canonical, canonical_class, context=context)
    duplicate_decision = closure_decision(duplicate, duplicate_class, context=context)

    assert canonical_decision.action == "leave_open"
    assert duplicate_decision.action == "auto_close"


def test_duplicate_with_self_referential_canonical_needs_human():
    """If the canonical mapping points at the issue itself, refuse to
    auto-close."""
    from paperclip_backlog_hygiene import Classification

    issue = {
        "identifier": "FFM-302",
        "status": "todo",
        "title": "[maintenance:access-cto] missing $PAPERCLIP_API_KEY",
    }
    classification = Classification(
        backlog_class="duplicate",
        reason="hand-crafted",
        proof={"canonical": "FFM-302", "agent": "cto"},
    )
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "needs_human"


# --- stale report -----------------------------------------------------------


def test_report_with_newer_family_entry_is_stale():
    older = {
        "identifier": "FFM-400",
        "status": "todo",
        "title": "[report:weekly-2026-04-25] last week",
    }
    newer = {
        "identifier": "FFM-401",
        "status": "todo",
        "title": "[report:weekly-2026-05-02] this week",
    }
    context = derive_report_context_from_issues([older, newer])

    older_class = classify_issue(older, context=context)
    newer_class = classify_issue(newer, context=context)

    assert older_class.backlog_class == "stale_report"
    assert older_class.proof == {
        "family": "weekly",
        "latest": "2026-05-02",
        "this": "2026-04-25",
    }
    assert newer_class.backlog_class == "unknown"

    older_decision = closure_decision(older, older_class, context=context)
    newer_decision = closure_decision(newer, newer_class, context=context)

    assert older_decision.action == "auto_close"
    assert newer_decision.action == "leave_open"


def test_only_report_in_family_is_not_stale():
    only = {
        "identifier": "FFM-410",
        "status": "todo",
        "title": "[report:health-2026-05-01] first health report",
    }
    context = derive_report_context_from_issues([only])
    classification = classify_issue(only, context=context)
    assert classification.backlog_class == "unknown"


# --- superseded by ----------------------------------------------------------


def test_superseded_with_known_successor_auto_closes():
    issue = {
        "identifier": "FFM-500",
        "status": "todo",
        "title": "old plan to fix metrics",
        "comments": [{"body": "Superseded by FFM-501; closing soon."}],
    }
    context = BacklogContext(known_identifiers=frozenset({"FFM-500", "FFM-501"}))
    classification = classify_issue(issue, context=context)
    assert classification.backlog_class == "superseded"
    assert classification.proof == {"successor": "FFM-501"}
    decision = closure_decision(issue, classification, context=context)
    assert decision.action == "auto_close"


def test_superseded_with_unknown_successor_needs_human():
    issue = {
        "identifier": "FFM-501",
        "status": "todo",
        "title": "old plan",
        "comments": [{"body": "superseded by FFM-9999 (not visible)"}],
    }
    classification = classify_issue(issue, context=BacklogContext())
    # The classifier requires the successor to be in known_identifiers,
    # otherwise the comment doesn't promote to `superseded`.
    assert classification.backlog_class == "unknown"


# --- approval / access / active --------------------------------------------


def test_approval_waiting_post_stays_open():
    issue = {
        "identifier": "FFM-600",
        "status": "in_review",
        "title": "[post:2026-05-09-rollup] daily channel rollup",
        "description": "Awaiting approval — APPROVED_TO_PUBLISH not received yet.",
    }
    classification = classify_issue(issue, context=BacklogContext())
    assert classification.backlog_class == "approval_waiting"
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "leave_open"


def test_access_blocked_signal_in_text_keeps_issue_open():
    issue = {
        "identifier": "FFM-700",
        "status": "blocked",
        "title": "fix Sentry CLI integration",
        "comments": [{"body": "401 Unauthorized — missing token in runtime."}],
    }
    classification = classify_issue(issue, context=BacklogContext())
    assert classification.backlog_class == "access_blocked"
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "leave_open"


def test_active_implementation_with_assignee_stays_open():
    issue = {
        "identifier": "FFM-800",
        "status": "in_progress",
        "title": "wire describe_memes resilience",
        "assignedAgentId": "staff-engineer",
    }
    classification = classify_issue(issue, context=BacklogContext())
    assert classification.backlog_class == "active_implementation"
    decision = closure_decision(issue, classification, context=BacklogContext())
    assert decision.action == "leave_open"


# --- terminal-status guard --------------------------------------------------


def test_terminal_issue_never_auto_closes():
    issue = {
        "identifier": "FFM-900",
        "status": "done",
        "title": "[pr:204] already closed",
    }
    context = BacklogContext(merged_pr_numbers=frozenset({204}))
    classification = classify_issue(issue, context=context)
    decision = closure_decision(issue, classification, context=context)
    assert decision.action == "leave_open"
    assert "already terminal" in decision.reason


# --- build_report idempotency ----------------------------------------------


def _representative_issues() -> list[dict]:
    return [
        {
            "identifier": "FFM-A1",
            "status": "in_review",
            "title": "[pr:204] localize crossposting",
        },
        {
            "identifier": "FFM-A2",
            "status": "todo",
            "title": "[strategy:wedge] cold-start north star",
        },
        {
            "identifier": "FFM-A3",
            "status": "todo",
            "title": "[maintenance:access-qa-engineer] missing access #1",
        },
        {
            "identifier": "FFM-A4",
            "status": "todo",
            "title": "[maintenance:access-qa-engineer] missing access #2",
        },
        {
            "identifier": "FFM-A5",
            "status": "todo",
            "title": "[report:weekly-2026-04-25] last week",
        },
        {
            "identifier": "FFM-A6",
            "status": "todo",
            "title": "[report:weekly-2026-05-02] this week",
        },
        {
            "identifier": "FFM-A7",
            "status": "in_progress",
            "title": "implement experiment scoring",
            "assignedAgentId": "analyst",
        },
        {
            "identifier": "FFM-A8",
            "status": "blocked",
            "title": "investigate Sentry coverage gap",
            "comments": [{"body": "missing token — 403 Forbidden"}],
        },
        {
            "identifier": "FFM-A9",
            "status": "done",
            "title": "[pr:200] long-closed PR",
        },
    ]


def test_build_report_emits_full_counts_keyed_by_backlog_classes():
    context = BacklogContext(
        merged_pr_numbers=frozenset({204}),
        canonical_access_slugs={"qa-engineer": "FFM-A3"},
    )
    context = derive_report_context_from_issues(_representative_issues(), base=context)
    report = build_report(_representative_issues(), context=context)

    assert set(report["counts"].keys()) == set(BACKLOG_CLASSES)
    # Closed FFM-A9 must not appear in any open-issue row.
    open_idents = {row["identifier"] for row in report["rows"]}
    assert "FFM-A9" not in open_idents

    by_id = {row["identifier"]: row for row in report["rows"]}
    assert by_id["FFM-A1"]["class"] == "merged_pr_parent"
    assert by_id["FFM-A1"]["action"] == "auto_close"
    assert by_id["FFM-A2"]["class"] == "strategic_product"
    assert by_id["FFM-A3"]["class"] == "access_blocked"
    assert by_id["FFM-A3"]["action"] == "leave_open"
    assert by_id["FFM-A4"]["class"] == "duplicate"
    assert by_id["FFM-A4"]["action"] == "auto_close"
    assert by_id["FFM-A5"]["class"] == "stale_report"
    assert by_id["FFM-A5"]["action"] == "auto_close"
    assert by_id["FFM-A6"]["class"] == "unknown"
    assert by_id["FFM-A7"]["class"] == "active_implementation"
    assert by_id["FFM-A8"]["class"] == "access_blocked"

    assert report["actionCounts"]["auto_close"] == 3
    # Every action key is present even when zero.
    assert set(report["actionCounts"].keys()) == set(CLOSURE_ACTIONS)


def test_build_report_is_idempotent():
    context = BacklogContext(
        merged_pr_numbers=frozenset({204}),
        canonical_access_slugs={"qa-engineer": "FFM-A3"},
    )
    context = derive_report_context_from_issues(_representative_issues(), base=context)
    fixed = "2026-05-09T00:00:00+00:00"
    from datetime import datetime, timezone

    now = datetime.fromisoformat(fixed)
    first = build_report(_representative_issues(), context=context, now=now)
    second = build_report(_representative_issues(), context=context, now=now)

    # Generated-at varies in real runs; pin it via `now` so the rest of
    # the dict can be compared directly.
    assert first == second
    assert first["generatedAt"].endswith("+00:00")
    assert datetime.fromisoformat(first["generatedAt"]).tzinfo is timezone.utc


def test_build_report_with_empty_input():
    report = build_report([])
    assert report["rows"] == []
    assert all(report["counts"][cls] == 0 for cls in BACKLOG_CLASSES)
    assert all(report["actionCounts"][action] == 0 for action in CLOSURE_ACTIONS)


# --- CLI smoke test ---------------------------------------------------------


def test_cli_reads_issues_and_context_without_network(tmp_path: Path):
    issues_path = tmp_path / "issues.json"
    context_path = tmp_path / "context.json"
    issues_path.write_text(json.dumps(_representative_issues()), encoding="utf-8")
    context_path.write_text(
        json.dumps(
            {
                "merged_pr_numbers": [204],
                "canonical_access_slugs": {"qa-engineer": "FFM-A3"},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "paperclip_backlog_hygiene.py"),
            "--issues",
            str(issues_path),
            "--context",
            str(context_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": ""},  # prove no `gh` / `curl` lookup happens
    )
    payload = json.loads(result.stdout)
    by_id = {row["identifier"]: row for row in payload["rows"]}
    assert by_id["FFM-A1"]["action"] == "auto_close"
    assert by_id["FFM-A4"]["action"] == "auto_close"
    assert payload["actionCounts"]["auto_close"] >= 2


@pytest.mark.parametrize("missing_status", ["", None])
def test_open_filter_drops_status_unknown(missing_status):
    """Issues with no status are not OPEN — they should be filtered."""
    issues = [{"identifier": "FFM-X", "status": missing_status, "title": "?"}]
    report = build_report(issues)
    assert report["rows"] == []
