from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "agent_doctor.py"

_spec = importlib.util.spec_from_file_location("agent_doctor", SCRIPT_PATH)
assert _spec and _spec.loader
doctor = importlib.util.module_from_spec(_spec)
sys.modules["agent_doctor"] = doctor
_spec.loader.exec_module(doctor)


def test_extract_vision_models_from_literal_assignment(tmp_path: Path) -> None:
    path = tmp_path / "describe_memes.py"
    path.write_text(
        'VISION_MODELS = ["google/gemma-3-27b-it:free", "qwen/model:free"]\n',
        encoding="utf-8",
    )

    assert doctor.extract_vision_models(path) == [
        "google/gemma-3-27b-it:free",
        "qwen/model:free",
    ]


def test_non_free_openrouter_models_flags_paid_ids() -> None:
    assert doctor.non_free_openrouter_models(
        ["google/gemma-3-27b-it:free", "openai/gpt-4o-mini"]
    ) == ["openai/gpt-4o-mini"]


def test_real_describe_memes_models_are_free() -> None:
    result = doctor.check_describe_memes_models(REPO_ROOT)

    assert result.ok is True
    assert result.name == "describe_memes:free_models"


def test_paperclip_wrapper_check_is_read_only_and_present(tmp_path: Path) -> None:
    skill = tmp_path / ".codex" / "skills" / "paperclip"
    tools = tmp_path / ".codex" / "paperclip-tools"
    skill.mkdir(parents=True)
    tools.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Paperclip\n", encoding="utf-8")
    wrapper = tools / "paperclipai-ffmemes.sh"
    wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
    wrapper.chmod(0o700)

    result = doctor.check_paperclip_local_wrapper(tmp_path)

    assert result.ok is True
    assert result.name == "paperclip:local_wrapper"


def test_render_text_marks_failures() -> None:
    results = [doctor.CheckResult("example", False, "not available")]

    assert "[fail] example: not available" in doctor.render_text(results)


def test_agent_workflow_invariants_scan_passes_clean_docs(tmp_path: Path) -> None:
    doc = tmp_path / "AGENTS.md"
    doc.write_text(
        "Use the local Paperclip wrapper and report capability gaps.\n", encoding="utf-8"
    )

    result = doctor.check_agent_workflow_invariants(tmp_path, patterns=("AGENTS.md",))

    assert result.ok is True


def test_agent_workflow_invariants_scan_reports_bad_docs(tmp_path: Path) -> None:
    doc = tmp_path / "AGENTS.md"
    doc.write_text(
        "Paperclip MCP unavailable. This is a blocker; cannot continue.\n", encoding="utf-8"
    )

    result = doctor.check_agent_workflow_invariants(tmp_path, patterns=("AGENTS.md",))

    assert result.ok is False
    assert "missing_paperclip_first_path" in result.detail
