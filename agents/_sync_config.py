#!/usr/bin/env python3
"""Diff-first sync of agent config, native skills, and heartbeat from manifest.

Called by `agents/deploy.sh` after the markdown PUT pass. Reads `.paperclip.yaml`
and per-agent `AGENTS.md` frontmatter, compares with prod via Paperclip API,
PATCHes only agents whose config actually drifted, and uses Paperclip's native
skills sync endpoint for desired skill assignment.

Env: PAPERCLIP_URL, PAPERCLIP_API_KEY, COMPANY_ID, SCRIPT_DIR, DRY_RUN.
"""

import os
import re
import sys
import urllib.error
from pathlib import Path

import yaml

# scripts/ is a sibling of agents/; add it to sys.path so the shared
# Paperclip HTTP client can be imported when deploy.sh runs this file
# directly via `python3 agents/_sync_config.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from paperclip_http import PaperclipAPIError, PaperclipClient  # noqa: E402

URL = os.environ["PAPERCLIP_URL"]
KEY = os.environ["PAPERCLIP_API_KEY"]
COMPANY = os.environ["COMPANY_ID"]
SCRIPT_DIR = os.environ["SCRIPT_DIR"]
DRY = os.environ.get("DRY_RUN", "0") == "1"

_client = PaperclipClient(URL, KEY, user_agent="ffmemes-deploy.sh/1.0")


class ConfigError(Exception):
    pass


# Skills published under paperclipai/paperclip/ are preserved when present; they
# are not always listed in frontmatter.
PAPERCLIP_NS_SKILLS = {
    "paperclip",
    "paperclip-create-agent",
    "paperclip-create-plugin",
    "para-memory-files",
}


def api(method: str, path: str, body=None):
    """Adapter that preserves the legacy `urllib.error.HTTPError` contract.

    Tests and existing call-sites catch `urllib.error.HTTPError` and inspect
    `.code`; converting to `PaperclipAPIError` everywhere would force a
    cross-cutting change. Translate at the boundary instead.
    """
    try:
        return _client.request(method, path, body=body)
    except PaperclipAPIError as exc:
        if exc.kind == "http" and exc.code is not None:
            print(
                f"  HTTP {exc.code} on {method} {path}: {exc.body}",
                file=sys.stderr,
            )
            raise urllib.error.HTTPError(URL + path, exc.code, exc.body, {}, None) from exc
        raise


def sync_skills(agent_id: str, desired_skills: list[str]):
    return api(
        "POST",
        f"/api/agents/{agent_id}/skills/sync?companyId={COMPANY}",
        {"desiredSkills": desired_skills},
    )


def fetch_skill_catalog() -> tuple[set[str], str]:
    """Best-effort fetch of the company skill catalog.

    Returns (catalog_paths, status). `status` is a short label suitable for
    inclusion in the dry-run summary; `catalog_paths` is empty when the
    catalog couldn't be retrieved.
    """
    try:
        catalog = api("GET", f"/api/companies/{COMPANY}/skills")
    except urllib.error.HTTPError as e:
        return set(), f"skipped (HTTP {e.code})"
    except Exception as e:  # network / decode / other transport errors
        return set(), f"skipped ({type(e).__name__})"

    if not isinstance(catalog, list):
        return set(), f"skipped (unexpected shape {type(catalog).__name__})"

    paths: set[str] = set()
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        # Paperclip API surfaces vary across versions; accept either path-like
        # or composite owner/repo/slug forms.
        candidate = (
            entry.get("path") or entry.get("key") or entry.get("urlKey") or entry.get("slug")
        )
        if isinstance(candidate, str) and candidate:
            paths.add(candidate)
    return paths, f"ok ({len(paths)} skills)" if paths else "skipped (empty catalog)"


def compute_desired_skills(
    by_slug: dict[str, dict],
    manifest: dict,
) -> dict[str, tuple[list[str], list[str]]]:
    """Return per-agent (current_desired_skills, target_skills)."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    for slug in manifest.get("agents") or {}:
        if slug not in by_slug:
            continue
        cur = by_slug[slug]
        cur_ac = cur.get("adapterConfig") or {}
        cur_skills = ((cur_ac.get("paperclipSkillSync") or {}).get("desiredSkills")) or []
        preserved = [s for s in cur_skills if s.startswith("paperclipai/")]
        fm_skills = read_frontmatter_skills(f"{SCRIPT_DIR}/{slug}/AGENTS.md")
        target = sorted(set(preserved + [skill_to_path(s) for s in fm_skills]))
        out[slug] = (sorted(cur_skills), target)
    return out


def preflight_skills(
    by_slug: dict[str, dict],
    manifest: dict,
) -> dict:
    """Print a redacted skill-catalog preflight summary and return the state.

    Runs before the per-agent skill assignment sync. Surfaces:
    - upstream source/ref (from manifest, no secrets)
    - checked / updated / removed / failed counts across all in-prod agents
    - update_method
    - catalog validation status (best-effort; skipped when catalog endpoint
      is unavailable)
    - unknown desired skills (each is a Paperclip-namespaced path; never a
      secret)
    """
    skills_block = manifest.get("skills") or {}
    source = skills_block.get("source") or "unknown"
    ref = skills_block.get("ref") or "unpinned"
    update_method_label = (
        skills_block.get("update_method") or "POST /api/agents/<id>/skills/sync (per-agent)"
    )

    desired = compute_desired_skills(by_slug, manifest)
    all_desired: set[str] = set()
    updated_total = 0
    removed_total = 0
    for slug, (cur_skills, target_skills) in desired.items():
        added = set(target_skills) - set(cur_skills)
        gone = set(cur_skills) - set(target_skills)
        updated_total += len(added)
        removed_total += len(gone)
        all_desired.update(target_skills)

    catalog_paths, catalog_status = fetch_skill_catalog()
    unknown: list[str] = []
    if catalog_paths:
        for skill in sorted(all_desired):
            # paperclipai/* skills are preserved as-is from current adapterConfig;
            # if not in the live catalog, surface them too — that's exactly the
            # "unknown desired skill" case the verification asks about.
            if skill not in catalog_paths:
                unknown.append(skill)

    state = {
        "upstream_source": source,
        "upstream_ref": ref,
        "checked": len(all_desired),
        "updated": updated_total,
        "removed": removed_total,
        "failed": len(unknown),
        "update_method": update_method_label,
        "catalog_validation": catalog_status,
    }

    label = "Skill catalog preflight (dry-run)" if DRY else "Skill catalog state"
    print(f"\n{label}:")
    for k, v in state.items():
        print(f"  {k}: {v}")
    if unknown:
        print(f"  unknown_desired_skills: {unknown}")

    return {**state, "unknown_desired_skills": unknown}


def load_secret_ids() -> dict[str, str]:
    try:
        secrets = api("GET", f"/api/companies/{COMPANY}/secrets")
    except Exception as exc:
        raise ConfigError(f"could not list company secrets; refusing to sync env: {exc}") from exc
    return {s["name"]: s["id"] for s in secrets if s.get("name") and s.get("id")}


def skill_to_path(slug: str) -> str:
    if slug in PAPERCLIP_NS_SKILLS:
        return f"paperclipai/paperclip/{slug}"
    return f"garrytan/gstack/{slug}"


def read_frontmatter_skills(agents_md_path: str) -> list[str]:
    if not os.path.exists(agents_md_path):
        return []
    with open(agents_md_path) as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return []
    fm = yaml.safe_load(m.group(1)) or {}
    return list(fm.get("skills") or [])


def load_routine_description_specs() -> list[dict]:
    specs: list[dict] = []
    for slug in sorted(os.listdir(SCRIPT_DIR)):
        routines_dir = os.path.join(SCRIPT_DIR, slug, "routines")
        if not os.path.isdir(routines_dir):
            continue
        for filename in sorted(os.listdir(routines_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue
            routine_path = os.path.join(routines_dir, filename)
            with open(routine_path) as f:
                spec = yaml.safe_load(f) or {}
            description_file = spec.get("description_file")
            if not description_file:
                continue
            description_path = os.path.join(routines_dir, description_file)
            try:
                with open(description_path) as f:
                    description = f.read().rstrip() + "\n"
            except FileNotFoundError as exc:
                raise ConfigError(f"{routine_path}: missing {description_file}") from exc
            specs.append(
                {
                    "slug": slug,
                    "name": spec.get("name"),
                    "description": description,
                    "path": routine_path,
                }
            )
    return specs


def desired_env(mblock: dict, secret_ids: dict[str, str]) -> tuple[dict, list[str], list[str]]:
    target: dict[str, dict[str, str]] = {}
    warnings: list[str] = []
    errors: list[str] = []
    env_spec = ((mblock.get("inputs") or {}).get("env")) or {}
    for env_name, spec in env_spec.items():
        kind = spec.get("kind")
        if kind == "plain":
            if "default" not in spec:
                errors.append(f"{env_name}: plain env missing default")
                continue
            target[env_name] = {"type": "plain", "value": str(spec["default"])}
            continue

        if kind == "secret":
            secret_name = spec.get("secretName") or env_name
            secret_id = secret_ids.get(secret_name)
            if not secret_id:
                requirement = spec.get("requirement", "optional")
                message = f"{env_name}: missing Paperclip secret {secret_name}"
                if requirement == "required":
                    errors.append(message)
                else:
                    warnings.append(message)
                continue
            target[env_name] = {
                "type": "secret_ref",
                "secretId": secret_id,
                "version": "latest",
            }
            continue

        errors.append(f"{env_name}: unsupported env kind {kind!r}")
    return target, warnings, errors


def normalized_env(env: dict) -> dict:
    out = {}
    for name, value in sorted((env or {}).items()):
        if not isinstance(value, dict):
            out[name] = {"type": "invalid"}
            continue
        kind = value.get("type")
        if kind == "plain":
            out[name] = {"type": "plain", "value": str(value.get("value", ""))}
        elif kind == "secret_ref":
            out[name] = {
                "type": "secret_ref",
                "secretId": value.get("secretId"),
                "version": value.get("version", "latest"),
            }
        else:
            out[name] = {"type": kind or "unknown"}
    return out


def env_summary(env: dict, secret_names_by_id: dict[str, str]) -> dict[str, str]:
    summary = {}
    for name, value in normalized_env(env).items():
        kind = value.get("type")
        if kind == "plain":
            summary[name] = f"plain:{value.get('value', '')}"
        elif kind == "secret_ref":
            secret_name = secret_names_by_id.get(str(value.get("secretId")), "unknown-secret")
            summary[name] = f"secret_ref:{secret_name}@{value.get('version', 'latest')}"
        else:
            summary[name] = str(kind)
    return summary


def stale_adapter_keys(adapter_type: str | None) -> set[str]:
    if adapter_type == "codex_local":
        return {
            "dangerouslySkipPermissions",
            # Legacy/other-adapter UI keys. Codex uses modelReasoningEffort.
            "effort",
            "mode",
            "variant",
        }
    if adapter_type == "claude_local":
        return {
            "dangerouslyBypassApprovalsAndSandbox",
            "dangerouslyBypassSandbox",
            "modelReasoningEffort",
            "reasoningEffort",
            "search",
        }
    return set()


def routine_latest_revision_id(routine: dict) -> str | None:
    """Return the live routine revision id when the Paperclip API exposes one.

    v2026.512.0 introduced routine revision history. Older servers simply omit
    these fields, so callers can stay compatible by omitting baseRevisionId.
    """
    for key in ("latestRevisionId", "latest_revision_id", "currentRevisionId"):
        value = routine.get(key)
        if isinstance(value, str) and value:
            return value

    for key in ("latestRevision", "currentRevision", "revision"):
        value = routine.get(key)
        if isinstance(value, dict):
            revision_id = value.get("id")
            if isinstance(revision_id, str) and revision_id:
                return revision_id
    return None


def routine_patch_payload(routine: dict, description: str) -> dict:
    payload = {"description": description}
    revision_id = routine_latest_revision_id(routine)
    if revision_id:
        payload["baseRevisionId"] = revision_id
    return payload


def sync_routine_descriptions(by_slug: dict[str, dict]) -> tuple[int, int, int]:
    specs = load_routine_description_specs()
    if not specs:
        return 0, 0, 0

    routines = api("GET", f"/api/companies/{COMPANY}/routines")
    if not isinstance(routines, list):
        raise ConfigError("unexpected routines response")

    patched = 0
    skipped = 0
    failed = 0
    for spec in specs:
        agent = by_slug.get(spec["slug"])
        if not agent:
            print(f"  SKIP routine {spec['path']} — agent not in prod")
            continue
        matches = [
            routine
            for routine in routines
            if routine.get("title") == spec["name"]
            and routine.get("assigneeAgentId") == agent.get("id")
        ]
        if len(matches) != 1:
            print(
                f"  ERROR routine {spec['path']}: expected 1 live match, found {len(matches)}",
                file=sys.stderr,
            )
            failed += 1
            continue

        routine = matches[0]
        current = (routine.get("description") or "").rstrip()
        target = spec["description"].rstrip()
        if current == target:
            print(f"  skip routine {spec['name']} (no description drift)")
            skipped += 1
            continue
        payload = routine_patch_payload(routine, spec["description"])
        if DRY:
            change = "description"
            if "baseRevisionId" in payload:
                change += " with baseRevisionId"
            print(f"  WOULD PATCH routine {spec['name']}: {change}")
            patched += 1
            continue
        try:
            api(
                "PATCH",
                f"/api/routines/{routine['id']}",
                payload,
            )
        except Exception as e:
            print(
                f"  ERROR PATCH routine {spec['name']}: {e}",
                file=sys.stderr,
            )
            failed += 1
            continue
        print(f"  PATCHED routine {spec['name']}: description")
        patched += 1
    return patched, skipped, failed


def main() -> int:
    with open(f"{SCRIPT_DIR}/.paperclip.yaml") as f:
        manifest = yaml.safe_load(f)

    agents_list = api("GET", f"/api/companies/{COMPANY}/agents")
    if not isinstance(agents_list, list):
        print(
            f"  ERROR unexpected agents response shape {type(agents_list).__name__}",
            file=sys.stderr,
        )
        return 1
    by_slug = {a["urlKey"]: a for a in agents_list}
    try:
        secret_ids = load_secret_ids()
    except ConfigError as exc:
        print(f"  ERROR {exc}", file=sys.stderr)
        return 1
    secret_names_by_id = {secret_id: name for name, secret_id in secret_ids.items()}
    env_targets: dict[str, dict] = {}
    env_failed = False
    for slug, mblock in (manifest.get("agents") or {}).items():
        if slug not in by_slug:
            continue
        target_env, env_warnings, env_errors = desired_env(mblock, secret_ids)
        env_targets[slug] = target_env
        for warning in env_warnings:
            print(f"  WARN {slug} env {warning}", file=sys.stderr)
        for error in env_errors:
            print(f"  ERROR {slug} env {error}", file=sys.stderr)
            env_failed = True
    if env_failed:
        print("  ERROR env preflight failed; no agent config changes applied", file=sys.stderr)
        return 1

    preflight = preflight_skills(by_slug, manifest)
    if preflight["unknown_desired_skills"]:
        print(
            f"  ERROR {preflight['failed']} desired skill(s) not in Paperclip catalog: "
            f"{preflight['unknown_desired_skills']}",
            file=sys.stderr,
        )
        # Block apply; surface in dry-run as a failure marker but keep going so
        # operators see the full diff.
        if not DRY:
            return 1

    patched = 0
    skipped = 0
    failed = 0
    would_patch = 0
    for slug, mblock in (manifest.get("agents") or {}).items():
        if slug not in by_slug:
            print(f"  SKIP {slug} — not in prod")
            continue
        cur = by_slug[slug]

        # Targets from manifest
        target_adapter_type = (mblock.get("adapter") or {}).get("type")
        ad_cfg = (mblock.get("adapter") or {}).get("config") or {}
        target_heartbeat = (mblock.get("runtime") or {}).get("heartbeat") or {}
        target_perms = mblock.get("permissions") or {}
        target_env = env_targets[slug]

        # Frontmatter → desiredSkills (preserve any paperclipai/* currently attached)
        fm_skills = read_frontmatter_skills(f"{SCRIPT_DIR}/{slug}/AGENTS.md")
        cur_ac = cur.get("adapterConfig") or {}
        cur_skills = ((cur_ac.get("paperclipSkillSync") or {}).get("desiredSkills")) or []
        preserved = [s for s in cur_skills if s.startswith("paperclipai/")]
        target_skills = sorted(set(preserved + [skill_to_path(s) for s in fm_skills]))
        cur_skills_sorted = sorted(cur_skills)

        # Diff
        changes: list[str] = []
        if target_adapter_type and cur.get("adapterType") != target_adapter_type:
            changes.append(f"adapterType: {cur.get('adapterType')} → {target_adapter_type}")
        for key, target_value in ad_cfg.items():
            if cur_ac.get(key) != target_value:
                changes.append(f"{key}: {cur_ac.get(key)} → {target_value}")
        for key in sorted(stale_adapter_keys(target_adapter_type)):
            if key in cur_ac:
                changes.append(f"-adapterConfig.{key}")
        if target_skills != cur_skills_sorted:
            added = sorted(set(target_skills) - set(cur_skills_sorted))
            removed = sorted(set(cur_skills_sorted) - set(target_skills))
            if added:
                changes.append(f"+skills: {added}")
            if removed:
                changes.append(f"-skills: {removed}")

        cur_rt = cur.get("runtimeConfig") or {}
        cur_hb = cur_rt.get("heartbeat") or {}
        for k, v in target_heartbeat.items():
            if cur_hb.get(k) != v:
                changes.append(f"heartbeat.{k}: {cur_hb.get(k)} → {v}")

        cur_env = cur_ac.get("env") or {}
        if normalized_env(cur_env) != normalized_env(target_env):
            changes.append(
                f"env: {env_summary(cur_env, secret_names_by_id)} → "
                f"{env_summary(target_env, secret_names_by_id)}"
            )

        cur_perms = cur.get("permissions") or {}
        perm_changes: list[tuple[str, object]] = []
        for k, v in target_perms.items():
            if cur_perms.get(k) != v:
                perm_changes.append((k, v))
                changes.append(f"permissions.{k}: {cur_perms.get(k)} → {v}")

        config_changes = [
            change
            for change in changes
            if not change.startswith(("+skills:", "-skills:", "permissions."))
        ]
        skills_changed = target_skills != cur_skills_sorted

        if not changes:
            print(f"  skip {slug} (no config drift)")
            skipped += 1
            continue

        if DRY:
            print(f"  WOULD PATCH {slug}: {'; '.join(changes)}")
            would_patch += 1
            continue

        # Build merged payload — preserve everything else (instructionsFilePath, env, etc.)
        new_ac = dict(cur_ac)
        new_ac.update(ad_cfg)
        new_ac["env"] = target_env
        for key in stale_adapter_keys(target_adapter_type):
            new_ac.pop(key, None)

        new_rt = dict(cur_rt)
        new_hb = dict(cur_hb)
        new_hb.update(target_heartbeat)
        new_rt["heartbeat"] = new_hb

        # Permissions go through a separate endpoint (PATCH /api/agents/:id rejects them).
        try:
            if config_changes:
                body = {
                    "adapterConfig": new_ac,
                    "runtimeConfig": new_rt,
                    "replaceAdapterConfig": True,
                }
                if target_adapter_type:
                    body["adapterType"] = target_adapter_type
                api("PATCH", f"/api/agents/{cur['id']}", body)
                print(f"  PATCHED {slug}: {'; '.join(config_changes)}")
                patched += 1
            if skills_changed:
                snapshot = sync_skills(cur["id"], target_skills)
                warnings = snapshot.get("warnings") or []
                suffix = f"; warnings={warnings}" if warnings else ""
                print(f"  SYNCED SKILLS {slug}: desired={target_skills}{suffix}")
                patched += 1
            if perm_changes:
                # Best-effort permissions update via dedicated endpoint.
                new_perms = dict(cur_perms)
                new_perms.update(target_perms)
                try:
                    api("PATCH", f"/api/agents/{cur['id']}/permissions", new_perms)
                    print(f"    + permissions updated: {dict(perm_changes)}")
                    patched += 1
                except Exception as pe:
                    print(f"    WARN permissions sync failed for {slug}: {pe}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR PATCH {slug}: {e}", file=sys.stderr)
            failed += 1

    print("\nSyncing routine descriptions...")
    try:
        routine_patched, routine_skipped, routine_failed = sync_routine_descriptions(by_slug)
    except (ConfigError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"  ERROR routine sync aborted: {exc}", file=sys.stderr)
        routine_patched = 0
        routine_skipped = 0
        routine_failed = 1

    if DRY:
        print(f"\nConfig sync (dry-run): would patch {would_patch}, skip {skipped} (no drift).")
        print(
            f"Routine sync (dry-run): would patch {routine_patched}, "
            f"skip {routine_skipped}, failed={routine_failed}."
        )
    else:
        print(f"\nConfig sync: patched={patched}, skipped={skipped}, failed={failed}.")
        print(
            f"Routine sync: patched={routine_patched}, "
            f"skipped={routine_skipped}, failed={routine_failed}."
        )
    failed += routine_failed
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
