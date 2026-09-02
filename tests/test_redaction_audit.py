"""Unit tests for scripts/redaction_audit.py.

Self-contained: no DB, no network. Each test writes a fixture file under
a tmp_path and runs `scan(...)` against it. The repo-relative allowlist
is bypassed because tmp paths are not in ALLOWLIST_PATHS.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "redaction_audit.py"

_spec = importlib.util.spec_from_file_location("redaction_audit", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["redaction_audit"] = _module
_spec.loader.exec_module(_module)


def _scan_file(tmp_path: Path, content: str, name: str = "fixture.md") -> list:
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")
    # Patch REPO_ROOT to tmp so `scan_file` reads relative to tmp.
    original_root = _module.REPO_ROOT
    _module.REPO_ROOT = tmp_path
    try:
        return _module.scan_file(name)
    finally:
        _module.REPO_ROOT = original_root


def test_clean_file(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        """
        Mention secrets by env var name: ANALYST_DATABASE_URL.
        Issue: FFM-1234. Routine: QA Log Scan.
        """,
    )
    assert findings == []


def test_legacy_public_trigger_path_is_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "POST https://automation.example/api/routine-triggers/public/910d844a954042dc060c56bf/fire",
    )
    assert len(findings) == 1
    assert findings[0].pattern == "legacy_public_trigger_path"


def test_bearer_literal_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "Authorization: Bearer abcdef1234567890ABCDEF.signed_payload",
    )
    assert len(findings) == 1
    assert findings[0].pattern == "bearer_literal"


def test_bearer_envvar_reference_is_clean(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        """
        -H "Authorization: Bearer $SERVICE_API_KEY"
        -H "Authorization: Bearer ${SERVICE_API_KEY}"
        -H "Authorization: Bearer <token>"
        """,
    )
    assert findings == []


def test_postgres_url_with_password_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "DB: postgresql://prod_user:HotPassword2026@db.internal:5432/app",
    )
    assert any(f.pattern == "db_url_with_password" for f in findings)


def test_postgres_url_with_real_password_on_db_host_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "DATABASE_URL=postgresql://prod_user:HotPassword2026@db:5432/app",
    )
    assert any(f.pattern == "db_url_with_password" for f in findings)


def test_postgres_placeholders_clean(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        """
        DATABASE_URL=postgresql+asyncpg://app:app@app_db:5432/app
        ANALYST_DATABASE_URL=postgresql://analyst_readonly:changeme@localhost:65432/app
        EXAMPLE=postgres://${PG_USER}:${PG_PASS}@host/db
        """,
    )
    assert findings == []


def test_openai_api_key_flagged(tmp_path: Path) -> None:
    findings = _scan_file(tmp_path, "OPENAI_API_KEY=sk-abcdefghijABCDEFGHIJ1234567890xyz")
    assert any(f.pattern == "openai_api_key" for f in findings)


def test_aws_access_key_flagged(tmp_path: Path) -> None:
    # AKIA tokens containing "EXAMPLE" are heuristically skipped (AWS docs use them).
    clean = _scan_file(tmp_path, "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
    assert clean == []
    findings = _scan_file(tmp_path, "AWS_ACCESS_KEY_ID=AKIA0123456789ABCDEF")
    assert any(f.pattern == "aws_access_key" for f in findings)


def test_telegram_bot_token_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "TELEGRAM_BOT_TOKEN=1234567890:AAHfaiTHEqu6oH4rXtGrTHISisBOGUS-token1234",
    )
    assert any(f.pattern == "telegram_bot_token" for f in findings)


def test_telegram_placeholder_clean(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "# .env.example: TELEGRAM_BOT_TOKEN=234234:esfgdfsbfd",
    )
    # too-short alpha tail (10 chars) — not flagged.
    assert findings == []


def test_telethon_session_string_flagged(tmp_path: Path) -> None:
    blob = "1Aa" + ("ABcdef9876_" * 10)
    findings = _scan_file(tmp_path, f"TELEGRAM_SESSION_STRING={blob}")
    assert any(f.pattern == "telethon_session_string" for f in findings)


def test_private_key_block_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIB...\n-----END RSA PRIVATE KEY-----",
    )
    assert any(f.pattern == "private_key_block" for f in findings)


def test_secret_reference_uuid_flagged(tmp_path: Path) -> None:
    findings = _scan_file(
        tmp_path,
        "service_secret_id: 96ee7b2e-6df2-43c8-bbe3-53e19297308a",
    )
    assert any(f.pattern == "secret_reference_uuid" for f in findings)


def test_real_repo_audit_clean() -> None:
    """End-to-end: scanning the actual tracked file list must come back clean."""
    paths = _module.list_tracked_files()
    findings = _module.scan(paths)
    if findings:
        rendered = "\n".join(f.format() for f in findings)
        pytest.fail(f"redaction-audit found tracked secret material:\n{rendered}")
