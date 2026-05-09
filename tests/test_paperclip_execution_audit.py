"""Unit tests for paperclip_execution_audit's evidence-class classifier.

The classifier is pure: it takes already-fetched issue/comment dicts. Tests
exercise every evidence class plus a happy-path "no signal" case so a
regression that drops one class will fail loudly.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_execution_audit import (  # noqa: E402
    EVIDENCE_CLASSES,
    build_report,
    classify_issue,
)

NOW = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)


def _issue(**overrides):
    base = {
        "id": "i-1",
        "identifier": "FFM-100",
        "status": "in_progress",
        "title": "Test issue",
        "description": "Body",
        "createdAt": (NOW - timedelta(hours=2)).isoformat(),
        "updatedAt": (NOW - timedelta(hours=2)).isoformat(),
        "createdByAgentId": "agent-1",
    }
    base.update(overrides)
    return base


def _comment(body: str, *, hours_ago: float = 1) -> dict:
    return {
        "body": body,
        "createdAt": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def _classify(issue, comments=(), *, by_ident=None, log_ids=None, threshold=timedelta(hours=24)):
    return classify_issue(
        issue,
        list(comments),
        issues_by_identifier=by_ident or {},
        log_outcome_ids=log_ids or set(),
        now=NOW,
        stopped_threshold=threshold,
    )


def test_evidence_classes_constant_matches_plan():
    # Locks the module's class enumeration to the plan's six classes. If
    # someone adds a class without updating the audit, this test fails.
    assert set(EVIDENCE_CLASSES) == {
        "stopped",
        "looping",
        "fake_green",
        "missing_access",
        "stale_instruction",
        "outcome_gap",
    }


def test_no_signal_for_fresh_in_progress_issue():
    issue = _issue(updatedAt=(NOW - timedelta(hours=1)).isoformat())
    assert _classify(issue, [_comment("just touched", hours_ago=0.5)]) == {}


def test_stopped_when_idle_past_threshold():
    stale = (NOW - timedelta(hours=72)).isoformat()
    issue = _issue(
        status="in_progress",
        createdAt=stale,
        updatedAt=stale,
    )
    classes = _classify(issue, [])
    assert "stopped" in classes
    assert classes["stopped"]["reason"] == "idle_past_threshold"
    assert classes["stopped"]["idleHours"] >= 24


def test_stopped_no_signal_for_terminal_status():
    issue = _issue(status="done", updatedAt=(NOW - timedelta(days=30)).isoformat())
    # A done issue can't be "stopped" — it's finished.
    assert "stopped" not in _classify(issue, [])


def test_missing_access_marker_in_comment():
    issue = _issue()
    comments = [_comment("permission denied: missing env $PAPERCLIP_API_KEY")]
    classes = _classify(issue, comments)
    assert "missing_access" in classes
    markers = classes["missing_access"]["markers"]
    assert any("missing env" in m or "$paperclip_" in m for m in markers)


def test_stale_instruction_marker_in_description():
    issue = _issue(description="container name changed; rerun against the new one")
    classes = _classify(issue, [])
    assert "stale_instruction" in classes


def test_fake_green_when_referenced_child_open():
    parent = _issue(
        id="i-parent",
        identifier="FFM-100",
        status="done",
        description="closes via FFM-200",
    )
    child_open = _issue(
        id="i-child",
        identifier="FFM-200",
        status="in_progress",
    )
    by_ident = {"FFM-100": parent, "FFM-200": child_open}
    classes = _classify(parent, [], by_ident=by_ident)
    assert "fake_green" in classes
    assert "FFM-200" in classes["fake_green"]["children"]


def test_fake_green_no_signal_when_all_children_terminal():
    parent = _issue(id="i-parent", identifier="FFM-100", status="done", description="see FFM-200")
    child_done = _issue(id="i-child", identifier="FFM-200", status="done")
    by_ident = {"FFM-100": parent, "FFM-200": child_done}
    assert "fake_green" not in _classify(parent, [], by_ident=by_ident)


def test_fake_green_skips_self_reference():
    # A done issue mentioning its own identifier in the body should not be
    # flagged as a fake-green parent of itself (regression guard).
    parent = _issue(
        id="i-parent",
        identifier="FFM-100",
        status="done",
        description="see FFM-100 for context",
    )
    by_ident = {"FFM-100": parent}
    assert "fake_green" not in _classify(parent, [], by_ident=by_ident)


def test_outcome_gap_when_done_without_marker():
    issue = _issue(status="done", description="all wrapped up")
    assert "outcome_gap" in _classify(issue, [_comment("looks good")])


def test_outcome_gap_satisfied_by_outcome_marker_in_comment():
    issue = _issue(status="done")
    comments = [_comment("outcome=published telegram_message_id=42")]
    assert "outcome_gap" not in _classify(issue, comments)


def test_outcome_gap_satisfied_by_log_event_for_identifier():
    issue = _issue(status="done", identifier="FFM-100")
    classes = _classify(issue, [_comment("done")], log_ids={"FFM-100"})
    assert "outcome_gap" not in classes


def test_looping_per_issue_when_retry_comments_exceed_threshold():
    issue = _issue()
    comments = [
        _comment("retrying after timeout", hours_ago=4),
        _comment("retrying again — same failure", hours_ago=3),
        _comment("retry attempt 4, still failing", hours_ago=2),
    ]
    classes = _classify(issue, comments)
    assert "looping" in classes
    assert classes["looping"]["retryComments"] >= 3


def test_looping_no_signal_for_single_retry_comment():
    issue = _issue()
    classes = _classify(issue, [_comment("retrying once")])
    assert "looping" not in classes


def test_build_report_aggregates_counts():
    parent_done = _issue(id="i-1", identifier="FFM-1", status="done", description="see FFM-2")
    child_open = _issue(id="i-2", identifier="FFM-2", status="in_progress")
    days_ago = (NOW - timedelta(days=4)).isoformat()
    stale = _issue(
        id="i-3",
        identifier="FFM-3",
        status="in_progress",
        createdAt=days_ago,
        updatedAt=days_ago,
    )
    issues = [parent_done, child_open, stale]
    report = build_report(issues, comments_by_id={}, log_outcome_ids=set(), now=NOW)
    counts = report["counts"]
    # Every plan class is represented in the response, even when zero.
    for cls in EVIDENCE_CLASSES:
        assert cls in counts
    assert counts["fake_green"] == 1  # parent_done references open FFM-2
    assert counts["stopped"] >= 1  # stale FFM-3 idle past 24h
    assert counts["outcome_gap"] >= 1  # parent_done has no outcome marker


def test_build_report_detects_cross_issue_duplicate_creation():
    issues = [
        _issue(id=f"i-{n}", identifier=f"FFM-{n}", title="QA scan failure", createdByAgentId="qa")
        for n in range(3)
    ]
    report = build_report(issues, comments_by_id={}, log_outcome_ids=set(), now=NOW)
    assert report["loopingGroups"], "expected one duplicate-title group"
    group = report["loopingGroups"][0]
    assert group["creatorAgentId"] == "qa"
    assert group["count"] == 3
    assert report["counts"]["looping"] >= 3


def test_redacts_secret_lookalikes_in_title():
    # The issue must trigger at least one evidence class so it lands in the
    # report's `issues` array — pick `stopped` by aging it past threshold.
    stale = (NOW - timedelta(days=4)).isoformat()
    issue = _issue(
        title="bug: bearer abcdef0123456789ABCDEF0123456789xyz failed",
        status="in_progress",
        createdAt=stale,
        updatedAt=stale,
    )
    report = build_report([issue], comments_by_id={}, log_outcome_ids=set(), now=NOW)
    rendered = report["issues"][0]["title"]
    assert "abcdef0123456789ABCDEF0123456789xyz" not in rendered
    assert "[REDACTED]" in rendered
