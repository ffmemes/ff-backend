# Agent Entrypoint Map

Codex is the primary agent surface for this repo. `AGENTS.md` is the concise
Codex entrypoint; `CLAUDE.md` remains legacy/reference material and should not
override current Codex or Paperclip decisions.

## Where To Start

| Task type | Read first | Notes |
|-----------|------------|-------|
| General repo work | [AGENTS.md](../../AGENTS.md) | Current Codex operating notes and hard constraints. |
| Paperclip inspection or agent ops | [ADR-0001](../adr/0001-local-paperclip-cli.md) and `.codex/skills/paperclip/SKILL.md` | Use the project-local CLI skill/wrapper; do not enable global Paperclip MCP. |
| Local agent readiness check | [`scripts/agent_doctor.py`](../../scripts/agent_doctor.py) | Read-only checks for local commands, Describe Memes free-model contract, Paperclip wrapper, and agent-doc workflow invariants. |
| Paperclip runtime migration or auth | [Paperclip-native migration](../paperclip-native-migration.md) and [ADR-0002](../adr/0002-codex-oauth-agent-auth.md) | Codex agents are OAuth/subscription-only; no `OPENAI_API_KEY` binding. |
| Agent skill catalog or generated exports | [Paperclip skill catalog](../paperclip-skill-catalog.md) and [ADR-0004](../adr/0004-generated-agent-readme.md) | Generated README snapshots are reference only. |
| Routine health and outcomes | [Routine observability](routine-observability.md) and [Outcome ledger](outcome-ledger.md) | Prefer business outcome checks over generic liveness checks. |
| PR review automation | [PR review cycle](pr-review-cycle.md) | Keep GitHub payloads narrow and Paperclip issue links explicit. |
| Moderator source scouting | [Moderator community loop spec](../../specs/moderator-community-loop.md), [CONTEXT.md](../../CONTEXT.md), and [ADR-0003](../adr/0003-prepared-source-etl-guard.md) | Use the Russian domain vocabulary; prepared sources stay parked until enabled. |
| Describe Memes / vision OCR | [AGENTS.md](../../AGENTS.md) and [Describe Memes spec](../../specs/describe-memes.md) | Free OpenRouter vision models only. |

## Authority Boundaries

- `AGENTS.md`: current Codex-facing repo instructions.
- `docs/adr/**`: durable decisions for agent architecture hardening.
- `docs/agents/**`: short operational maps and focused handoffs.
- `agents/.paperclip.yaml`: live Paperclip sync manifest for runtime, env, and
  skill source/ref.
- `agents/<slug>/AGENTS.md`: per-agent prompt and skill assignment contract.
- `CLAUDE.md`: legacy/reference context. Use it only when newer Codex docs do
  not cover the task.
