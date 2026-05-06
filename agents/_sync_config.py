#!/usr/bin/env python3
"""Diff-first PATCH of agent adapterConfig + desiredSkills + heartbeat from manifest.

Called by `agents/deploy.sh` after the markdown PUT pass. Reads `.paperclip.yaml`
and per-agent `AGENTS.md` frontmatter, compares with prod via Paperclip API,
PATCHes only agents whose config actually drifted.

Env: PAPERCLIP_URL, PAPERCLIP_API_KEY, COMPANY_ID, SCRIPT_DIR, DRY_RUN.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

import yaml

URL = os.environ["PAPERCLIP_URL"]
KEY = os.environ["PAPERCLIP_API_KEY"]
COMPANY = os.environ["COMPANY_ID"]
SCRIPT_DIR = os.environ["SCRIPT_DIR"]
DRY = os.environ.get("DRY_RUN", "0") == "1"

# Skills published under paperclipai/paperclip/ are preserved when present; they
# do not need to appear in frontmatter.
PAPERCLIP_NS_SKILLS = {
    "paperclip",
    "paperclip-create-agent",
    "paperclip-create-plugin",
    "para-memory-files",
}


def api(method: str, path: str, body=None):
    req = urllib.request.Request(URL + path, method=method)
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Content-Type", "application/json")
    # Cloudflare in front of org.ffmemes.com blocks default Python-urllib UA (error 1010).
    req.add_header("User-Agent", "ffmemes-deploy.sh/1.0")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}", file=sys.stderr)
        raise


def fetch_secrets_by_name() -> dict[str, str]:
    """Return company secret name -> id when the deploy token can read secrets."""
    try:
        secrets = api("GET", f"/api/companies/{COMPANY}/secrets")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return {}
        raise
    if not isinstance(secrets, list):
        return {}
    return {
        item["name"]: item["id"]
        for item in secrets
        if isinstance(item, dict) and item.get("name") and item.get("id")
    }


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


def target_env_bindings(
    cur_env: dict | None,
    target_inputs: dict | None,
    secrets_by_name: dict[str, str],
) -> tuple[dict, list[str]]:
    """Build runtime adapterConfig.env bindings from portable manifest inputs."""
    target_env = ((target_inputs or {}).get("env")) or {}
    cur_env = cur_env or {}
    bindings = {}
    missing_required_secrets = []

    for key, spec in target_env.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("kind") == "plain":
            bindings[key] = {"type": "plain", "value": str(spec.get("default", ""))}
            continue

        current = cur_env.get(key)
        if isinstance(current, dict) and current.get("type") == "secret_ref":
            bindings[key] = current
            continue

        secret_id = secrets_by_name.get(key)
        if secret_id:
            bindings[key] = {
                "type": "secret_ref",
                "secretId": secret_id,
                "version": "latest",
            }
        elif spec.get("requirement") == "required":
            missing_required_secrets.append(key)

    return bindings, missing_required_secrets


def merged_adapter_env(cur_env: dict | None, target_bindings: dict) -> dict:
    """Merge manifest-managed env keys without removing runtime-only env keys."""
    return {**(cur_env or {}), **target_bindings}


def adapter_env_changes(cur_env: dict | None, target_bindings: dict) -> list[str]:
    """Return human-readable env binding drift without exposing secret values."""
    cur_env = cur_env or {}
    added = sorted(set(target_bindings) - set(cur_env))
    changed = sorted(
        k for k in set(target_bindings) & set(cur_env) if target_bindings[k] != cur_env[k]
    )

    changes = []
    if added:
        changes.append(f"+adapterConfig.env: {added}")
    if changed:
        changes.append(f"~adapterConfig.env: {changed}")
    return changes


def main() -> int:
    with open(f"{SCRIPT_DIR}/.paperclip.yaml") as f:
        manifest = yaml.safe_load(f)

    agents_list = api("GET", f"/api/companies/{COMPANY}/agents")
    by_slug = {a["urlKey"]: a for a in agents_list}
    secrets_by_name = fetch_secrets_by_name()

    patched = 0
    skipped = 0
    failed = 0
    would_patch = 0
    missing_required_secret_errors = 0
    for slug, mblock in (manifest.get("agents") or {}).items():
        if slug not in by_slug:
            print(f"  SKIP {slug} — not in prod")
            continue
        cur = by_slug[slug]

        # Targets from manifest
        ad_cfg = (mblock.get("adapter") or {}).get("config") or {}
        target_model = ad_cfg.get("model")
        target_max_turns = ad_cfg.get("maxTurnsPerRun")
        target_heartbeat = (mblock.get("runtime") or {}).get("heartbeat") or {}
        target_perms = mblock.get("permissions") or {}
        target_inputs = mblock.get("inputs") or {}

        # Frontmatter → desiredSkills (preserve any paperclipai/* currently attached)
        fm_skills = read_frontmatter_skills(f"{SCRIPT_DIR}/{slug}/AGENTS.md")
        cur_ac = cur.get("adapterConfig") or {}
        cur_skills = ((cur_ac.get("paperclipSkillSync") or {}).get("desiredSkills")) or []
        preserved = [s for s in cur_skills if s.startswith("paperclipai/")]
        target_skills = sorted(set(preserved + [skill_to_path(s) for s in fm_skills]))
        cur_skills_sorted = sorted(cur_skills)

        # Diff
        changes: list[str] = []
        if target_model and cur_ac.get("model") != target_model:
            changes.append(f"model: {cur_ac.get('model')} → {target_model}")
        if target_max_turns and cur_ac.get("maxTurnsPerRun") != target_max_turns:
            changes.append(f"maxTurnsPerRun: {cur_ac.get('maxTurnsPerRun')} → {target_max_turns}")
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

        cur_perms = cur.get("permissions") or {}
        perm_changes: list[tuple[str, object]] = []
        for k, v in target_perms.items():
            if cur_perms.get(k) != v:
                perm_changes.append((k, v))
                changes.append(f"permissions.{k}: {cur_perms.get(k)} → {v}")

        cur_env = cur_ac.get("env") or {}
        target_bindings, missing_required_secrets = target_env_bindings(
            cur_env,
            target_inputs,
            secrets_by_name,
        )
        if missing_required_secrets:
            changes.append(f"!missing required secrets: {missing_required_secrets}")
            missing_required_secret_errors += 1
        changes.extend(adapter_env_changes(cur_env, target_bindings))

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
        if target_model:
            new_ac["model"] = target_model
        if target_max_turns:
            new_ac["maxTurnsPerRun"] = target_max_turns
        if target_bindings:
            new_ac["env"] = merged_adapter_env(cur_env, target_bindings)
        new_skill_sync = dict(new_ac.get("paperclipSkillSync") or {})
        new_skill_sync["desiredSkills"] = target_skills
        new_ac["paperclipSkillSync"] = new_skill_sync

        new_rt = dict(cur_rt)
        new_hb = dict(cur_hb)
        new_hb.update(target_heartbeat)
        new_rt["heartbeat"] = new_hb

        # Permissions go through a separate endpoint (PATCH /api/agents/:id rejects them).
        body = {
            "adapterConfig": new_ac,
            "runtimeConfig": new_rt,
        }

        try:
            api("PATCH", f"/api/agents/{cur['id']}", body)
            print(f"  PATCHED {slug}: {'; '.join(changes)}")
            patched += 1
            if perm_changes:
                # Best-effort permissions update via dedicated endpoint.
                new_perms = dict(cur_perms)
                new_perms.update(target_perms)
                try:
                    api("PATCH", f"/api/agents/{cur['id']}/permissions", new_perms)
                    print(f"    + permissions updated: {dict(perm_changes)}")
                except Exception as pe:
                    print(f"    WARN permissions sync failed for {slug}: {pe}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR PATCH {slug}: {e}", file=sys.stderr)
            failed += 1

    if DRY:
        print(f"\nConfig sync (dry-run): would patch {would_patch}, skip {skipped} (no drift).")
    else:
        print(f"\nConfig sync: patched={patched}, skipped={skipped}, failed={failed}.")
    if missing_required_secret_errors:
        print(
            f"ERROR: {missing_required_secret_errors} agent(s) reference required secrets "
            "that are not visible to this deploy token.",
            file=sys.stderr,
        )
        return 1
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
