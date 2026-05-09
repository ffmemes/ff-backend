"""Fixture tests for the Comms Manager post-lifecycle contract.

Covers slug shape, idempotency-key derivation, lifecycle classification,
24h staleness, next-action selection, and the publish-outcome verifier.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_comms_post import (  # noqa: E402
    LIFECYCLE_STATES,
    PUBLISH_REQUIRED_FIELDS,
    archive_path,
    confirmation_idempotency_key,
    is_stale_draft,
    lifecycle_state,
    next_action,
    parse_post_slug,
    post_slug,
    publish_outcome_missing,
    render_decision_summary,
)


def test_post_slug_shape():
    assert post_slug("2026-04-25", "dau-delta") == "[post:2026-04-25-dau-delta]"


@pytest.mark.parametrize("bad_topic", ["", "DAU-delta", "spaces here", "_underscore", "-leading"])
def test_post_slug_rejects_bad_topics(bad_topic):
    with pytest.raises(ValueError):
        post_slug("2026-04-25", bad_topic)


def test_post_slug_rejects_bad_date():
    with pytest.raises(ValueError):
        post_slug("2026/04/25", "dau-delta")


def test_parse_post_slug_round_trip():
    slug = post_slug("2026-04-25", "dau-delta")
    assert parse_post_slug(slug) == ("2026-04-25", "dau-delta")


def test_parse_post_slug_handles_extra_text():
    assert parse_post_slug("[post:2026-04-25-dau-delta] DAU spike on Thursday") == (
        "2026-04-25",
        "dau-delta",
    )


def test_parse_post_slug_returns_none_for_missing_prefix():
    assert parse_post_slug("DAU spike on Thursday") is None
    assert parse_post_slug(None) is None


def test_confirmation_idempotency_key_is_stable_across_callers():
    slug = "[post:2026-04-25-dau-delta]"
    k1 = confirmation_idempotency_key(slug)
    k2 = confirmation_idempotency_key(slug)
    assert k1 == k2 == "comms.daily-channel-post.2026-04-25-dau-delta"


def test_confirmation_idempotency_key_accepts_bare_body():
    assert (
        confirmation_idempotency_key("2026-04-25-dau-delta")
        == "comms.daily-channel-post.2026-04-25-dau-delta"
    )


def test_confirmation_idempotency_key_rejects_garbage():
    with pytest.raises(ValueError):
        confirmation_idempotency_key("???")


def test_archive_path_shape():
    assert (
        archive_path("[post:2026-04-25-dau-delta]")
        == "docs/comms/published/2026-04-25-dau-delta.md"
    )


def _issue(**overrides):
    base = {
        "title": "[post:2026-04-25-dau-delta] DAU spike on Thursday",
        "description": "Anomaly post draft",
        "comments": [],
        "status": "in_review",
        "updatedAt": "2026-04-25T08:00:00Z",
    }
    base.update(overrides)
    return base


def test_lifecycle_state_missing_slug():
    assert lifecycle_state({"title": "Random thoughts"}) == "missing_slug"


def test_lifecycle_state_blocked_status():
    assert lifecycle_state(_issue(status="blocked")) == "blocked"


def test_lifecycle_state_published():
    issue = _issue(
        comments=[
            {
                "body": (
                    "outcome=published, channel=ffmemes, "
                    "telegram_message_id=999, editorial_post_id=42"
                ),
                "createdAt": "2026-04-25T10:00:00Z",
            }
        ]
    )
    assert lifecycle_state(issue) == "published"


def test_lifecycle_state_approved_unpublished():
    issue = _issue(
        comments=[
            {
                "body": "outcome=draft_created, awaiting CEO confirmation card",
                "createdAt": "2026-04-25T08:30:00Z",
            }
        ]
    )
    assert lifecycle_state(issue) == "approved_unpublished"


def test_lifecycle_state_legacy_approved_to_publish_marker():
    issue = _issue(comments=[{"body": "APPROVED_TO_PUBLISH", "createdAt": "2026-04-25T08:30:00Z"}])
    assert lifecycle_state(issue) == "approved_unpublished"


def test_lifecycle_state_pending_when_no_signal():
    assert lifecycle_state(_issue()) == "draft_pending_approval"


def test_lifecycle_state_stale_draft_marker():
    issue = _issue(
        comments=[
            {
                "body": "outcome=stale_draft — 24h passed without approval",
                "createdAt": "2026-04-26T09:00:00Z",
            }
        ]
    )
    assert lifecycle_state(issue) == "stale_draft"


def test_lifecycle_states_enumeration_complete():
    expected = {
        "missing_slug",
        "draft_pending_approval",
        "approved_unpublished",
        "stale_draft",
        "published",
        "blocked",
        "unknown",
    }
    assert set(LIFECYCLE_STATES) == expected


def test_is_stale_draft_24h_threshold():
    issue = _issue(updatedAt="2026-04-25T00:00:00Z")
    now = datetime(2026, 4, 26, 0, 0, 1, tzinfo=timezone.utc)
    assert is_stale_draft(issue, now=now) is True


def test_is_stale_draft_under_threshold():
    issue = _issue(updatedAt="2026-04-25T08:00:00Z")
    now = datetime(2026, 4, 25, 23, 0, 0, tzinfo=timezone.utc)
    assert is_stale_draft(issue, now=now) is False


def test_is_stale_draft_skipped_for_published():
    issue = _issue(
        comments=[
            {
                "body": "outcome=published, telegram_message_id=1, editorial_post_id=2",
                "createdAt": "2026-04-25T08:00:00Z",
            }
        ],
        updatedAt="2026-04-23T08:00:00Z",
    )
    now = datetime(2026, 4, 30, 0, 0, 0, tzinfo=timezone.utc)
    assert is_stale_draft(issue, now=now) is False


def test_next_action_pending_returns_request_confirmation_with_idempotency_key():
    action = next_action(_issue(), now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc))
    assert action.kind == "request_confirmation"
    assert action.suggested_payload == {
        "idempotencyKey": "comms.daily-channel-post.2026-04-25-dau-delta"
    }


def test_next_action_approved_returns_publish():
    issue = _issue(
        comments=[{"body": "outcome=draft_created", "createdAt": "2026-04-25T08:30:00Z"}]
    )
    action = next_action(issue, now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc))
    assert action.kind == "publish"


def test_next_action_published_open_returns_close():
    issue = _issue(
        status="in_review",
        comments=[
            {
                "body": "outcome=published, telegram_message_id=99, editorial_post_id=42",
                "createdAt": "2026-04-25T10:00:00Z",
            }
        ],
    )
    action = next_action(issue, now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc))
    assert action.kind == "close_published"


def test_next_action_published_done_returns_none():
    issue = _issue(
        status="done",
        comments=[
            {
                "body": "outcome=published, telegram_message_id=99, editorial_post_id=42",
                "createdAt": "2026-04-25T10:00:00Z",
            }
        ],
    )
    action = next_action(issue, now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc))
    assert action.kind == "none"


def test_next_action_stale_draft_returns_mark_stale():
    issue = _issue(updatedAt="2026-04-23T00:00:00Z")
    action = next_action(issue, now=datetime(2026, 4, 25, 0, 0, 1, tzinfo=timezone.utc))
    assert action.kind == "mark_stale"


def test_next_action_missing_slug():
    action = next_action(
        {"title": "draft", "status": "todo"}, now=datetime(2026, 4, 25, tzinfo=timezone.utc)
    )
    assert action.kind == "rename_or_create"


def test_publish_outcome_required_fields_complete():
    assert set(PUBLISH_REQUIRED_FIELDS) == {
        "outcome",
        "channel",
        "telegram_message_id",
        "editorial_post_id",
    }


def test_publish_outcome_missing_full_payload_clean():
    payload = {
        "outcome": "published",
        "channel": "ffmemes",
        "telegram_message_id": 99,
        "editorial_post_id": 42,
    }
    assert publish_outcome_missing(payload) == []


def test_publish_outcome_missing_partial_payload():
    payload = {"outcome": "published", "channel": "ffmemes"}
    assert set(publish_outcome_missing(payload)) == {"telegram_message_id", "editorial_post_id"}


def test_publish_outcome_missing_wrong_outcome_value():
    payload = {
        "outcome": "draft_created",
        "channel": "ffmemes",
        "telegram_message_id": 1,
        "editorial_post_id": 2,
    }
    assert "outcome" in publish_outcome_missing(payload)


def test_render_decision_summary_pending():
    issue = _issue()
    summary = render_decision_summary(issue, now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc))
    assert summary["slug"] == "[post:2026-04-25-dau-delta]"
    assert summary["state"] == "draft_pending_approval"
    assert summary["next_action"]["kind"] == "request_confirmation"
    assert summary["idempotency_key"] == "comms.daily-channel-post.2026-04-25-dau-delta"
    assert summary["archive_path"] == "docs/comms/published/2026-04-25-dau-delta.md"


def test_render_decision_summary_includes_publish_check():
    issue = _issue(
        comments=[{"body": "outcome=draft_created", "createdAt": "2026-04-25T08:30:00Z"}],
    )
    summary = render_decision_summary(
        issue,
        now=datetime(2026, 4, 25, 12, tzinfo=timezone.utc),
        publish_payload={"outcome": "published", "channel": "ffmemes"},
    )
    assert "telegram_message_id" in summary["publish_outcome_missing"]


def test_dry_run_cli_runs_without_network(tmp_path):
    issue_path = tmp_path / "issue.json"
    issue_path.write_text(json.dumps(_issue()))
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "paperclip_comms_post.py"),
            "--issue",
            str(issue_path),
            "--now",
            "2026-04-25T12:00:00Z",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["state"] == "draft_pending_approval"
    assert payload["next_action"]["kind"] == "request_confirmation"
