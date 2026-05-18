"""Unit tests for the centralized Paperclip contract module.

The module under test (`scripts/paperclip_contracts.py`) is pure: it
holds the slug → class map, outcome action enumeration, and the
nested-state classifier the audit scripts share. These fixtures double
as the "representative issue / comment / outcome" examples Task 6 calls
out: post drafts, PR review issues, QA incidents, stale experiments,
weekly outcome routines.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_contracts import (  # noqa: E402
    AGENT_WORKFLOW_INVARIANTS,
    ALLOWED_ISSUE_CLASSES,
    DECISION_ACTIONS,
    EXECUTION_CATEGORIES,
    ISSUE_CLASSES,
    NESTED_STATES,
    OUTCOME_ACTIONS,
    OUTCOME_ALIASES,
    agent_workflow_invariant_violations,
    canonical_action,
    is_decision_action,
    is_outcome_action,
    issue_slug,
    nested_state,
    parent_child_status_violation,
    parse_bracket_slug,
)

# --- slug parsing -----------------------------------------------------------


def test_parse_bracket_slug_post():
    assert parse_bracket_slug("[post:2026-05-09-test] Daily post") == (
        "post",
        "2026-05-09-test",
    )


def test_parse_bracket_slug_pr_review():
    assert parse_bracket_slug("[pr:215] Review") == ("pr", "215")


def test_parse_bracket_slug_qa_scan():
    assert parse_bracket_slug("[scan:2026-05-09-recommendations] QA") == (
        "scan",
        "2026-05-09-recommendations",
    )


def test_parse_bracket_slug_strips_uppercase():
    # Mixed-case prefixes should still resolve via the lowercased map.
    assert parse_bracket_slug("[Post:abc] Draft")[0] == "post"


def test_parse_bracket_slug_returns_none_for_plain_title():
    assert parse_bracket_slug("Investigate flakey reactions") is None
    assert parse_bracket_slug("") is None
    assert issue_slug(None) is None  # type: ignore[arg-type]


def test_issue_classes_cover_known_slugs():
    # Every prefix used by current routines must map to a stable class.
    for slug in (
        "pr",
        "post",
        "deploy",
        "incident",
        "maintenance",
        "report",
        "experiment",
        "scan",
        "strategy",
    ):
        assert slug in ISSUE_CLASSES, slug
        assert ISSUE_CLASSES[slug] in ALLOWED_ISSUE_CLASSES


def test_execution_categories_subset_of_allowed_classes():
    assert EXECUTION_CATEGORIES <= ALLOWED_ISSUE_CLASSES


# --- outcome / decision actions --------------------------------------------


def test_decision_actions_are_subset_of_outcome_actions():
    assert DECISION_ACTIONS <= OUTCOME_ACTIONS


def test_canonical_action_passes_through_known_action():
    assert canonical_action("daily_channel_post") == "daily_channel_post"
    assert canonical_action("post_published") == "post_published"


def test_canonical_action_resolves_legacy_alias():
    # The plan's named drift case: `daily_post` must resolve to
    # `daily_channel_post` so outcome counts stay accurate during the
    # migration.
    assert "daily_post" in OUTCOME_ALIASES
    assert OUTCOME_ALIASES["daily_post"] == "daily_channel_post"
    assert canonical_action("daily_post") == "daily_channel_post"


def test_canonical_action_returns_none_for_unknown_action():
    assert canonical_action("random_event") is None
    assert canonical_action(None) is None
    assert canonical_action("") is None


def test_is_outcome_and_decision_helpers_agree_with_canonical():
    assert is_outcome_action("daily_post") is True  # via alias
    assert is_outcome_action("daily_channel_post") is True
    assert is_outcome_action("bug_fixed") is True
    assert is_outcome_action("totally_made_up") is False
    assert is_decision_action("experiment_completed") is True
    assert is_decision_action("daily_channel_post") is False


# --- nested state classifier -----------------------------------------------


def test_nested_state_published_terminal():
    text = "Posted to channel.\noutcome=published telegram_message_id=42 editorial_post_id=ep-9"
    assert nested_state(text, slug="post") == "published"


def test_nested_state_approved_unpublished():
    text = "outcome=draft_created\ndecision=approved_to_publish\ndraft_revision=2"
    assert nested_state(text, slug="post") == "approved_unpublished"


def test_nested_state_pending_approval_for_post_without_signals():
    text = "draft text only"
    assert nested_state(text, slug="post") == "pending_approval"


def test_nested_state_stale_draft_takes_priority_over_approval():
    text = "APPROVED_TO_PUBLISH\noutcome=stale_draft"
    assert nested_state(text, slug="post") == "stale_draft"


def test_nested_state_blocked_without_access():
    text = "missing env $TELEGRAM_BOT_TOKEN; cannot publish"
    assert nested_state(text, slug="post") == "blocked_without_access"


def test_nested_state_missing_smoke():
    text = "Deploy succeeded but smoke check skipped — missing_smoke"
    assert nested_state(text, slug="deploy") == "missing_smoke"


def test_nested_state_merged_without_close_terminal():
    text = "PR merged. issue still open in Paperclip — merged_without_close"
    assert nested_state(text, slug="pr") == "merged_without_close"


def test_nested_state_unknown_for_non_post_without_signals():
    assert nested_state("plain text", slug="incident") == "unknown"
    assert nested_state("plain text", slug=None) == "unknown"


def test_nested_states_constant_is_stable():
    # Locks the enumeration for downstream consumers.
    assert NESTED_STATES == (
        "published",
        "merged_without_close",
        "stale_draft",
        "blocked_without_access",
        "missing_smoke",
        "approved_unpublished",
        "pending_approval",
        "unknown",
    )


# --- parent/child violation -----------------------------------------------


def _ref(identifier: str, *, status: str, nested: str | None = None):
    out = {"identifier": identifier, "status": status}
    if nested is not None:
        out["nestedState"] = nested
    return out


def test_parent_child_violation_flags_open_post_under_done_routine():
    children = [_ref("FFM-200", status="in_progress", nested="pending_approval")]
    assert parent_child_status_violation("done", children) == ["FFM-200"]


def test_parent_child_violation_clears_when_child_published():
    children = [_ref("FFM-200", status="done", nested="published")]
    assert parent_child_status_violation("done", children) == []


def test_parent_child_violation_clears_for_open_parent():
    # A non-terminal parent cannot be "fake green" by definition.
    children = [_ref("FFM-200", status="in_progress", nested="pending_approval")]
    assert parent_child_status_violation("in_progress", children) == []


def test_parent_child_violation_clears_when_nested_state_terminal_even_if_status_open():
    # Some routines close their own issue but leave the child status as
    # `in_review` after publishing because the publish path is the
    # nested signal. Honor the terminal nested state.
    children = [_ref("FFM-200", status="in_review", nested="published")]
    assert parent_child_status_violation("done", children) == []


def test_parent_child_violation_handles_multiple_children():
    children = [
        _ref("FFM-1", status="done", nested="published"),
        _ref("FFM-2", status="in_progress", nested="pending_approval"),
        _ref("FFM-3", status="cancelled"),  # cancelled counts as terminal
        _ref("FFM-4", status="blocked", nested="blocked_without_access"),
    ]
    assert parent_child_status_violation("done", children) == ["FFM-2", "FFM-4"]


# --- agent workflow invariants ---------------------------------------------


def test_agent_workflow_invariants_constant_is_stable():
    assert AGENT_WORKFLOW_INVARIANTS == (
        "ssh_default_path",
        "secret_recovery_prompt",
        "missing_paperclip_first_path",
    )


def test_agent_workflow_invariant_flags_ssh_default_path():
    text = "If deploy fails, start with SSH and inspect the container as the primary path."
    assert agent_workflow_invariant_violations(text) == ("ssh_default_path",)


def test_agent_workflow_invariant_flags_secret_recovery_prompt():
    text = "Search the machine and logs to recover the missing API key before continuing."
    assert agent_workflow_invariant_violations(text) == ("secret_recovery_prompt",)


def test_agent_workflow_invariant_flags_missing_paperclip_as_blocker():
    text = (
        "Paperclip MCP unavailable. This is a blocker and the audit cannot continue "
        "until the connector is installed."
    )
    assert agent_workflow_invariant_violations(text) == ("missing_paperclip_first_path",)


def test_agent_workflow_invariant_allows_capability_gap_reporting():
    text = (
        "Prefer Paperclip MCP/API for live inspection. If unavailable, record a "
        "capability gap and continue with local read-only audits."
    )
    assert agent_workflow_invariant_violations(text) == ()
