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
    comments = [{"body": "CEO approved this draft; publishing still pending."}]

    flags, _latest = audit.classify_issue(issue, comments)

    assert "approved_without_publish_marker" in flags
