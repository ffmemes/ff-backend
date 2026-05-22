#!/usr/bin/env python3
"""Read-only local agent workflow doctor.

Checks command availability and repo contracts that should be true before an
agent starts Paperclip/architecture work. This script never reads secret files,
does not print secret values, and does not call network services.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
AGENT_WORKFLOW_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/agents/*.md",
    "docs/adr/*.md",
    "agents/*/AGENTS.md",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


def _literal_list_assignment(source: str, name: str) -> list[str] | None:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{name} must be a literal list[str]")
        return value
    return None


def extract_vision_models(path: Path) -> list[str]:
    """Extract VISION_MODELS without importing src settings or dependencies."""
    source = path.read_text(encoding="utf-8")
    model_ids = _literal_list_assignment(source, "VISION_MODELS")
    if model_ids is None:
        raise ValueError(f"VISION_MODELS assignment not found in {path}")
    return model_ids


def non_free_openrouter_models(model_ids: Iterable[str]) -> list[str]:
    return [model_id for model_id in model_ids if not model_id.endswith(":free")]


def check_command_available(command: str) -> CheckResult:
    path = shutil.which(command)
    if path:
        return CheckResult(f"command:{command}", True, path)
    return CheckResult(f"command:{command}", False, "not found on PATH")


def check_describe_memes_models(root: Path = ROOT) -> CheckResult:
    paths = (
        root / "src" / "flows" / "storage" / "describe_memes.py",
        root / "src" / "flows" / "storage" / "openrouter_vision.py",
    )
    errors: list[str] = []
    for path in paths:
        try:
            model_ids = extract_vision_models(path)
            source_path = path
            break
        except Exception as exc:
            errors.append(str(exc))
    else:
        return CheckResult("describe_memes:free_models", False, "; ".join(errors))

    paid = non_free_openrouter_models(model_ids)
    if paid:
        return CheckResult(
            "describe_memes:free_models",
            False,
            "non-free model ids: " + ", ".join(paid),
        )
    return CheckResult(
        "describe_memes:free_models",
        True,
        f"{len(model_ids)} free model(s) in {source_path.relative_to(root)}",
    )


def check_paperclip_access_adapter(
    root: Path = ROOT,
    env: dict[str, str] | None = None,
    command_resolver=shutil.which,
) -> CheckResult:
    """Verify a Paperclip access path exists for this runtime.

    Codex desktop uses the repo-local `.codex` wrapper. Paperclip-managed
    agents run inside a different checkout where `.codex` is intentionally not
    tracked; there the native `paperclipai` CLI plus Paperclip env bindings are
    the valid adapter.
    """
    env = dict(os.environ if env is None else env)
    skill = root / ".codex" / "skills" / "paperclip" / "SKILL.md"
    wrapper = root / ".codex" / "paperclip-tools" / "paperclipai-ffmemes.sh"
    missing = [str(path.relative_to(root)) for path in (skill, wrapper) if not path.exists()]
    if not missing and wrapper.stat().st_mode & 0o111:
        return CheckResult("paperclip:access_adapter", True, "repo-local wrapper present")

    native_cli = command_resolver("paperclipai")
    native_url = bool(env.get("PAPERCLIP_URL") or env.get("PAPERCLIP_API_URL"))
    native_key = bool(env.get("PAPERCLIP_API_KEY"))
    if native_cli and native_url and native_key:
        return CheckResult("paperclip:access_adapter", True, "native Paperclip CLI/env present")

    adapter_gaps: list[str] = []
    if missing:
        adapter_gaps.append("repo-local wrapper missing: " + ", ".join(missing))
    elif not wrapper.stat().st_mode & 0o111:
        adapter_gaps.append("repo-local wrapper is not executable")
    native_missing = []
    if not native_cli:
        native_missing.append("paperclipai")
    if not native_url:
        native_missing.append("PAPERCLIP_URL|PAPERCLIP_API_URL")
    if not native_key:
        native_missing.append("PAPERCLIP_API_KEY")
    if native_missing:
        adapter_gaps.append("native adapter missing: " + ", ".join(native_missing))
    return CheckResult("paperclip:access_adapter", False, "; ".join(adapter_gaps))


def check_paperclip_contracts_importable() -> CheckResult:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        import paperclip_contracts
    except Exception as exc:
        return CheckResult("paperclip:contracts", False, f"import failed: {exc}")

    required = {
        "agent_workflow_invariant_violations",
        "nested_state",
        "parent_child_status_violation",
    }
    missing = sorted(name for name in required if not hasattr(paperclip_contracts, name))
    if missing:
        return CheckResult("paperclip:contracts", False, "missing: " + ", ".join(missing))
    return CheckResult("paperclip:contracts", True, "pure contract helpers import")


def check_agent_workflow_invariants(
    root: Path = ROOT,
    patterns: Iterable[str] = AGENT_WORKFLOW_PATHS,
) -> CheckResult:
    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        from paperclip_contracts import agent_workflow_invariant_violations
    except Exception as exc:
        return CheckResult("agent_docs:workflow_invariants", False, f"import failed: {exc}")

    violations: list[str] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            names = agent_workflow_invariant_violations(path.read_text(encoding="utf-8"))
            if names:
                rel = path.relative_to(root)
                violations.append(f"{rel}: {', '.join(names)}")

    if violations:
        return CheckResult("agent_docs:workflow_invariants", False, "; ".join(violations))
    return CheckResult("agent_docs:workflow_invariants", True, "no forbidden workflow patterns")


def run_checks(commands: Iterable[str] = ("git", "python3", "rg", "pytest")) -> list[CheckResult]:
    results = [check_command_available(command) for command in commands]
    results.extend(
        [
            check_describe_memes_models(),
            check_paperclip_access_adapter(),
            check_paperclip_contracts_importable(),
            check_agent_workflow_invariants(),
        ]
    )
    return results


def render_text(results: list[CheckResult]) -> str:
    lines = ["agent-doctor:"]
    for result in results:
        status = "ok" if result.ok else "fail"
        lines.append(f"  [{status}] {result.name}: {result.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    results = run_checks()
    if args.json:
        print(json.dumps([result.as_dict() for result in results], indent=2, sort_keys=True))
    else:
        print(render_text(results))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
