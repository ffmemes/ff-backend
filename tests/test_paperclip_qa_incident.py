"""Fixture tests for the QA Engineer runtime + incident-dedupe contract."""

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

from paperclip_qa_incident import (  # noqa: E402
    DEFAULT_NEW_ISSUE_CAP,
    KNOWN_INCIDENT_SLUGS,
    MAINTENANCE_ACCESS_SLUG,
    REQUIRED_ENV_VARS,
    incident_decision,
    incident_slug_for,
    qa_runtime_probe,
    render_decision_summary,
    scan_summary,
)


def test_required_env_vars_match_prompt():
    expected = {
        "ANALYST_DATABASE_URL",
        "COOLIFY_BASE_URL",
        "COOLIFY_ACCESS_TOKEN",
        "SENTRY_AUTH_TOKEN",
        "PREFECT_API_URL",
        "PREFECT_AUTH_STRING",
    }
    assert set(REQUIRED_ENV_VARS) == expected


def test_runtime_probe_green_path():
    env = {name: "value" for name in REQUIRED_ENV_VARS}
    env["PATH"] = "/usr/bin:/paperclip/bin"
    probe = qa_runtime_probe(env)
    assert probe.status == "green"
    assert probe.missing_env == ()
    assert probe.missing_path_fragments == ()
    assert probe.maintenance_slug == MAINTENANCE_ACCESS_SLUG


def test_runtime_probe_yellow_one_missing():
    env = {name: "value" for name in REQUIRED_ENV_VARS}
    env["COOLIFY_ACCESS_TOKEN"] = ""
    env["PATH"] = "/paperclip/bin"
    probe = qa_runtime_probe(env)
    assert probe.status == "yellow"
    assert probe.missing_env == ("COOLIFY_ACCESS_TOKEN",)


def test_runtime_probe_yellow_path_fragment_missing():
    env = {name: "value" for name in REQUIRED_ENV_VARS}
    env["PATH"] = "/usr/bin"
    probe = qa_runtime_probe(env)
    assert probe.status == "yellow"
    assert probe.missing_path_fragments == ("/paperclip/bin",)


def test_runtime_probe_red_when_all_missing():
    env = {"PATH": ""}
    probe = qa_runtime_probe(env)
    assert probe.status == "red"
    assert set(probe.missing_env) == set(REQUIRED_ENV_VARS)


def test_incident_decision_describe_memes_skipped():
    decision = incident_decision(
        {"title": "describe_memes circuit breaker tripped", "level": "error"}
    )
    assert decision.decision == "skip_known"


def test_incident_decision_openrouter_402_skipped():
    decision = incident_decision({"title": "OpenRouter 402: free-tier exhausted", "level": "error"})
    assert decision.decision == "skip_known"


def test_incident_decision_forbidden_skipped():
    decision = incident_decision(
        {"title": "telegram.error.Forbidden user blocked the bot", "level": "warning"}
    )
    assert decision.decision == "skip_known"


def test_incident_decision_db_pool_dedupes_to_canonical_slug():
    decision = incident_decision(
        {"title": "asyncpg.exceptions.TooManyConnectionsError", "level": "error"}
    )
    assert decision.decision == "comment_existing"
    assert decision.incident_slug == "[incident:db-pool]"


def test_incident_decision_score_column_dedupes():
    decision = incident_decision(
        {"title": "ProgrammingError: score column does not exist", "level": "error"}
    )
    assert decision.decision == "comment_existing"
    assert decision.incident_slug == "[incident:goat-score-column]"


def test_incident_decision_critical_level_escalates():
    # `fatal` outranks the noise list — production-down is never silenced.
    decision = incident_decision({"title": "Bot fully down — webhook 502", "level": "fatal"})
    assert decision.decision == "escalate_critical"


def test_incident_decision_known_recurring_overrides_critical_for_specific_slug():
    # A `db-pool` event remains `comment_existing` even at error level —
    # the canonical slug is the dedupe target.
    decision = incident_decision({"title": "asyncpg TooManyConnectionsError", "level": "error"})
    assert decision.decision == "comment_existing"


def test_incident_decision_create_new_for_genuinely_new_event():
    decision = incident_decision(
        {"title": "AttributeError: NoneType has no attribute 'language_code'", "level": "error"}
    )
    assert decision.decision == "create_new"


def test_incident_slug_for_returns_none_for_unknown():
    assert incident_slug_for({"title": "Some new issue"}) is None


def test_incident_slug_for_canonical_known_slugs_match_map():
    expected = set(KNOWN_INCIDENT_SLUGS.values())
    assert "[incident:db-pool]" in expected
    assert "[incident:goat-score-column]" in expected


def test_scan_summary_under_cap_returns_individuals():
    events = [
        {"title": "AttributeError: foo"},
        {"title": "TypeError: bar"},
        {"title": "describe_memes failed"},
        {"title": "TooManyConnectionsError"},
    ]
    summary = scan_summary(events)
    assert len(summary.new_issues) == 2
    assert len(summary.skipped) == 1
    assert len(summary.deduped) == 1
    assert summary.batch_slug is None
    assert summary.batch_items == ()


def test_scan_summary_overflow_batches_into_scan_slug():
    events = [{"title": f"NEW {i}: AttributeError unique-{i}"} for i in range(5)]
    summary = scan_summary(events, scan_slug="[scan:2026-04-25-1200]")
    assert len(summary.new_issues) == DEFAULT_NEW_ISSUE_CAP
    assert summary.batch_slug == "[scan:2026-04-25-1200]"
    assert len(summary.batch_items) == 5 - DEFAULT_NEW_ISSUE_CAP


def test_scan_summary_overflow_without_slug_raises():
    events = [{"title": f"NEW {i}: AttributeError unique-{i}"} for i in range(5)]
    with pytest.raises(ValueError):
        scan_summary(events)


def test_scan_summary_critical_route_separately():
    events = [
        {"title": "Bot down — webhook 502", "level": "fatal"},
        {"title": "AttributeError: foo"},
    ]
    summary = scan_summary(events)
    assert len(summary.critical) == 1
    assert len(summary.new_issues) == 1


def test_render_decision_summary_shape():
    env = {name: "value" for name in REQUIRED_ENV_VARS}
    env["PATH"] = "/paperclip/bin"
    summary = render_decision_summary(
        env,
        [
            {"title": "describe_memes free tier exhausted"},
            {"title": "asyncpg TooManyConnectionsError"},
            {"title": "AttributeError: NoneType"},
        ],
    )
    assert summary["runtime"]["status"] == "green"
    assert summary["counts"]["skipped"] == 1
    assert summary["counts"]["deduped"] == 1
    assert summary["counts"]["new_issues"] == 1
    assert summary["counts"]["critical"] == 0
    assert "[incident:db-pool]" in summary["deduped_slugs"]


def test_dry_run_cli_runs_without_network(tmp_path):
    events_path = tmp_path / "events.json"
    env_path = tmp_path / "env.json"
    events_path.write_text(json.dumps([{"title": "AttributeError: foo"}]))
    env_path.write_text(
        json.dumps({"PATH": "/paperclip/bin", **{name: "v" for name in REQUIRED_ENV_VARS}})
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "paperclip_qa_incident.py"),
            "--events",
            str(events_path),
            "--env",
            str(env_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["runtime"]["status"] == "green"
    assert payload["counts"]["new_issues"] == 1
