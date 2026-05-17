# Architecture Decision Records

Lightweight records for agent architecture hardening decisions. Keep records
short, link the operational source of truth, and add a new entry when agent
runtime boundaries change.

| ADR | Status | Decision |
|-----|--------|----------|
| [ADR-0001](0001-local-paperclip-cli.md) | Accepted | Use the project-local Paperclip CLI skill instead of global Paperclip MCP. |
| [ADR-0002](0002-codex-oauth-agent-auth.md) | Accepted | Codex agents use OAuth/subscription auth only. |
| [ADR-0003](0003-prepared-source-etl-guard.md) | Accepted | Prepared sources must not enter ETL until `parsing_enabled`. |
| [ADR-0004](0004-generated-agent-readme.md) | Accepted | Generated agent README exports are reference snapshots, not authority. |
