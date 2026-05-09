"""Fixture tests for the Staff Engineer PR-review contract.

Covers every branch of `paperclip_pr_review`:
  - issue slug / CTO follow-up title shape
  - internal vs external author + branch + fork rules
  - `pr_state_decision` — already_resolved / missing_payload / review
  - `review_outcome` — approved / changes_requested / blocked
  - `merge_preflight` — three-check preflight (review, internal, CI, repo)
  - `terminal_checklist` — required side effects per outcome
  - dry-run CLI runs without network access (uses tmp JSON fixtures)
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

from paperclip_pr_review import (  # noqa: E402
    INTERNAL_BRANCH_PREFIXES,
    cto_followup_title,
    is_internal_pr,
    merge_preflight,
    pr_issue_slug,
    pr_state_decision,
    render_decision_summary,
    review_outcome,
    terminal_checklist,
)


def test_pr_issue_slug_shape():
    assert pr_issue_slug(174) == "[pr:174]"
    assert pr_issue_slug("204") == "[pr:204]"
    assert cto_followup_title(174) == "[pr:174] address review changes"


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({"author": {"login": "ohld"}, "headRefName": "main", "isCrossRepository": False}, True),
        (
            {"author": {"login": "ohld"}, "headRefName": "feat/x", "isCrossRepository": True},
            False,
        ),  # fork
        (
            {
                "author": {"login": "external"},
                "headRefName": "agent/wakey",
                "isCrossRepository": False,
            },
            True,
        ),
        (
            {
                "author": {"login": "external"},
                "headRefName": "fix/FFM-123",
                "isCrossRepository": False,
            },
            True,
        ),
        (
            {
                "author": {"login": "external"},
                "headRefName": "feat/agent-something",
                "isCrossRepository": False,
            },
            True,
        ),
        (
            {
                "author": {"login": "external"},
                "headRefName": "feature/x",
                "isCrossRepository": False,
            },
            False,
        ),
        (
            {
                "author": {"login": "external"},
                "headRefName": "agent/wakey",
                "isCrossRepository": True,
            },
            False,
        ),  # fork spoof
        (
            {"author": "ohld", "headRefName": "main", "isCrossRepository": False},
            True,
        ),  # plain string author
    ],
)
def test_is_internal_pr(meta, expected):
    assert is_internal_pr(meta) is expected


def test_internal_branch_prefixes_cover_documented_set():
    # Mirrors the set in agents/staff-engineer/AGENTS.md step 1.
    expected = {
        "agent/",
        "cto/",
        "staff-engineer/",
        "release-engineer/",
        "localize-",
        "fix/FFM-",
        "feat/agent-",
    }
    assert set(INTERNAL_BRANCH_PREFIXES) == expected


def test_pr_state_decision_resolved_states():
    assert pr_state_decision({"pr_number": 1, "state": "MERGED"}) == "already_resolved"
    assert pr_state_decision({"pr_number": 1, "state": "CLOSED"}) == "already_resolved"
    assert pr_state_decision({"pr_number": 1, "state": "OPEN"}) == "review"
    assert pr_state_decision({"pr_number": 1, "state": ""}) == "review"


def test_pr_state_decision_missing_payload():
    assert pr_state_decision({}) == "missing_payload"
    assert pr_state_decision({"pr_number": 0}) == "missing_payload"
    assert pr_state_decision({"pr_number": None, "state": "OPEN"}) == "missing_payload"


def test_review_outcome_paranoia_blocks():
    assert (
        review_outcome(
            {"structural_pass": True, "codex_pass": True, "paranoia_violations": ["secret_added"]}
        )
        == "changes_requested"
    )


def test_review_outcome_structural_or_codex_fail():
    assert review_outcome({"structural_pass": False, "codex_pass": True}) == "changes_requested"
    assert review_outcome({"structural_pass": True, "codex_pass": False}) == "changes_requested"


def test_review_outcome_cso_branch():
    assert (
        review_outcome(
            {"structural_pass": True, "codex_pass": True, "cso_required": True, "cso_pass": False}
        )
        == "changes_requested"
    )
    assert (
        review_outcome(
            {"structural_pass": True, "codex_pass": True, "cso_required": True, "cso_pass": True}
        )
        == "approved"
    )


def test_review_outcome_blocked_when_evidence_missing():
    # No structural_pass evidence at all.
    assert review_outcome({}) == "blocked"
    assert review_outcome({"structural_pass": True}) == "blocked"
    assert (
        review_outcome({"structural_pass": True, "codex_pass": True, "cso_required": True})
        == "blocked"
    )


def test_review_outcome_clean_approve():
    assert review_outcome({"structural_pass": True, "codex_pass": True}) == "approved"
    assert (
        review_outcome({"structural_pass": True, "codex_pass": True, "cso_required": False})
        == "approved"
    )


def _meta(**overrides):
    base = {
        "pr_number": 174,
        "state": "OPEN",
        "author": {"login": "ohld"},
        "headRefName": "fix/FFM-foo",
        "isCrossRepository": False,
        "statusCheckRollup": [{"state": "SUCCESS"}],
    }
    base.update(overrides)
    return base


def _review(outcome="approved"):
    return {"structural_pass": True, "codex_pass": True, "outcome": outcome}


def test_merge_preflight_happy_path_internal():
    pre = merge_preflight(_meta(), _review(), {"allow_auto_merge": True})
    assert pre.should_merge is True
    assert pre.skip_reasons == ()


def test_merge_preflight_skips_when_changes_requested():
    pre = merge_preflight(_meta(), _review(outcome="changes_requested"), {"allow_auto_merge": True})
    assert pre.should_merge is False
    assert "review_outcome=changes_requested" in pre.skip_reasons


def test_merge_preflight_skips_external_author():
    meta = _meta(isCrossRepository=True, author={"login": "drive-by"})
    pre = merge_preflight(meta, _review(), {"allow_auto_merge": True})
    assert pre.should_merge is False
    assert "external_author" in pre.skip_reasons


def test_merge_preflight_skips_red_ci():
    meta = _meta(statusCheckRollup=[{"state": "SUCCESS"}, {"state": "FAILURE"}])
    pre = merge_preflight(meta, _review(), {"allow_auto_merge": True})
    assert pre.should_merge is False
    assert "ci_red" in pre.skip_reasons


def test_merge_preflight_skips_when_repo_auto_merge_disabled():
    pre = merge_preflight(_meta(), _review(), {"allow_auto_merge": False})
    assert pre.should_merge is False
    assert "auto_merge_disabled" in pre.skip_reasons


def test_merge_preflight_aggregates_multiple_reasons():
    meta = _meta(
        isCrossRepository=True, author={"login": "drive-by"}, statusCheckRollup=[{"state": "ERROR"}]
    )
    pre = merge_preflight(meta, _review(outcome="changes_requested"), {"allow_auto_merge": False})
    assert pre.should_merge is False
    assert {
        "review_outcome=changes_requested",
        "external_author",
        "ci_red",
        "auto_merge_disabled",
    } <= set(pre.skip_reasons)


def test_terminal_checklist_internal_approved_merged_clean():
    issues = terminal_checklist(
        _meta(),
        {"outcome": "approved"},
        {"review_signal_posted": True, "merge_state": "merged"},
    )
    assert issues == []


def test_terminal_checklist_internal_approved_queued_clean():
    issues = terminal_checklist(
        _meta(),
        {"outcome": "approved"},
        {"review_signal_posted": True, "merge_state": "queued"},
    )
    assert issues == []


def test_terminal_checklist_internal_approved_blocked_needs_comment():
    issues = terminal_checklist(
        _meta(),
        {"outcome": "approved"},
        {"review_signal_posted": True, "merge_state": "blocked"},
    )
    codes = [i.code for i in issues]
    assert "missing_block_comment" in codes


def test_terminal_checklist_external_approved_skipped_clean():
    meta = _meta(isCrossRepository=True, author={"login": "drive-by"})
    issues = terminal_checklist(
        meta,
        {"outcome": "approved"},
        {"review_signal_posted": True, "merge_state": "skipped"},
    )
    assert issues == []


def test_terminal_checklist_external_approved_unexpected_merge_flagged():
    meta = _meta(isCrossRepository=True, author={"login": "drive-by"})
    issues = terminal_checklist(
        meta,
        {"outcome": "approved"},
        {"review_signal_posted": True, "merge_state": "merged"},
    )
    codes = [i.code for i in issues]
    assert "external_unexpected_merge" in codes


def test_terminal_checklist_changes_requested_internal_requires_followup_and_cancel():
    issues = terminal_checklist(
        _meta(),
        {"outcome": "changes_requested"},
        {"review_signal_posted": True},
    )
    codes = [i.code for i in issues]
    assert "missing_cto_followup" in codes
    assert "auto_merge_not_cancelled" in codes


def test_terminal_checklist_changes_requested_external_no_followup_required():
    meta = _meta(isCrossRepository=True, author={"login": "drive-by"})
    issues = terminal_checklist(
        meta,
        {"outcome": "changes_requested"},
        {"review_signal_posted": True, "auto_merge_cancelled": True},
    )
    # External authors don't get CTO follow-up issues.
    codes = [i.code for i in issues]
    assert "missing_cto_followup" not in codes
    assert "auto_merge_not_cancelled" not in codes


def test_terminal_checklist_missing_review_signal_always_flagged():
    issues = terminal_checklist(
        _meta(),
        {"outcome": "approved"},
        {"review_signal_posted": False, "merge_state": "merged"},
    )
    codes = [i.code for i in issues]
    assert "missing_review_signal" in codes


def test_render_decision_summary_shape_for_review_branch():
    summary = render_decision_summary(
        _meta(),
        {"structural_pass": True, "codex_pass": True},
        {"allow_auto_merge": True},
        {"review_signal_posted": True, "merge_state": "queued"},
    )
    assert summary["pr_number"] == 174
    assert summary["issue_slug"] == "[pr:174]"
    assert summary["state_decision"] == "review"
    assert summary["is_internal"] is True
    assert summary["review_outcome"] == "approved"
    assert summary["merge_preflight"]["should_merge"] is True
    assert summary["terminal_unsatisfied"] == []
    assert summary["cto_followup_title"] == "[pr:174] address review changes"


def test_render_decision_summary_shape_for_already_resolved():
    summary = render_decision_summary(
        _meta(state="MERGED"),
        {},
        {"allow_auto_merge": True},
        {},
    )
    assert summary["state_decision"] == "already_resolved"


def test_dry_run_cli_runs_without_network(tmp_path):
    """Round-trip the dry-run CLI through subprocess to confirm no
    network access is attempted (no `gh`, no `curl`)."""
    meta_path = tmp_path / "meta.json"
    review_path = tmp_path / "review.json"
    repo_path = tmp_path / "repo.json"
    actions_path = tmp_path / "actions.json"
    meta_path.write_text(json.dumps(_meta()))
    review_path.write_text(json.dumps({"structural_pass": True, "codex_pass": True}))
    repo_path.write_text(json.dumps({"allow_auto_merge": True}))
    actions_path.write_text(json.dumps({"review_signal_posted": True, "merge_state": "queued"}))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "paperclip_pr_review.py"),
            "--meta",
            str(meta_path),
            "--review",
            str(review_path),
            "--repo",
            str(repo_path),
            "--post-actions",
            str(actions_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["review_outcome"] == "approved"
    assert payload["merge_preflight"]["should_merge"] is True
