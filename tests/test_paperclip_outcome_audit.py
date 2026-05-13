"""Focused tests for the Paperclip outcome audit.

These stay network-free: the live API client is injected behind the small
`Paperclip` facade, and the experiment log path is monkeypatched to a temp file.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import paperclip_outcome_audit as audit  # noqa: E402


class _FakeClient:
    def __init__(self) -> None:
        self.seen_limit: int | None | object = object()

    def paginate(self, path: str, **kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.seen_limit = kwargs["limit"]
        return (
            [{"id": f"issue-{index}", "status": "done"} for index in range(501)],
            {"truncated": False, "reason": None, "atOffset": None},
        )


def test_list_issues_default_has_no_global_500_ceiling():
    client = _FakeClient()
    issues, truncation = audit.list_issues(client, "company-id", None)  # type: ignore[arg-type]

    assert client.seen_limit is None
    assert len(issues) == 501
    assert truncation["truncated"] is False
    assert truncation["requestedLimit"] is None
    assert truncation["query"] == {"status": audit.ALL_STATUSES}


def test_log_events_maps_known_legacy_alias_without_drift_flag(tmp_path, monkeypatch):
    log_path = tmp_path / "log.jsonl"
    log_path.write_text(
        "\n".join(
            [
                (
                    '{"timestamp":"2026-05-13T07:22:00Z","agent":"comms-manager",'
                    '"action":"daily_post","status":"success","summary":"published"}'
                ),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "LOG_PATH", log_path)

    result = audit.log_events(datetime(2026, 5, 13, tzinfo=timezone.utc))

    assert result["counts"]["outcomes"] == 1
    assert result["aliasDrift"] == {}
    assert result["mappedAliases"] == {"daily_post->daily_channel_post": 1}
    assert result["outcomes"][0]["canonicalAction"] == "daily_channel_post"
