"""Regression tests for the repo-local Paperclip CLI wrapper."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / ".codex" / "paperclip-tools" / "paperclipai-ffmemes.sh"
DEFAULT_NPM_CACHE = REPO_ROOT / ".codex" / "paperclip-tools" / ".npm-cache"


def _fake_npx(fake_bin: Path) -> Path:
    npx = fake_bin / "npx"
    npx.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf 'NPM_CONFIG_CACHE=%s\\n' "${NPM_CONFIG_CACHE:-}"
printf 'npm_config_cache=%s\\n' "${npm_config_cache:-}"
printf 'args=%s\\n' "$*"
""",
        encoding="utf-8",
    )
    npx.chmod(0o755)
    return npx


def test_wrapper_uses_repo_local_npm_cache_for_npx_fallback(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_npx(fake_bin)

    env = os.environ.copy()
    env.pop("NPM_CONFIG_CACHE", None)
    env.pop("npm_config_cache", None)
    env.pop("PAPERCLIPAI_BIN", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["PAPERCLIPAI_VERSION"] = "test-version"

    result = subprocess.run(
        ["bash", str(WRAPPER), "--version"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"NPM_CONFIG_CACHE={DEFAULT_NPM_CACHE}" in result.stdout
    assert f"npm_config_cache={DEFAULT_NPM_CACHE}" in result.stdout
    assert "args=--yes paperclipai@test-version --version" in result.stdout


def test_wrapper_honors_explicit_npm_cache_override(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_npx(fake_bin)
    override_cache = tmp_path / "npm-cache"

    env = os.environ.copy()
    env.pop("npm_config_cache", None)
    env.pop("PAPERCLIPAI_BIN", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["NPM_CONFIG_CACHE"] = str(override_cache)

    result = subprocess.run(
        ["bash", str(WRAPPER), "issue", "list"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"NPM_CONFIG_CACHE={override_cache}" in result.stdout
    assert f"npm_config_cache={override_cache}" in result.stdout
    assert override_cache.is_dir()


def test_wrapper_overwrites_stale_lowercase_npm_cache(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _fake_npx(fake_bin)
    stale_cache = tmp_path / "stale-cache"

    env = os.environ.copy()
    env.pop("NPM_CONFIG_CACHE", None)
    env.pop("PAPERCLIPAI_BIN", None)
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["npm_config_cache"] = str(stale_cache)

    result = subprocess.run(
        ["bash", str(WRAPPER), "--version"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"NPM_CONFIG_CACHE={DEFAULT_NPM_CACHE}" in result.stdout
    assert f"npm_config_cache={DEFAULT_NPM_CACHE}" in result.stdout
    assert f"npm_config_cache={stale_cache}" not in result.stdout
