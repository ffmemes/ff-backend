# Paperclip / gstack Update Findings — 2026-05-01

This is the compact handoff from the May 1 update routine audit. Use it as
input for the next Paperclip/gstack update check instead of re-reading every
release note from scratch.

## Sources Checked

- Paperclip stable npm line: `paperclipai` / `@paperclipai/mcp-server`
  latest stable `2026.428.0`; canary line `2026.430.0-canary.*` is not a prod
  target unless explicitly requested.
- Paperclip releases:
  - https://github.com/paperclipai/paperclip/releases/tag/v2026.427.0
  - https://github.com/paperclipai/paperclip/releases/tag/v2026.428.0
- gstack changelog: https://github.com/garrytan/gstack/blob/main/CHANGELOG.md
- Telegram plugin npm line: `paperclip-plugin-telegram` latest `0.6.0`.

## Paperclip Changes That Matter Here

- Structured issue-thread interactions: suggested tasks, question forms, and
  confirmation cards. Use these for approvals and one-way gates instead of
  ad-hoc comments when prod support is verified.
- First-class blockers and ordered sub-issues. Use `blockedByIssueIds` and
  checklist/subtask structure instead of free-text "blocked" states.
- Liveness/recovery improvements and active-run watchdog. `v2026.427.0`
  explicitly fixed stale execution-run locks, which maps directly to the
  `activeRun=null` zombie PR-review pattern observed here. After prod upgrade
  verification, remove prompt-side race/recovery prose that duplicates runtime
  behavior.
- Productivity review service. This is the right surface for "agents are busy
  but did anything useful happen?" It should open issues for no-comment streaks,
  long-active runs, and high-churn loops.
- Recovery fixes in `v2026.428.0`: stranded assigned todo issues, stale company
  skill refreshes, `maxConcurrentRuns:1`, manual routine visibility, and issue
  tree pause/resume.

## gstack Changes That Matter Here

- `1.20.0.0`: `/scrape` and `/skillify` browser-skill flow. Use `/scrape` for
  read-only changelog/dashboard extraction. Do not allow unattended `/skillify`
  in prod agents yet because it creates persistent browser skills after approval
  gates.
- `1.16.0.0`: paired-agent browser tunnel fixes plus browser operations such as
  `newtab`, `tabs`, `snapshot`, `fill`, and `closetab`. Relevant for remote or
  paired browser agents before blaming prompts for browser-control failures.
- `1.21.1.0`: stronger `/plan-ceo-review` smoke tests around Step 0. Good for
  planning quality; do not bypass plan-review gates with blanket "always accept"
  behavior except where the prompt explicitly says autonomous approval is safe.
- `1.17.0.0`: gbrain memory source/sync flow. Useful later, but it is local-Mac
  oriented and should not be wired into Paperclip cloud agents without an infra
  decision.

## Findings From Live Routine Outcomes

- `Daily Channel Post` Apr 30 created `FFM-842`, got CEO approval, then closed
  green without publishing. The actual public outcome requires
  `telegram_message_id` and `editorial_post_id`; approval alone is intermediate.
- `Daily Channel Post` May 1 published the meme highlight to the main RU meme
  channel (`https://t.me/fastfoodmemes/12590`). This is a valid target for fun
  findings like "most liked meme", but the outcome comment must name the actual
  channel. `@ffmemes` remains the target for build-in-public/product/process
  updates.
- `gstack Update Check` closed green while it had no canonical update path for
  runtime-delivered skills. Future runs must report `upstream_ref`,
  `checked_count`, `updated_count`, `failed_count`, `removed_count`, and
  `update_method`.
- `Paperclip Update Check` is currently SHA-only. It must include deployed
  version/ref, latest stable, changelog delta, and "impact on this agent system"
  before closing as useful.
- `@ffnerdbot` is only an activity feed. It is useful to see work starting and
  stopping, but not to judge value delivered.
- PR Review can currently misqueue work: PR #215 was coalesced into active
  `FFM-860 [pr:214] Review`, then both `FFM-860` and the re-triggered
  `FFM-862 [pr:215] Review` showed `in_progress` + running run +
  `activeRun=null` with no review comments. Treat this as Paperclip runtime
  zombie execution, not as a real review in progress.

## Repo Changes Made

- Added `scripts/paperclip_routine_audit.py` for compact routine outcome audits.
- Added `docs/agents/routine-observability.md` with outcome contracts.
- Updated CEO and Comms prompts so CEO approval returns `[post:...]` issues to
  Comms instead of closing them as done.
- Deployed updated agent instructions to live Paperclip on 2026-05-01.

## Next Safe Improvements

- Upgrade Paperclip to stable `2026.428.0` after confirming migrations and
  backing up prod. Then verify blocker scheduling, structured interactions, and
  productivity review on real issues before deleting prompt hotfixes.
- Keep canary `2026.430.0-canary.*` out of prod unless there is a specific bug
  fix that justifies canary risk.
- Add `/scrape` to agents that need read-only web extraction only after gstack
  skill import/update path is explicit and observable.
- Update Telegram plugin only if we want better routing/threading/digests. It
  will not solve value observability by itself.
