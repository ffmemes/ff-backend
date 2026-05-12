"""Unit tests for the skill catalog preflight in agents/_sync_config.py.

Self-contained: no DB, no network. The module under test reads its config
from process env (PAPERCLIP_URL / PAPERCLIP_API_KEY / COMPANY_ID / SCRIPT_DIR /
DRY_RUN), so we set those before import. Network calls are stubbed by
monkeypatching the module-level `api` callable.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import urllib.error
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
    assert state["checked"] == 2
    assert state["updated"] == 2  # browse + paperclip newly added
    assert state["removed"] == 0
    assert state["failed"] == 0
    assert state["update_method"] == "paperclip_skill_sync"
    # Required keys must be in stdout for operator visibility.
    for key in ("upstream_ref", "checked", "updated", "removed", "failed", "update_method"):
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
    assert state["failed"] == 1
    assert state["unknown_desired_skills"] == ["paperclipai/paperclip/paperclip"]
    assert "unknown_desired_skills" in out


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
    assert state["failed"] == 0
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
    assert state["updated"] == 0  # both target skills already present
    assert state["removed"] == 1
    assert state["failed"] == 0


def test_preflight_unpinned_ref_label(
    sync_module, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(sync_module, "api", lambda *a, **k: [])
    by_slug = _by_slug_with_skills("alpha", [])
    manifest = {"skills": {}, "agents": {"alpha": {}}}
    state = sync_module.preflight_skills(by_slug, manifest)
    capsys.readouterr()
    assert state["upstream_ref"] == "unpinned"


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
