---
name: paperclip
description: >
  Use the FFmemes repo-local Paperclip CLI wrapper for task coordination,
  issue comments, status updates, and other Paperclip control-plane work.
---

# FFmemes Paperclip Skill

Use this skill only for Paperclip coordination: issue context, comments,
status updates, child issues, approvals, and runtime/task inspection. Do not
use it for the domain implementation itself.

## Entrypoint

Run Paperclip through the repo-local wrapper:

```bash
.codex/paperclip-tools/paperclipai-ffmemes.sh
```

Pass normal Paperclip CLI arguments after the wrapper. For manual local CLI
setup, use:

```bash
.codex/paperclip-tools/paperclipai-ffmemes.sh agent local-cli <agent-id-or-shortname> --company-id <company-id>
```

The wrapper keeps Paperclip access task-scoped for this repository and avoids
enabling the Paperclip MCP server globally.

It sources `.codex/paperclip-tools/paperclip.env` when present, normalizes
`PAPERCLIP_URL` to `PAPERCLIP_API_URL`, sets `PAPERCLIP_CONTEXT`, and defaults
`PAPERCLIP_COMPANY_ID` to the FFmemes company. Do not print `paperclip.env`.

Useful read-only commands:

```bash
.codex/paperclip-tools/paperclipai-ffmemes.sh --version
.codex/paperclip-tools/paperclipai-ffmemes.sh company list --json
.codex/paperclip-tools/paperclipai-ffmemes.sh dashboard get -C 96ee7b2e-6df2-43c8-bbe3-53e19297308a --json
.codex/paperclip-tools/paperclipai-ffmemes.sh issue list -C 96ee7b2e-6df2-43c8-bbe3-53e19297308a --status todo,in_progress,blocked,done --json
.codex/paperclip-tools/paperclipai-ffmemes.sh issue get FFM-1250 --json
```

## Heartbeat Rules

- Use `PAPERCLIP_WAKE_PAYLOAD_JSON` first when it is present.
- For scoped wakes, do not search for other assignments.
- If the harness already checked out the issue, do not call checkout again.
- Include `X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID` on all modifying API calls.
- End every heartbeat with a durable disposition: `done`, `in_review`,
  `blocked`, delegated child issues, or a real continuation path.

## Status Discipline

- Use `done` only when the requested work is complete and verified.
- Use `in_review` only when there is a real reviewer, approval, interaction,
  or monitor path.
- Use `blocked` only with a named owner/action, and prefer first-class
  `blockedByIssueIds` when another issue is the blocker.
- Create child issues for delegated follow-up work instead of leaving a comment
  as the only handoff.

## API Fallback

If the CLI is unavailable but heartbeat environment variables are present, use
the Paperclip HTTP API directly:

```bash
curl -fsS \
  -H "Authorization: Bearer $PAPERCLIP_API_KEY" \
  -H "X-Paperclip-Run-Id: $PAPERCLIP_RUN_ID" \
  "$PAPERCLIP_API_URL/api/issues/$PAPERCLIP_TASK_ID"
```

Never print secret values or commit local runtime credentials.
