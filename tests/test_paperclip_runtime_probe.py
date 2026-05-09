"""Unit tests for the per-agent runtime probe.

The probe is pure (no Paperclip API, no real PATH lookup) so we exercise
it with synthetic manifests, an in-memory `agents/` tree, an injected
`env` dict, and a stub `which`. The CLI path is exercised separately
through `build_report` so we never touch process state.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from paperclip_runtime_probe import (  # noqa: E402
    build_report,
    classify_agent,
    extract_env_references,
    extract_tool_references,
    load_manifest,
    maintenance_slug,
    manifest_env_requirements,
    render_human,
)


def _which_factory(present: set[str]):
    def which(tool: str) -> str | None:
        return f"/usr/bin/{tool}" if tool in present else None

    return which


def _mblock(*, required: dict | None = None, optional: dict | None = None) -> dict:
    env: dict = {}
    for name, default in (required or {}).items():
        env[name] = {"kind": "secret", "requirement": "required"}
        if default is not None:
            env[name] = {"kind": "plain", "default": default, "requirement": "required"}
    for name, default in (optional or {}).items():
        if default is None:
            env[name] = {"kind": "secret", "requirement": "optional"}
        else:
            env[name] = {"kind": "plain", "default": default, "requirement": "optional"}
    return {"inputs": {"env": env}}


def test_extract_env_references_filters_shell_noise():
    text = "psql $ANALYST_DATABASE_URL\necho $PATH\nuse ${SENTRY_AUTH_TOKEN}"
    assert extract_env_references(text) == {"ANALYST_DATABASE_URL", "SENTRY_AUTH_TOKEN"}


def test_extract_env_references_ignores_lowercase_and_short():
    assert extract_env_references("$x $ab cat $FOO") == {"FOO"}


def test_extract_env_references_ignores_locally_assigned_shell_vars():
    """Shell snippets that build a local var (`FOO=$(...)`) and reference
    it later (`$FOO`) must not surface as missing envs."""
    text = (
        "META=$(gh pr view 123 --json author)\n"
        'AUTHOR=$(echo "$META" | jq -r .author.login)\n'
        "echo $AUTHOR\n"
        "psql $ANALYST_DATABASE_URL\n"
    )
    assert extract_env_references(text) == {"ANALYST_DATABASE_URL"}


def test_extract_tool_references_picks_known_only():
    text = "$ psql $URL\nrun gh pr list | jq .\n# sentry issue list\n"
    assert {"psql", "gh", "jq", "sentry"}.issubset(extract_tool_references(text))


def test_manifest_env_requirements_flags_uuid_default():
    block = _mblock(
        required={"COOLIFY_BASE_URL": None},
        optional={
            "COOLIFY_CONTAINER_NAME": "k4w804sco4s8kc88kwcw0ow4-131756368009",
            "SENTRY_ORG": "ffmemes",
        },
    )
    required, optional, stale = manifest_env_requirements(block)
    assert required == {"COOLIFY_BASE_URL"}
    assert optional == {"COOLIFY_CONTAINER_NAME", "SENTRY_ORG"}
    # `ffmemes` is short / not UUID-shaped → not stale.
    # The UUID-suffixed container name → stale.
    assert stale == ["COOLIFY_CONTAINER_NAME"]


def test_classify_agent_ready_when_everything_present():
    block = _mblock(required={"FOO": None})
    row = classify_agent(
        "alpha",
        mblock=block,
        docs="psql $FOO\n",
        env={"FOO": "x"},
        which=_which_factory({"psql"}),
    )
    assert row["status"] == "ready"
    assert row["next_action"] is None


def test_classify_agent_blocked_on_missing_required_env():
    block = _mblock(required={"ANALYST_DATABASE_URL": None})
    row = classify_agent(
        "qa-engineer",
        mblock=block,
        docs="psql $ANALYST_DATABASE_URL\n",
        env={},
        which=_which_factory({"psql"}),
    )
    assert row["status"] == "blocked"
    assert row["missing_required_envs"] == ["ANALYST_DATABASE_URL"]
    assert row["next_action"]["slug"] == "[maintenance:access-qa-engineer]"
    assert "ANALYST_DATABASE_URL" in row["next_action"]["title"]


def test_classify_agent_blocked_on_missing_hard_tool():
    block = _mblock(required={"FOO": None})
    row = classify_agent(
        "qa-engineer",
        mblock=block,
        docs="run psql $FOO and gh pr list\n",
        env={"FOO": "x"},
        which=_which_factory({"gh"}),  # psql missing
    )
    assert row["status"] == "blocked"
    assert row["missing_hard_tools"] == ["psql"]


def test_classify_agent_degraded_on_optional_env_used_by_prompt():
    block = _mblock(
        required={"FOO": None},
        optional={"OPENAI_API_KEY": None},
    )
    row = classify_agent(
        "cto",
        mblock=block,
        docs="set $OPENAI_API_KEY before running codex\n",
        env={"FOO": "x"},
        which=_which_factory({"codex"}),
    )
    assert row["status"] == "degraded"
    assert row["missing_optional_used_envs"] == ["OPENAI_API_KEY"]


def test_classify_agent_optional_env_not_referenced_does_not_degrade():
    block = _mblock(
        required={"FOO": None},
        optional={"NEVER_USED": None},
    )
    row = classify_agent(
        "alpha",
        mblock=block,
        docs="just runs $FOO\n",
        env={"FOO": "x"},
        which=_which_factory(set()),
    )
    assert row["status"] == "ready"


def test_classify_agent_undeclared_prompt_env_degrades():
    block = _mblock(required={"FOO": None})
    row = classify_agent(
        "alpha",
        mblock=block,
        docs="export $TOTALLY_UNDECLARED_TOKEN\n",
        env={"FOO": "x"},
        which=_which_factory(set()),
    )
    assert row["status"] == "degraded"
    assert "TOTALLY_UNDECLARED_TOKEN" in row["undeclared_doc_envs"]


def test_classify_agent_redacts_only_names():
    """Probe output must never echo the env value, only the name."""
    block = _mblock(required={"SECRET_TOKEN": None})
    row = classify_agent(
        "alpha",
        mblock=block,
        docs="use $SECRET_TOKEN\n",
        env={"SECRET_TOKEN": "actual-secret-do-not-leak"},
        which=_which_factory(set()),
    )
    blob = json.dumps(row)
    assert "actual-secret-do-not-leak" not in blob
    assert "SECRET_TOKEN" in blob  # the name is fine


def test_maintenance_slug_is_per_agent_canonical():
    assert maintenance_slug("qa-engineer") == "[maintenance:access-qa-engineer]"
    assert maintenance_slug("cto") == "[maintenance:access-cto]"


def test_build_report_aggregates_canonical_issues(tmp_path):
    # Build a minimal agents tree with two agents that both miss FOO.
    agents = tmp_path / "agents"
    for slug in ("alpha", "beta"):
        (agents / slug).mkdir(parents=True)
        (agents / slug / "AGENTS.md").write_text(f"# {slug}\nuse $FOO\n", encoding="utf-8")
    manifest = {
        "agents": {
            "alpha": _mblock(required={"FOO": None}),
            "beta": _mblock(required={"FOO": None}),
        }
    }
    report = build_report(
        manifest,
        agents_dir=agents,
        env={},
        which=_which_factory(set()),
    )
    assert report["counts"] == {"ready": 0, "degraded": 0, "blocked": 2}
    # One canonical issue per agent (idempotent slug, deduped per-agent).
    assert sorted(report["canonical_issues"].keys()) == [
        "[maintenance:access-alpha]",
        "[maintenance:access-beta]",
    ]
    # Each issue lists exactly one blocked agent and the missing env once.
    assert report["canonical_issues"]["[maintenance:access-alpha]"]["blocked_agents"] == ["alpha"]
    assert report["canonical_issues"]["[maintenance:access-alpha]"]["missing_envs"] == ["FOO"]


def test_build_report_is_idempotent(tmp_path):
    agents = tmp_path / "agents"
    (agents / "alpha").mkdir(parents=True)
    (agents / "alpha" / "AGENTS.md").write_text("$FOO", encoding="utf-8")
    manifest = {"agents": {"alpha": _mblock(required={"FOO": None})}}
    a = build_report(manifest, agents_dir=agents, env={}, which=_which_factory(set()))
    b = build_report(manifest, agents_dir=agents, env={}, which=_which_factory(set()))
    # JSON-stable except for `generated_at`.
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b


def test_render_human_redacts_values_and_lists_canonical_issues(tmp_path):
    agents = tmp_path / "agents"
    (agents / "qa-engineer").mkdir(parents=True)
    (agents / "qa-engineer" / "AGENTS.md").write_text(
        "psql $ANALYST_DATABASE_URL\n", encoding="utf-8"
    )
    manifest = {
        "agents": {
            "qa-engineer": _mblock(required={"ANALYST_DATABASE_URL": None}),
        }
    }
    report = build_report(manifest, agents_dir=agents, env={}, which=_which_factory({"psql"}))
    text = render_human(report)
    assert "[blocked] qa-engineer" in text
    assert "ANALYST_DATABASE_URL" in text
    assert "[maintenance:access-qa-engineer]" in text


def test_load_manifest_reads_real_paperclip_yaml():
    """The probe must be runnable against the real manifest in the repo."""
    manifest = load_manifest()
    assert "agents" in manifest
    # Sanity: the prod agents we expect are all present.
    expected = {
        "analyst",
        "ceo",
        "comms-manager",
        "cto",
        "qa-engineer",
        "release-engineer",
        "staff-engineer",
    }
    assert expected.issubset(set(manifest["agents"].keys()))


def test_real_manifest_does_not_carry_uuid_plain_defaults():
    """Stale plain defaults like the Coolify resource UUID and container
    name must not live as `default:` in the manifest. They're stale agent
    runtime config that should resolve dynamically or via a secret.
    """
    manifest = load_manifest()
    qa = manifest["agents"]["qa-engineer"]
    _, _, stale = manifest_env_requirements(qa)
    assert stale == [], f"stale plain defaults still in manifest: {stale}"


def test_build_report_against_real_repo_runs_without_error():
    """Smoke test: probe builds a report against the live agents/ tree
    even when nothing is in the env. Status must be machine-readable
    (every agent has a known status string)."""
    manifest = load_manifest()
    report = build_report(manifest, env={}, which=_which_factory(set()))
    for slug, row in report["agents"].items():
        assert row["status"] in {"ready", "degraded", "blocked"}, slug
