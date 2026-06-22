from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_audit_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "paperclip_routine_audit.py"
    spec = importlib.util.spec_from_file_location("paperclip_routine_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    original_sys_path = list(sys.path)
    blocked_paths = {path.parent, path.parents[1]}
    sys.path[:] = [item for item in sys.path if Path(item or ".").resolve() not in blocked_paths]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_sys_path
    return module


audit = load_audit_module()


class FakePaperclip:
    def __init__(self, routes):
        self.routes = routes

    def get(self, path, query=None):
        key = (path, tuple(sorted((query or {}).items())))
        if key in self.routes:
            return self.routes[key]
        if path in self.routes:
            return self.routes[path]
        msg = f"missing fake route: {path} {query}"
        raise AssertionError(msg)


def test_pr_review_approval_comment_does_not_require_publish_markers():
    issue = {"title": "[pr:241] Review", "description": ""}
    comments = [
        {
            "body": (
                "Done: PR #241 reviewed and merged. GitHub signal: STAFF ENGINEER REVIEW: APPROVED."
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_process_health_summary_does_not_self_trigger_publish_marker_flag():
    issue = {"title": "Process Health Check", "description": ""}
    comments = [
        {
            "body": (
                "Status: YELLOW. Prior flags: approved_without_publish_marker. "
                "Referenced post FFM-1079 is awaiting CEO approval."
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_paperclip_update_verified_by_coolify_commit_is_green():
    issue = {"title": "Paperclip Update Check", "description": ""}
    comments = [
        {
            "body": (
                "Paperclip update check green.\n"
                "- health.version=not_reported\n"
                "- coolify_deployment_uuid=v8s5shyjid9n9c7l2gtghig9\n"
                "- coolify_deployment_status=finished\n"
                "- coolify_deployment_commit=3494e84a2920f3e2bc5f627f916da29e224086dc\n"
                "- latest_stable=2026.428.0\n"
                "- latest_canary=2026.508.0-canary.0\n"
                "- stable_tag_sha=3494e84a2920f3e2bc5f627f916da29e224086dc\n"
                "- impact=none\n"
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert flags == []


def test_daily_channel_post_approval_still_requires_publish_markers():
    issue = {"title": "Daily Channel Post", "description": ""}
    comments = [{"body": "decision=approved_to_publish\npublishing still pending."}]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" in flags


def test_daily_channel_post_parent_static_approval_instruction_is_not_live_approval():
    issue = {
        "title": "Daily Channel Post",
        "description": (
            "Publication gate: requires CEO-authored issue update containing "
            "decision=approved_to_publish before publishing."
        ),
    }
    comments = [{"body": "outcome=draft_created; draft issue FFM-1559 was created."}]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_daily_channel_post_parent_is_green_when_linked_post_is_published():
    parent = {
        "id": "parent-id",
        "identifier": "FFM-1558",
        "title": "Daily Channel Post",
        "status": "done",
        "description": (
            "Publication gate: requires CEO-authored issue update containing "
            "decision=approved_to_publish before publishing.\n"
            "Linked draft: FFM-1559."
        ),
    }
    child = {
        "id": "child-id",
        "identifier": "FFM-1559",
        "title": "[post:2026-06-15-text-heavy-memes] Text-heavy memes beat no-text images",
        "status": "done",
        "description": "",
        "assigneeAgentId": "comms-agent",
        "updatedAt": "2026-06-15T12:00:00Z",
    }
    routes = {
        "/api/companies/company-id/routines": [
            {
                "id": "routine-id",
                "status": "active",
                "title": "Daily Channel Post",
                "lastRun": {
                    "status": "completed",
                    "linkedIssueId": "parent-id",
                    "linkedIssue": {
                        "identifier": "FFM-1558",
                        "title": "Daily Channel Post",
                        "status": "done",
                    },
                },
            }
        ],
        "/api/issues/parent-id": parent,
        ("/api/issues/parent-id/comments", (("limit", "100"),)): [
            {"body": "outcome=draft_created; draft issue FFM-1559 was created."}
        ],
        ("/api/issues/parent-id/interactions", (("limit", "100"),)): [],
        "/api/issues/FFM-1559": child,
        ("/api/issues/child-id/comments", (("limit", "100"),)): [
            {
                "body": (
                    "outcome=published channel=ffmemes telegram_message_id=262 editorial_post_id=30"
                )
            }
        ],
        ("/api/issues/child-id/interactions", (("limit", "100"),)): [],
    }

    rows = audit.audit_routines(FakePaperclip(routes), "company-id", "comms")

    assert rows[0]["flags"] == []
    assert rows[0]["referencedPostIssues"][0]["nestedState"] == "published"


def test_daily_channel_post_parent_stays_flagged_with_mixed_referenced_posts():
    parent = {
        "id": "parent-id",
        "identifier": "FFM-1558",
        "title": "Daily Channel Post",
        "status": "done",
        "description": "Linked drafts: FFM-1559 and FFM-1560.",
    }
    published_child = {
        "id": "published-child-id",
        "identifier": "FFM-1559",
        "title": "[post:2026-06-15-text-heavy-memes] Text-heavy memes beat no-text images",
        "status": "done",
        "description": "",
        "assigneeAgentId": "comms-agent",
        "updatedAt": "2026-06-15T12:00:00Z",
    }
    approved_child = {
        "id": "approved-child-id",
        "identifier": "FFM-1560",
        "title": "[post:2026-06-15-reactions-lore] Reaction lore",
        "status": "done",
        "description": "",
        "assigneeAgentId": "comms-agent",
        "updatedAt": "2026-06-15T12:30:00Z",
    }
    routes = {
        "/api/companies/company-id/routines": [
            {
                "id": "routine-id",
                "status": "active",
                "title": "Daily Channel Post",
                "lastRun": {
                    "status": "completed",
                    "linkedIssueId": "parent-id",
                    "linkedIssue": {
                        "identifier": "FFM-1558",
                        "title": "Daily Channel Post",
                        "status": "done",
                    },
                },
            }
        ],
        "/api/issues/parent-id": parent,
        ("/api/issues/parent-id/comments", (("limit", "100"),)): [
            {
                "body": (
                    "decision=approved_to_publish before publishing.\n"
                    "Linked drafts: FFM-1559 and FFM-1560."
                )
            }
        ],
        ("/api/issues/parent-id/interactions", (("limit", "100"),)): [],
        "/api/issues/FFM-1559": published_child,
        ("/api/issues/published-child-id/comments", (("limit", "100"),)): [
            {
                "body": (
                    "outcome=published channel=ffmemes telegram_message_id=262 editorial_post_id=30"
                )
            }
        ],
        ("/api/issues/published-child-id/interactions", (("limit", "100"),)): [],
        "/api/issues/FFM-1560": approved_child,
        ("/api/issues/approved-child-id/comments", (("limit", "100"),)): [
            {"body": "decision=approved_to_publish\ndraft_revision=2"}
        ],
        ("/api/issues/approved-child-id/interactions", (("limit", "100"),)): [],
    }

    rows = audit.audit_routines(FakePaperclip(routes), "company-id", "comms")

    assert "approved_without_publish_marker" in rows[0]["flags"]
    assert "parent_done_child_non_terminal" not in rows[0]["flags"]
    assert [ref["nestedState"] for ref in rows[0]["referencedPostIssues"]] == [
        "published",
        "approved_unpublished",
    ]


def test_daily_channel_post_telegram_permalink_counts_as_published():
    issue = {"title": "[post:2026-06-15-text-heavy-memes] Daily Channel Post", "description": ""}
    comments = [
        {
            "body": (
                "decision=approved_to_publish\n"
                "Public channel preview confirmed the published post at https://t.me/ffmemes/262."
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_daily_channel_post_newline_telegram_permalink_counts_as_published():
    issue = {"title": "[post:2026-06-15-text-heavy-memes] Daily Channel Post", "description": ""}
    comments = [{"body": ("decision=approved_to_publish\nPublished:\nhttps://t.me/ffmemes/262")}]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_daily_channel_post_published_archive_counts_as_published():
    issue = {"title": "[post:2026-06-15-text-heavy-memes] Daily Channel Post", "description": ""}
    comments = [
        {
            "body": (
                "decision=approved_to_publish\n"
                "published_archive=docs/comms/published/2026-06-15-text-heavy-memes.md"
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_freeform_approval_comment_is_not_publish_approval_signal():
    issue = {"title": "Daily Channel Post", "description": ""}
    comments = [{"body": "CEO approved this draft; publishing still pending."}]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" not in flags


def test_gstack_rejected_script_import_is_degraded_green():
    issue = {"title": "gstack Update Check", "description": ""}
    comments = [
        {
            "body": (
                "Skill preflight clean: failed_count=0.\n"
                "POST /api/companies/<company-id>/skills/import failed: "
                "sourceType=github trustLevel=scripts_executables "
                "reason=scripts_executables_blocked."
            )
        }
    ]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "degraded_green" in flags
