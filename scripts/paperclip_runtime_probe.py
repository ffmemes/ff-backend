#!/usr/bin/env python3
"""Per-agent runtime probe: tool, env, and access preflight.

Reads `agents/.paperclip.yaml` plus each `agents/<slug>/AGENTS.md` and
`agents/<slug>/routines/*.yaml(+description_file)` to produce, for every
agent, a `ready` / `degraded` / `blocked` status with a concrete next
action and a canonical `[maintenance:access-*]` issue suggestion when
access is missing.

The probe is deliberately pure (no Paperclip API, no network) so it can
run inside an agent wake-up before assigning work:

    python3 scripts/paperclip_runtime_probe.py --json

Status rules (see `classify_agent`):

- `blocked`   — at least one manifest-required env or a documented hard
                tool (psql/gh/jq/etc. that the agent's prompt invokes) is
                missing from `os.environ` / PATH.
- `degraded`  — only optional envs / soft tools missing, but the agent
                can still do reduced work (e.g. fall back to dashboard).
- `ready`     — every required input is present and every documented
                tool resolves on PATH.

When access is missing, the probe emits a single canonical maintenance
issue per agent (`[maintenance:access-<agent-slug>]`) listing the missing
env-var names + tool names + blocked agents. The CLI never prints env
*values*, only names — output is safe to commit/log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / "agents"
MANIFEST_PATH = AGENTS_DIR / ".paperclip.yaml"

# Tools the probe knows how to look for. Keys are CLI binary names; values
# are the agent docs that, when they invoke the tool, escalate from
# "soft" (degraded) to "hard" (blocked) if missing.
KNOWN_TOOLS: tuple[str, ...] = (
    "gh",
    "jq",
    "psql",
    "sentry",
    "sentry-cli",
    "codex",
    "prefect",
    "curl",
    "python3",
    "ruff",
    "alembic",
    "docker",
)

# Tools that, when referenced by an agent's prompt/routine, are required
# for that agent to do its job at all. Missing → blocked. Tools not in
# this set degrade the agent but don't block it.
HARD_TOOLS: frozenset[str] = frozenset({"psql", "gh", "jq", "sentry", "sentry-cli", "codex"})

# UUID-shaped plain values (Coolify resource UUIDs, container names, etc.)
# that should not live as `default` in the manifest — they should be a
# secret_ref or a dynamic lookup.
_UUID_LIKE = re.compile(r"^[a-z0-9]{20,}(-[a-z0-9]+)*$", re.IGNORECASE)

# Any `$VAR` style reference in prompt/routine text. We use this to learn
# which optional envs an agent actually touches; an optional env that no
# prompt mentions is documentation-only and won't degrade status.
_ENV_REF = re.compile(r"\$(?:\{)?([A-Z][A-Z0-9_]{2,})(?:\})?")
# Codeblock-style command lines we mine for tool references. We only
# look at the first whitespace-delimited token after a shell prompt
# marker so noise like "to run X" doesn't pollute the matrix.
_TOOL_LINE = re.compile(r"^\s*(?:[$#>]\s+)?([a-z][a-z0-9_-]*)", re.MULTILINE)


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def discover_agent_assets(slug: str, agents_dir: Path = AGENTS_DIR) -> str:
    """Return the concatenated text of `agents/<slug>/AGENTS.md` and any
    routine description sibling files. Empty string if nothing exists."""
    chunks: list[str] = []
    md = agents_dir / slug / "AGENTS.md"
    if md.exists():
        chunks.append(md.read_text(encoding="utf-8"))
    routines_dir = agents_dir / slug / "routines"
    if routines_dir.is_dir():
        for entry in sorted(routines_dir.iterdir()):
            if entry.suffix in (".yaml", ".yml"):
                try:
                    spec = yaml.safe_load(entry.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    continue
                desc_file = spec.get("description_file")
                if desc_file:
                    desc_path = routines_dir / desc_file
                    if desc_path.exists():
                        chunks.append(desc_path.read_text(encoding="utf-8"))
            elif entry.suffix == ".md":
                chunks.append(entry.read_text(encoding="utf-8"))
    return "\n\n".join(chunks)


_LOCAL_ASSIGN = re.compile(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=", re.MULTILINE)


def extract_env_references(text: str) -> set[str]:
    """Return the set of `$ENV_VAR` names mentioned in prompts/routines.

    We exclude:
    - shell builtins (PATH, HOME, USER, …) — always present in any
      reasonable runtime and not actionable.
    - locally-assigned shell variables (`FOO=$(...)` then `$FOO` later
      in a snippet). These look like env vars to a naive regex but are
      noise — they're scratch values the example sets up itself.
    """
    SHELL_NOISE = {"PATH", "HOME", "USER", "PWD", "SHELL", "OLDPWD", "TERM", "LANG"}
    locally_assigned = {m.group(1) for m in _LOCAL_ASSIGN.finditer(text)}
    found = {m.group(1) for m in _ENV_REF.finditer(text)}
    return {name for name in found if name not in SHELL_NOISE and name not in locally_assigned}


def extract_tool_references(text: str) -> set[str]:
    """Return the subset of `KNOWN_TOOLS` referenced as commands."""
    out: set[str] = set()
    # Shell command tokens (line-anchored) — these are the strongest
    # signals.
    for match in _TOOL_LINE.finditer(text):
        token = match.group(1)
        if token in KNOWN_TOOLS:
            out.add(token)
    # Inline references like `psql $ANALYST_DATABASE_URL` or backtick
    # mentions.
    for tool in KNOWN_TOOLS:
        if re.search(rf"\b{re.escape(tool)}\b", text):
            out.add(tool)
    return out


def manifest_env_requirements(
    mblock: Mapping,
) -> tuple[set[str], set[str], list[str]]:
    """Return `(required, optional, stale_defaults)` for one manifest agent block.

    `stale_defaults` lists names whose plain default looks like a UUID /
    container suffix — those should be a secret_ref or a runtime lookup,
    not a hand-written default in the public manifest.
    """
    required: set[str] = set()
    optional: set[str] = set()
    stale: list[str] = []
    env_spec = ((mblock.get("inputs") or {}).get("env")) or {}
    for env_name, spec in env_spec.items():
        kind = (spec or {}).get("kind")
        requirement = (spec or {}).get("requirement", "optional")
        if requirement == "required":
            required.add(env_name)
        else:
            optional.add(env_name)
        if kind == "plain":
            default = str((spec or {}).get("default", ""))
            if _UUID_LIKE.match(default) and len(default) >= 20:
                stale.append(env_name)
    return required, optional, stale


def maintenance_slug(agent_slug: str) -> str:
    return f"[maintenance:access-{agent_slug}]"


def classify_agent(
    slug: str,
    *,
    mblock: Mapping,
    docs: str,
    env: Mapping[str, str],
    which: callable | None = None,
) -> dict:
    """Pure classifier: returns a dict with status + next_action.

    Args:
      slug: agent url-key
      mblock: the manifest's `agents.<slug>` block
      docs: concatenated AGENTS.md + routine description text
      env: process env mapping (typically `os.environ`)
      which: `shutil.which`-shaped callable; injectable for tests.
    """
    if which is None:
        which = shutil.which

    required, optional, stale = manifest_env_requirements(mblock)
    doc_envs = extract_env_references(docs)
    doc_tools = extract_tool_references(docs)

    missing_required: list[str] = sorted(name for name in required if not env.get(name))
    missing_optional_used: list[str] = sorted(
        name for name in optional if name in doc_envs and not env.get(name)
    )
    # Envs the prompt names but the manifest doesn't declare at all.
    undeclared_doc_envs: list[str] = sorted(
        name
        for name in doc_envs
        if name not in required
        and name not in optional
        and not env.get(name)
        # filter manifest-side noise: secret hints like FFMEMES_PROD_*
        # the agent only documents in fenced examples
        and name.isupper()
    )

    missing_hard_tools: list[str] = sorted(
        tool for tool in doc_tools if tool in HARD_TOOLS and which(tool) is None
    )
    missing_soft_tools: list[str] = sorted(
        tool
        for tool in doc_tools
        if tool not in HARD_TOOLS and tool in KNOWN_TOOLS and which(tool) is None
    )

    if missing_required or missing_hard_tools:
        status = "blocked"
    elif missing_optional_used or missing_soft_tools or undeclared_doc_envs:
        status = "degraded"
    else:
        status = "ready"

    next_action: dict | None = None
    if status != "ready":
        slug_id = maintenance_slug(slug)
        summary_bits: list[str] = []
        if missing_required:
            summary_bits.append(f"required envs missing: {missing_required}")
        if missing_hard_tools:
            summary_bits.append(f"required tools missing: {missing_hard_tools}")
        if missing_optional_used:
            summary_bits.append(f"optional envs used by prompt missing: {missing_optional_used}")
        if missing_soft_tools:
            summary_bits.append(f"soft tools missing: {missing_soft_tools}")
        if undeclared_doc_envs:
            summary_bits.append(f"prompt references undeclared envs: {undeclared_doc_envs}")
        next_action = {
            "type": "maintenance_issue",
            "slug": slug_id,
            "title": f"Access preflight for {slug}: " + "; ".join(summary_bits),
            "owner": slug,
        }

    return {
        "status": status,
        "missing_required_envs": missing_required,
        "missing_optional_used_envs": missing_optional_used,
        "missing_hard_tools": missing_hard_tools,
        "missing_soft_tools": missing_soft_tools,
        "undeclared_doc_envs": undeclared_doc_envs,
        "stale_plain_defaults": stale,
        "manifest_required_envs": sorted(required),
        "manifest_optional_envs": sorted(optional),
        "doc_referenced_envs": sorted(doc_envs),
        "doc_referenced_tools": sorted(doc_tools),
        "next_action": next_action,
    }


def build_report(
    manifest: Mapping,
    *,
    agents_dir: Path = AGENTS_DIR,
    env: Mapping[str, str] | None = None,
    which: callable | None = None,
    now: datetime | None = None,
) -> dict:
    if env is None:
        env = os.environ
    now = now or datetime.now(timezone.utc)
    rows: dict[str, dict] = {}
    canonical_issues: dict[str, dict] = {}
    for slug, mblock in (manifest.get("agents") or {}).items():
        docs = discover_agent_assets(slug, agents_dir=agents_dir)
        row = classify_agent(slug, mblock=mblock, docs=docs, env=env, which=which)
        rows[slug] = row
        if row["next_action"] is not None:
            issue_slug = row["next_action"]["slug"]
            entry = canonical_issues.setdefault(
                issue_slug,
                {
                    "blocked_agents": [],
                    "missing_envs": set(),
                    "missing_tools": set(),
                    "stale_plain_defaults": set(),
                },
            )
            entry["blocked_agents"].append(slug)
            entry["missing_envs"].update(row["missing_required_envs"])
            entry["missing_envs"].update(row["missing_optional_used_envs"])
            entry["missing_envs"].update(row["undeclared_doc_envs"])
            entry["missing_tools"].update(row["missing_hard_tools"])
            entry["missing_tools"].update(row["missing_soft_tools"])
            entry["stale_plain_defaults"].update(row["stale_plain_defaults"])
    # Freeze sets → sorted lists for stable JSON.
    for issue in canonical_issues.values():
        for key in ("missing_envs", "missing_tools", "stale_plain_defaults"):
            issue[key] = sorted(issue[key])
        issue["blocked_agents"] = sorted(issue["blocked_agents"])
    counts = {"ready": 0, "degraded": 0, "blocked": 0}
    for row in rows.values():
        counts[row["status"]] += 1
    return {
        "generated_at": now.isoformat(),
        "counts": counts,
        "agents": rows,
        "canonical_issues": canonical_issues,
    }


def render_human(report: Mapping) -> str:
    lines: list[str] = []
    counts = report["counts"]
    lines.append(
        "Paperclip runtime probe: "
        f"{counts['ready']} ready, {counts['degraded']} degraded, {counts['blocked']} blocked"
    )
    for slug in sorted(report["agents"].keys()):
        row = report["agents"][slug]
        lines.append(f"\n[{row['status']}] {slug}")
        if row["missing_required_envs"]:
            lines.append(f"  required envs missing: {row['missing_required_envs']}")
        if row["missing_hard_tools"]:
            lines.append(f"  required tools missing: {row['missing_hard_tools']}")
        if row["missing_optional_used_envs"]:
            lines.append(
                f"  optional envs used by prompt missing: {row['missing_optional_used_envs']}"
            )
        if row["missing_soft_tools"]:
            lines.append(f"  soft tools missing: {row['missing_soft_tools']}")
        if row["undeclared_doc_envs"]:
            lines.append(f"  prompt references undeclared envs: {row['undeclared_doc_envs']}")
        if row["stale_plain_defaults"]:
            lines.append(f"  stale plain defaults: {row['stale_plain_defaults']}")
        if row["next_action"]:
            lines.append(f"  next action: update {row['next_action']['slug']}")
    if report["canonical_issues"]:
        lines.append("\nCanonical maintenance issues to update:")
        for slug, issue in sorted(report["canonical_issues"].items()):
            lines.append(
                f"  {slug} → agents={issue['blocked_agents']} "
                f"envs={issue['missing_envs']} tools={issue['missing_tools']}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of human text")
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="path to .paperclip.yaml (default: agents/.paperclip.yaml)",
    )
    parser.add_argument(
        "--agents-dir",
        default=str(AGENTS_DIR),
        help="path to agents/ root (default: agents/)",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(Path(args.manifest))
    report = build_report(manifest, agents_dir=Path(args.agents_dir))
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_human(report) + "\n")
    return 1 if report["counts"]["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
