# ADR-0002: Codex OAuth Agent Auth

Status: Accepted

## Context

Paperclip can run Codex agents through the `codex_local` adapter. Codex CLI
0.122+ treats `OPENAI_API_KEY` as API-key billing, which is not the approved
runtime path for FFmemes agents.

## Decision

Codex is the primary agent surface. Codex agents must use persistent
OAuth/subscription auth from the Paperclip volume, not `OPENAI_API_KEY`.

Do not bind `OPENAI_API_KEY` to `codex_local` agents and do not set it in the
Paperclip host environment. Legacy Claude references are retained only as
historical or migration context.

## References

- [Paperclip-native migration](../paperclip-native-migration.md)
- [Paperclip operations runbook](../paperclip-ops-runbook.md)
- [Agent entrypoint map](../agents/README.md)
