"""Unit tests for the skill catalog preflight in agents/_sync_config.py.

Self-contained: no DB, no network. The module under test reads its config
from process env (PAPERCLIP_URL / PAPERCLIP_API_KEY / COMPANY_ID / SCRIPT_DIR /
DRY_RUN), so we set those before import. Network calls are stubbed by
monkeypatching the module-level `api` callable.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterator

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def sync_module(tmp_path: Path) -> Iterator:
    """Load agents/_sync_config.py under a tmp SCRIPT_DIR with stub agents."""
    # Build a minimal SCRIPT_DIR layout: one agent slug with an AGENTS.md that
    # has a frontmatter `skills:` list.
    script_dir = tmp_path / "agents_root"
    (script_dir / "alpha").mkdir(parents=True)
    (script_dir / "alpha" / "AGENTS.md").write_text(
        "---\nname: Alpha\nskills:\n  - browse\n  - paperclip\n---\n# Alpha\n",
        encoding="utf-8",
    )
    (script_dir / ".paperclip.yaml").write_text(
        """
skills:
  source: https://github.com/garrytan/gstack
  ref: main
  update_method: paperclip_skill_sync
agents:
  alpha: {}
""".lstrip(),
        encoding="utf-8",
    )

    env = {
        "PAPERCLIP_URL": "https://example.test",
        "PAPERCLIP_API_KEY": "test-key",
        "COMPANY_ID": "00000000-0000-0000-0000-000000000000",
        "SCRIPT_DIR": str(script_dir),
        "DRY_RUN": "1",
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)

    sys.modules.pop("_sync_config", None)
    spec = importlib.util.spec_from_file_location(
        "_sync_config", REPO_ROOT / "agents" / "_sync_config.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_sync_config"] = mod
    spec.loader.exec_module(mod)
    try:
        yield mod
    finally:
        sys.modules.pop("_sync_config", None)
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _by_slug_with_skills(slug: str, current_skills: list[str]) -> dict[str, dict]:
    return {
        slug: {
            "id": "agent-id",
            "urlKey": slug,
            "adapterConfig": {
                "paperclipSkillSync": {"desiredSkills": list(current_skills)},
            },
        }
    }


def test_preflight_emits_required_keys(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        sync_module,
        "api",
        lambda method, path, body=None: [
            {"path": "garrytan/gstack/browse"},
            {"path": "paperclipai/paperclip/paperclip"},
        ],
    )
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {
        "skills": {
            "source": "https://github.com/garrytan/gstack",
            "ref": "v1.2.3",
            "update_method": "paperclip_skill_sync",
        },
        "agents": {"alpha": {}},
    }
    state = sync_module.preflight_skills(by_slug, manifest)
    out = capsys.readouterr().out

    assert state["upstream_source"] == "https://github.com/garrytan/gstack"
    assert state["upstream_ref"] == "v1.2.3"
    assert state["checked_count"] == 2
    assert state["updated_count"] == 2  # browse + paperclip newly added
    assert state["failed_count"] == 0
    assert state["stale_count"] == 0
    assert state["removed_count"] == 0
    assert state["update_method"] == "paperclip_skill_sync"
    # Required keys must be in stdout for operator visibility.
    for key in (
        "upstream_ref",
        "checked_count",
        "updated_count",
        "failed_count",
        "stale_count",
        "removed_count",
        "update_method",
    ):
        assert key in out


def test_preflight_flags_unknown_desired_skill(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        sync_module,
        "api",
        lambda method, path, body=None: [
            # `browse` exists, `paperclip` is missing from the catalog → unknown.
            {"path": "garrytan/gstack/browse"},
        ],
    )
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {
        "skills": {"source": "u", "ref": "main"},
        "agents": {"alpha": {}},
    }
    state = sync_module.preflight_skills(by_slug, manifest)
    out = capsys.readouterr().out
    assert state["failed_count"] == 1
    assert state["unknown_desired_skills"] == ["paperclipai/paperclip/paperclip"]
    assert "unknown_desired_skills" in out


def test_preflight_flags_incompatible_catalog_entry(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        sync_module,
        "api",
        lambda method, path, body=None: [
            {"path": "garrytan/gstack/browse", "compatibility": "incompatible"},
            {"path": "paperclipai/paperclip/paperclip", "compatibility": "compatible"},
        ],
    )
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {"skills": {"ref": "main"}, "agents": {"alpha": {}}}
    state = sync_module.preflight_skills(by_slug, manifest)
    out = capsys.readouterr().out
    assert state["failed_count"] == 0
    assert state["stale_count"] == 1
    assert state["stale_desired_skills"] == ["garrytan/gstack/browse"]
    assert "stale_desired_skills" in out


def test_preflight_skips_validation_when_catalog_unreachable(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def boom(method, path, body=None):
        raise urllib.error.HTTPError(path, 404, "Not Found", {}, None)

    monkeypatch.setattr(sync_module, "api", boom)
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {"skills": {"ref": "main"}, "agents": {"alpha": {}}}
    state = sync_module.preflight_skills(by_slug, manifest)
    out = capsys.readouterr().out
    assert state["failed_count"] == 0
    assert state["catalog_validation"].startswith("skipped")
    assert "skipped" in out


def test_preflight_counts_removals(sync_module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sync_module,
        "api",
        lambda method, path, body=None: [
            {"path": "garrytan/gstack/browse"},
            {"path": "paperclipai/paperclip/paperclip"},
            {"path": "garrytan/gstack/gone-skill"},
        ],
    )
    # Currently has both target skills + an extra gstack skill no longer
    # listed in frontmatter, plus a paperclipai/* skill that should be
    # preserved by `compute_desired_skills`.
    by_slug = _by_slug_with_skills(
        "alpha",
        [
            "garrytan/gstack/browse",
            "garrytan/gstack/gone-skill",
            "paperclipai/paperclip/paperclip",
        ],
    )
    manifest = {"skills": {"ref": "main"}, "agents": {"alpha": {}}}
    state = sync_module.preflight_skills(by_slug, manifest)
    assert state["updated_count"] == 0  # both target skills already present
    assert state["removed_count"] == 1
    assert state["failed_count"] == 0


def test_preflight_unpinned_ref_label(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(sync_module, "api", lambda *a, **k: [])
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {"skills": {}, "agents": {"alpha": {}}}
    state = sync_module.preflight_skills(by_slug, manifest)
    capsys.readouterr()
    assert state["upstream_ref"] == "unpinned"


def test_skill_preflight_only_skips_secret_and_routine_calls(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    calls: list[str] = []

    def fake_api(method, path, body=None):
        calls.append(path)
        if path.endswith("/agents"):
            return [
                {
                    "id": "agent-id",
                    "urlKey": "alpha",
                    "adapterConfig": {"paperclipSkillSync": {"desiredSkills": []}},
                }
            ]
        if path.endswith("/skills"):
            return [
                {"path": "garrytan/gstack/browse"},
                {"path": "paperclipai/paperclip/paperclip"},
            ]
        raise AssertionError(f"unexpected API call in skills-only mode: {path}")

    monkeypatch.setattr(sync_module, "api", fake_api)
    monkeypatch.setattr(sync_module, "SKILL_PREFLIGHT_ONLY", True)

    assert sync_module.main() == 0
    out = capsys.readouterr().out
    assert "Skill catalog preflight" in out
    assert not any(path.endswith("/secrets") for path in calls)
    assert not any(path.endswith("/routines") for path in calls)


def test_skill_preflight_only_fails_for_unknown_desired_skill(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fake_api(method, path, body=None):
        if path.endswith("/agents"):
            return [
                {
                    "id": "agent-id",
                    "urlKey": "alpha",
                    "adapterConfig": {"paperclipSkillSync": {"desiredSkills": []}},
                }
            ]
        if path.endswith("/skills"):
            return [{"path": "garrytan/gstack/browse"}]
        raise AssertionError(f"unexpected API call in skills-only mode: {path}")

    monkeypatch.setattr(sync_module, "api", fake_api)
    monkeypatch.setattr(sync_module, "SKILL_PREFLIGHT_ONLY", True)

    assert sync_module.main() == 1
    captured = capsys.readouterr()
    assert "unknown_desired_skills" in captured.out
    assert "desired skill(s) not in Paperclip catalog" in captured.err


def test_skill_preflight_only_fails_for_stale_desired_skill(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fake_api(method, path, body=None):
        if path.endswith("/agents"):
            return [
                {
                    "id": "agent-id",
                    "urlKey": "alpha",
                    "adapterConfig": {"paperclipSkillSync": {"desiredSkills": []}},
                }
            ]
        if path.endswith("/skills"):
            return [
                {"path": "garrytan/gstack/browse", "compatibility": "incompatible"},
                {"path": "paperclipai/paperclip/paperclip", "compatibility": "compatible"},
            ]
        raise AssertionError(f"unexpected API call in skills-only mode: {path}")

    monkeypatch.setattr(sync_module, "api", fake_api)
    monkeypatch.setattr(sync_module, "SKILL_PREFLIGHT_ONLY", True)

    assert sync_module.main() == 1
    captured = capsys.readouterr()
    assert "stale_desired_skills" in captured.out
    assert "desired skill(s) incompatible with Paperclip catalog" in captured.err


def test_skill_preflight_only_fails_when_catalog_validation_skipped(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    def fake_api(method, path, body=None):
        if path.endswith("/agents"):
            return [
                {
                    "id": "agent-id",
                    "urlKey": "alpha",
                    "adapterConfig": {"paperclipSkillSync": {"desiredSkills": []}},
                }
            ]
        if path.endswith("/skills"):
            return []
        raise AssertionError(f"unexpected API call in skills-only mode: {path}")

    monkeypatch.setattr(sync_module, "api", fake_api)
    monkeypatch.setattr(sync_module, "SKILL_PREFLIGHT_ONLY", True)

    assert sync_module.main() == 1
    captured = capsys.readouterr()
    assert "catalog_validation: skipped (empty catalog)" in captured.out
    assert "skill catalog validation skipped" in captured.err


def test_deploy_skill_preflight_propagates_config_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
body=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o)
      body="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
printf '[]' > "$body"
printf '200'
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    python = bin_dir / "python3"
    python.write_text(
        """#!/usr/bin/env bash
exit 1
""",
        encoding="utf-8",
    )
    python.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "agents" / "deploy.sh"), "--skill-preflight"],
        env={
            **os.environ,
            "PAPERCLIP_URL": "https://example.test",
            "PAPERCLIP_API_KEY": "test-key",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Config sync failed." in result.stderr
    assert "Skill preflight failed with 1 error(s)." in result.stderr
    assert "Skill preflight complete." not in result.stdout


def test_deploy_skill_preflight_fails_for_stale_desired_skill(tmp_path: Path) -> None:
    script_dir = tmp_path / "agents"
    script_dir.mkdir()
    shutil.copy(REPO_ROOT / "agents" / "deploy.sh", script_dir / "deploy.sh")
    shutil.copy(REPO_ROOT / "agents" / "_sync_config.py", script_dir / "_sync_config.py")
    (script_dir / "deploy.sh").chmod(0o755)
    (script_dir / "alpha").mkdir()
    (script_dir / "alpha" / "AGENTS.md").write_text(
        "---\nname: Alpha\nskills:\n  - browse\n  - paperclip\n---\n# Alpha\n",
        encoding="utf-8",
    )
    (script_dir / ".paperclip.yaml").write_text(
        """
skills:
  source: https://github.com/garrytan/gstack
  ref: main
  update_method: paperclip_skill_sync
agents:
  alpha: {}
""".lstrip(),
        encoding="utf-8",
    )

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "paperclip_http.py", scripts_dir / "paperclip_http.py")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path.endswith("/agents"):
                self._send_json(
                    [
                        {
                            "id": "agent-id",
                            "urlKey": "alpha",
                            "adapterConfig": {"paperclipSkillSync": {"desiredSkills": []}},
                        }
                    ]
                )
                return
            if self.path.endswith("/skills"):
                self._send_json(
                    [
                        {"path": "garrytan/gstack/browse", "compatibility": "incompatible"},
                        {
                            "path": "paperclipai/paperclip/paperclip",
                            "compatibility": "compatible",
                        },
                    ]
                )
                return
            self.send_response(404)
            self.end_headers()

        def _send_json(self, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            ["bash", str(script_dir / "deploy.sh"), "--skill-preflight"],
            env={
                **os.environ,
                "PAPERCLIP_URL": f"http://127.0.0.1:{server.server_port}",
                "PAPERCLIP_API_KEY": "test-key",
            },
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        server.shutdown()
        thread.join()

    assert result.returncode == 1
    assert "stale_desired_skills" in result.stdout
    assert "desired skill(s) incompatible with Paperclip catalog" in result.stderr
    assert "Config sync failed." in result.stderr
    assert "Skill preflight failed with 1 error(s)." in result.stderr
    assert "Skill preflight complete." not in result.stdout


def test_routine_patch_payload_includes_latest_revision_id(sync_module) -> None:
    payload = sync_module.routine_patch_payload(
        {"latestRevisionId": "rev-123"},
        "new description\n",
    )
    assert payload == {
        "description": "new description\n",
        "baseRevisionId": "rev-123",
    }


def test_routine_patch_payload_accepts_nested_revision_id(sync_module) -> None:
    payload = sync_module.routine_patch_payload(
        {"latestRevision": {"id": "rev-456"}},
        "new description\n",
    )
    assert payload["baseRevisionId"] == "rev-456"


def test_routine_patch_payload_omits_revision_for_older_server(sync_module) -> None:
    payload = sync_module.routine_patch_payload({}, "new description\n")
    assert payload == {"description": "new description\n"}
