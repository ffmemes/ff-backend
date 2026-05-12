# Paperclip Simplification Notes - 2026-05-04

Use this as the short handoff before editing Paperclip agent prompts or sync
code. It avoids rereading the full upstream repo and the long ops runbook.

## Sources

- Upstream docs: https://docs.paperclip.ing/
- Repo docs:
  - https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/task-workflow.md
  - https://github.com/paperclipai/paperclip/blob/master/docs/guides/agent-developer/heartbeat-protocol.md
  - https://github.com/paperclipai/paperclip/blob/master/docs/api/issues.md
  - https://github.com/paperclipai/paperclip/blob/master/docs/api/routines.md
  - https://github.com/paperclipai/paperclip/blob/master/packages/mcp-server/README.md
- Local implementation:
  - [`agents/.paperclip.yaml`](../../agents/.paperclip.yaml)
  - [`agents/deploy.sh`](../../agents/deploy.sh)
  - [`agents/_sync_config.py`](../../agents/_sync_config.py)
  - [`.github/workflows/staff-engineer-trigger.yml`](../../.github/workflows/staff-engineer-trigger.yml)
- Related local notes:
  - [`paperclip-native-migration.md`](../paperclip-native-migration.md)
  - [`update-routine-findings-2026-05-01.md`](update-routine-findings-2026-05-01.md)
  - [`routine-observability.md`](routine-observability.md)

## What Can Shrink

- Agent prompts should not duplicate Paperclip runtime behavior:
  `PAPERCLIP_TASK_ID` wake handling, inbox retry prose, manual tool lists, and
  ad-hoc blocked-state comments belong in the native Paperclip skill. Keep only
  local business rules in `agents/<slug>/AGENTS.md`.
- Use first-class `blockedByIssueIds`, child issues, and structured interaction
  cards instead of comment-only handoffs when the target Paperclip version
  supports them.
- Keep the local slug/dedupe discipline for now. Upstream tools reduce race
  handling and recovery code, but the issue API still does not provide a
  general idempotency key for "create one issue for this business object".
- On Paperclip v2026.512.0, use native company search before creating recurrent
  bracket-slug issues. This keeps our stable slug discipline while removing
  broad custom issue scans from prompts.
- Use native planning work mode for strategy, experiment, architecture, and
  proposal issues. Execution issues stay standard.
- Use issue monitors / retry-now for delayed verification, post-deploy waits,
  and "measure after N days" follow-ups instead of comment-only due dates.
- Let routine revision history carry routine-description restore/audit needs.
  The repo sync includes `baseRevisionId` when the server exposes it.

## Sync Code Guidance

- `company import --target existing --collision replace` is still not the
  deploy path: the safe import API rejects replace for existing companies.
  Keep the native-API sync path until Paperclip exposes a safe update/import
  route for existing agents.
- Simplify the sync path before adding features:
  - Prefer one Python sync script over shell plus Python so local runs do not
    depend on `jq`.
  - Current `_sync_config.py` already patches adapter type/config, Codex
    reasoning effort, heartbeat, permissions, and env refs from
    `agents/.paperclip.yaml`, and uses native
    `POST /api/agents/:id/skills/sync` for desired skills. It also syncs
    routine descriptions declared under `agents/<slug>/routines/*.yaml`.
  - Use `replaceAdapterConfig: true` when patching adapter config so stale
    adapter-specific keys are actually removed; Paperclip's default PATCH
    behavior merges `adapterConfig`.
  - Keep env sync fail-closed: if Paperclip secrets cannot be listed or a
    required secret is missing, abort before any agent config PATCH. Compare
    full sanitized env bindings, including plain values and secret names, not
    only env types.
  - Keep per-file instructions-bundle writes because they are audited and
    rollbackable.
- Do not add secrets, API keys, Paperclip secret IDs, trigger public IDs, or
  private internal hostnames to public docs. Env var names and Paperclip secret
  names are OK; never include values.
- Codex agents are subscription/OAuth-only. Do not add `OPENAI_API_KEY` to
  `codex_local` agent env or the Paperclip host env; Codex CLI 0.122+ treats it
  as API-key billing. Remaining Claude agents should be replaced with Codex
  rather than maintained as a second subscription runtime.
- Do not adopt AWS Secrets Manager provider vaults for this setup. Keep
  Paperclip company secrets for agent env bindings; use Coolify envs only for
  Paperclip service-level config.

## Keep Custom For Now

- The GitHub PR review workflow is still reasonable if it sends a narrow
  `{pr_number, pr_url}` payload through Paperclip's native routine API trigger.
  A direct GitHub webhook with `github_hmac` can remove the workflow later, but
  then the agent prompt must parse the full GitHub webhook payload.
- Comms publishing and routine outcome checks are product-specific. Paperclip
  can know a Telegram post is complete only when the agent records the concrete
  `result.message_id` and `result.editorial_post_id` returned by
  `publish_editorial_post(...)` on the `[post:...]` issue.
