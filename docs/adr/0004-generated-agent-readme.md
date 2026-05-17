# ADR-0004: Generated Agent README Is Not Authoritative

Status: Accepted

## Context

Agent catalogs can be exported into generated README snapshots. Those snapshots
are convenient for review, but they can lag the live Paperclip catalog and the
repo sync manifest.

## Decision

Treat generated agent README exports as reference snapshots only. The authority
for Paperclip agent configuration is:

- `agents/.paperclip.yaml` for runtime, env, and skill source/ref.
- `agents/<slug>/AGENTS.md` frontmatter for per-agent skill assignment.
- `docs/agents/README.md` for where humans and agents should start reading.

`CLAUDE.md` is legacy/reference guidance. Codex-facing guidance should live in
`AGENTS.md`, `docs/agents/**`, and linked specs.

## References

- [Paperclip skill catalog](../paperclip-skill-catalog.md)
- [Agent entrypoint map](../agents/README.md)
- [Paperclip-native migration](../paperclip-native-migration.md)
