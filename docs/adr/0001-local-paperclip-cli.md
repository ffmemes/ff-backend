# ADR-0001: Local Paperclip CLI Instead Of Global MCP

Status: Accepted

## Context

Paperclip inspection is useful for agent operations, but enabling the Paperclip
MCP server globally adds a large always-on tool surface to every Codex session.

## Decision

Use the repo-local Paperclip skill and wrapper for Paperclip work:
`.codex/skills/paperclip/SKILL.md` and
`.codex/paperclip-tools/paperclipai-ffmemes.sh`.

Do not add Paperclip MCP to global Codex configuration for this repo. If MCP is
needed for a specific investigation, keep it local and task-scoped.

## References

- [AGENTS.md](../../AGENTS.md)
- [Agent entrypoint map](../agents/README.md)
- [Paperclip simplification notes (archive)](../archive/2026-q2/paperclip-simplification-2026-05-04.md)
