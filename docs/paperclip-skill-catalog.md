# Paperclip Skill Catalog (Source Of Truth)

This file is `current operational`. It documents how Paperclip agents discover
GStack and Paperclip-native skills and how the catalog is kept in sync.

## Source of truth

| Surface | File | Notes |
|---------|------|-------|
| Upstream skill source + ref | `agents/.paperclip.yaml` (`skills.source`, `skills.ref`) | Ref is explicit. Bump only after a clean dry-run. |
| Per-agent skill assignment | `agents/<slug>/AGENTS.md` frontmatter `skills:` | Each entry resolves to either `garrytan/gstack/<slug>` (default) or `paperclipai/paperclip/<slug>` (for entries in `PAPERCLIP_NS_SKILLS`). |
| Adapter / env / runtime | `agents/.paperclip.yaml` (`agents.<slug>` block) | Sync via `agents/deploy.sh`. |
| Live ID/UUID indirection | `agents/_sync_config.py` | Resolves slug → agent ID by `urlKey` lookup. |

Do **not** treat `agents/README.md` as authoritative — it is a generated
snapshot and may lag the live Paperclip catalog. The banner at the top of
that file calls this out.

## Update method

GStack and Paperclip-native skills are attached per-agent via
`POST /api/agents/<id>/skills/sync` with the full desired list. This is the
`update_method: paperclip_skill_sync` recorded in `.paperclip.yaml`. The deploy
script runs a preflight before issuing any per-agent sync:

```text
Skill catalog preflight (dry-run):
  upstream_source: https://github.com/garrytan/gstack
  upstream_ref: <ref>
  checked: <N>
  updated: <added>
  removed: <gone>
  failed: <unknown desired skills>
  update_method: POST /api/agents/<id>/skills/sync (per-agent)
  catalog_validation: <ok|skipped (...)>
```

When `failed > 0`, the apply pass is blocked. `dry-run` still completes so the
operator sees the full diff and the unknown skill names.

## Team-mode (gstack) decision: docs-only

GStack supports a "team-mode" that lets multiple agents share the same skill
configuration via tracked files. **FFmemes does not vendor team-mode files
into this public repo.** Justification:

- `.claude/`, `.gstack/`, `.codex/`, `.agents/` are already covered by
  `.gitignore` (see lines `137`, `149`, plus the catch-all
  `# Per-developer git worktrees` block; we extend the rule by convention to
  any `.codex/skills/gstack` or `.agents/skills/gstack` paths if a tool
  introduces them).
- Each runtime (Claude Code, Codex, Paperclip) loads gstack from its own
  install. Paperclip pulls from `skills.source`/`skills.ref`; Claude Code and
  Codex install gstack into per-user dot-directories that are gitignored.
- Sharing a tracked team-mode file would mean either committing per-user
  paths (privacy leak) or pinning a config that is unlikely to be valid
  across all three runtimes.

**No tracked files are required for team-mode.** If a future use case demands
shared config, place it under a new directory and add it to `.gitignore`
before tracking anything else; the redaction audit
(`scripts/redaction_audit.py`) and the deploy preflight will keep the public
repo clean.

## When to bump `skills.ref`

1. Run `agents/deploy.sh --dry-run`. Confirm `failed: 0`.
2. If a desired skill is missing upstream, either add it to gstack (PR
   garrytan/gstack) or remove the frontmatter entry.
3. Bump `skills.ref` in `agents/.paperclip.yaml` and re-run dry-run. Apply
   only when the preflight is clean.
