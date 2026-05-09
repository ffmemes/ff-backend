---
status: DRAFT
---
# Ralphex Plan: Paperclip Agent Architecture Repair

Repo: ffmemes/ff-backend
Scope: FFmemes Paperclip setup, prompts, tools, routines, logs, and agent
operating contracts. This plan does not modify upstream Paperclip code.

## Goal

Run a long, audit-first repair loop that makes the Paperclip agent organization
move without avoidable stalls:

- agents start with the right next step instead of rediscovering context;
- missing access, tools, and env vars become explicit maintenance issues;
- stale local specs stop overriding current Paperclip/GStack behavior;
- routine and issue logs expose stuck states, loops, and fake-green outcomes;
- each fix is verified by re-triggering the relevant flow or by a dry-run gate.

The key rule: Ralphex must prove a problem from live logs, local docs, or a
dry-run mismatch before changing prompts or configuration.

## Hard Constraints

- Do not commit secrets, DB URLs, raw auth headers, trigger URLs, trigger public
  IDs, Paperclip API keys, SSH keys, session strings, or full webhook URLs.
- Do not edit upstream Paperclip source.
- Do not change ff-backend product behavior under `src/` unless a later
  explicitly approved task scopes that product change.
- Do not run `agents/deploy.sh` without `--dry-run` until the dry-run diff is
  reviewed and the task explicitly says apply is safe.
- Do not auto-close strategic, product, experiment, or ambiguous issues.
- Do not use SSH as the default agent path. SSH/Coolify/manual DB writes are
  human/MacBook operations; Paperclip agents should use Paperclip MCP/API or
  repo helper scripts, and report missing access by env var name.
- Do not ask agents to recover secrets by searching the machine or logs.
- Do not start uncontrolled recurring loops. Trigger one flow, wait a bounded
  window, audit, then continue.
- Keep raw audit snapshots in `.ralphex/paperclip-architecture/`; commit only
  redacted summaries or source code/tests.

## Evidence Classes To Collect First

Ralphex must classify every suspected problem into one of these classes before
repairing it:

- `stopped`: issue/run is blocked, idle, or waiting without a concrete owner,
  missing access, or next action.
- `looping`: agent repeatedly creates duplicate issues, retries the same action,
  reopens/recovers without new evidence, or alternates states.
- `fake_green`: parent/routine says done or healthy while child issues, approvals,
  posts, reviews, or smoke checks are still non-terminal.
- `missing_access`: prompt expects a tool, env var, secret, GitHub permission,
  Paperclip capability, DB role, or Telegram permission that runtime lacks.
- `stale_instruction`: markdown/spec/prompt points to old GStack/Paperclip
  behavior, stale containers, deprecated skills, raw trigger paths, or old
  operational assumptions.
- `outcome_gap`: work completed but no decision/outcome/result artifact is
  recorded in the place audits read.
- `prompt_workflow`: prompt contains executable multi-step shell/API procedures
  that should be a tested script, skill, or Paperclip native capability.

## Known Seed Findings To Verify

These are not automatically trusted. Ralphex must verify each one from the
current file/live state before changing it.

- Runbook current-state drift: `docs/paperclip-ops-runbook.md` still presents an
  older Paperclip version/fork model while `docs/paperclip-native-migration.md`
  describes the newer pinned production state.
- Public trigger leakage: docs contain concrete routine trigger URLs/public IDs
  while the same runbook says the repo must not expose them.
- Historical April PoC docs still look operational and include dangerous setup
  commands such as onboarding against an existing install.
- Agent-vs-human access is muddled: docs say SSH is human-only, but nearby
  checklists still lead agents toward SSH/docker recovery paths.
- PR review recovery docs normalize direct trigger firing instead of diagnosing
  the Paperclip routine, GitHub workflow payload, and issue state.
- CTO commit instructions blur human identity and agent accountability.
- Comms instructions ban raw Telegram posting but still include raw Bot API
  snippets that can teach agents to chase production bot tokens.
- GStack/Claude routing docs hardcode skills and mechanics that differ across
  Codex, Claude Code, Paperclip, and current upstream GStack.
- `agents/README.md` is an old generated export that can be mistaken for live
  source of truth.
- Example DB recovery snippets normalize pasting secret-bearing DB URLs into
  public docs.

## Audit Sequence

Keep checkbox status accurate. Do not mark a repair complete until its own
verification has run.

### Task 0: Source-Of-Truth Triage

- [ ] Classify local docs into `current operational`, `agent prompt`,
      `generated snapshot`, `historical research`, `human break-glass`, and
      `deprecated`.
- [ ] Add or update a local-only triage note that tells Ralphex which files may
      drive operations and which files are only historical context.
- [ ] Mark seed findings above as `verified`, `not reproducible`, or
      `needs live-log proof`.
- [ ] Prefer Paperclip MCP for live inspection if available; if Paperclip MCP is
      still being installed, use existing redacted API scripts and record
      `missing Paperclip MCP` as a capability gap, not as a blocker for the
      whole audit.

Verification:

- [ ] No live mutation happens in this task.
- [ ] Current operational docs are identified before Ralphex follows any
      operational command from docs.
- [ ] Historical docs that contain dangerous commands are not used as current
      setup instructions.

### Task 1: Snapshot Live Paperclip And Local State

- [ ] Create local-only directory `.ralphex/paperclip-architecture/`.
- [ ] Save redacted `git status`, current branch, and Ralphex version.
- [ ] Save redacted GStack local version, upstream version/ref, and skill list
      diff.
- [ ] Save `agents/deploy.sh --dry-run` output with secrets and IDs redacted.
- [ ] Save `scripts/paperclip_routine_audit.py --focus all --json` output.
- [ ] Save `scripts/paperclip_outcome_audit.py --days 14 --json` output.
- [ ] Fetch open/recent Paperclip issues, issue comments, routine runs,
      execution transcripts, wakeups, blockers, and available run logs through
      Paperclip MCP/API; redact before persisting.
- [ ] Produce `paperclip-baseline-summary.md` with counts by evidence class.

Verification:

- [ ] `paperclip-baseline-summary.md` cites only redacted IDs/slugs and env var
      names.
- [ ] Raw local snapshots are untracked.
- [ ] No task proceeds to config changes before this summary exists.

### Task 2: Parallel Stuck/Loop Audit

Run these audits in parallel when subagents are available. If Ralphex cannot
spawn agents, run the same tracks sequentially.

- [ ] Track A, live execution logs: identify runs/issues that stopped, looped,
      or produced fake-green results. For each, record last concrete action,
      expected next action, observed blocker, and proof.
- [ ] Track B, local markdown/specs: identify stale or harmful instructions in
      `CLAUDE.md`, `agents/**`, `docs/**`, and `specs/**` that send agents to
      old tools, wrong access paths, deprecated GStack skills, raw trigger URLs,
      stale container names, or historical Paperclip behavior.
- [ ] Track C, tool/env/access matrix: compare prompts and routines against
      manifest/env/tool availability for `gh`, `jq`, `psql`, `sentry`, `codex`,
      Paperclip MCP/API, editorial publishing, GitHub PR review, Telegram, DB,
      Prefect, Redis, and GStack.
- [ ] Track D, architecture/deepening: run the local
      `improve-codebase-architecture` skill against Paperclip helper scripts and
      audits, then rank the modules that would reduce repeated agent work.
- [ ] Merge findings into `paperclip-problem-ledger.md` with fields:
      `class`, `proof`, `affected_agent`, `source_file_or_issue`, `root_cause`,
      `safe_fix`, `verification`, `risk`, `auto_fix_allowed`.

Verification:

- [ ] Every high-priority ledger row has direct proof from a live log, API
      response, audit script, dry-run mismatch, or file reference.
- [ ] Ledger separates proven blockers from guesses.
- [ ] Ledger marks which fixes can run automatically and which need human/CEO
      approval.

## Repair Phases

### Task 3: Public Repo Redaction And Stale Spec Guard

- [ ] Add or update a redaction audit that fails on trigger public paths,
      trigger IDs, raw bearer headers, DB URLs, API keys, session strings, and
      secret values in tracked docs/config.
- [ ] Replace any tracked full trigger URL or operational secret material with
      a lookup path and env var/secret name.
- [ ] Split "current Paperclip state" from historical incident notes so docs do
      not preserve stale versions as live truth.
- [ ] Add a short docs rule: public repo may contain env var names and redacted
      issue slugs, not secret values or full live trigger material.

Verification:

- [ ] Redaction audit passes.
- [ ] `rg` finds no tracked `routine-triggers/public`, raw bearer header,
      full DB URL, or session string.
- [ ] `git diff --check` passes.

### Task 4: GStack And Paperclip Capability Source Of Truth

- [ ] Record local GStack version and upstream ref in a generated, redacted
      state file or audit output, not hand-written prose.
- [ ] Decide whether team-mode configuration is docs-only or required; if
      required, make sure tracked files are compatible with `.gitignore`.
- [ ] Pin or explicitly record the GStack source/ref expected by Paperclip
      company skills instead of relying on an unqualified GitHub URL.
- [ ] Add an import/update dry-run step for Paperclip company skills before
      per-agent skill assignment sync.
- [ ] Update `CLAUDE.md`, `agents/README.md`, and agent docs only after the
      current skill catalog is known.

Verification:

- [ ] Dry-run output includes upstream ref, checked count, updated count,
      failed count, removed count, and update method.
- [ ] No vendored `.claude/skills/gstack`, `.codex/skills/gstack`, or
      `.agents/skills/gstack` is accidentally tracked.
- [ ] `agents/deploy.sh --dry-run` reports no unknown desired skills.

### Task 5: Paperclip HTTP And Audit Modules

- [ ] Extract a shared Paperclip HTTP client module for URL handling, auth,
      JSON, pagination, timeout, redaction, and error reporting.
- [ ] Update `agents/_sync_config.py`, `scripts/paperclip_routine_audit.py`,
      and `scripts/paperclip_outcome_audit.py` to use the shared module.
- [ ] Add fixture tests for auth redaction, pagination, API errors, and dry-run
      behavior without live Paperclip.
- [ ] Add a new execution-log audit if no current script can classify stopped,
      looping, fake-green, missing-access, stale-instruction, and outcome-gap
      cases.

Verification:

- [ ] Unit tests pass without network access.
- [ ] Existing routine/outcome audit commands still run.
- [ ] Execution-log audit produces a stable JSON ledger with evidence classes.

### Task 6: Issue, Routine, And Outcome Contracts

- [ ] Centralize issue slug parsing and allowed issue classes.
- [ ] Centralize outcome event names and counting rules. Fix known drift such
      as `daily_post` vs `daily_channel_post`/`post_published`.
- [ ] Centralize routine outcome contracts so prompts and audit scripts share
      the same definitions.
- [ ] Make nested states visible at the parent/routine level:
      `pending_approval`, `stale_draft`, `approved_unpublished`, `published`,
      `missing_smoke`, `merged_without_close`, and `blocked_without_access`.
- [ ] Update audits so a parent cannot be green while a required child/post/PR
      review/smoke check is non-terminal.

Verification:

- [ ] Fixture tests cover representative issue titles, comments, routine runs,
      PR review issues, daily post drafts, QA incidents, and stale experiments.
- [ ] `paperclip_routine_audit` no longer hides linked non-terminal work.
- [ ] `paperclip_outcome_audit` reports non-zero outcomes when structured
      outcome events exist.

### Task 7: Tool, Env, And Access Preflight

- [ ] Build a per-agent runtime probe from `agents/.paperclip.yaml`, prompts,
      and routine descriptions.
- [ ] Check required tools and permissions before waking or assigning work:
      GitHub, Paperclip MCP/API, `gh`, `jq`, `psql`, Sentry, Prefect, Redis,
      editorial publishing, Telegram moderator role, and DB read/write role.
- [ ] When access is missing, create or update one canonical
      `[maintenance:access-*]` issue with env var names and the blocked agents.
- [ ] Remove stale plain defaults such as old container names or outdated
      Prefect URLs from agent runtime config when dynamic lookup or secret names
      are the right interface.

Verification:

- [ ] Probe output is redacted and machine-readable.
- [ ] Each agent has a clear `ready`, `degraded`, or `blocked` status with a
      next action.
- [ ] Missing access does not cause duplicate QA/ops issues.

### Task 8: Move Executable Prompt Workflows Into Tested Helpers

- [ ] For Staff Engineer PR review, create a helper/contract that maps each PR
      to exactly one Paperclip issue, checks GitHub-visible review artifacts,
      and handles merge/close state.
- [ ] For Comms, create a helper/contract for draft creation, structured
      approval, publish, and close with a stable `[post:...]` key.
- [ ] For QA, create a runtime probe and incident dedupe contract before test
      execution starts.
- [ ] Shrink prompts to role, decision criteria, escalation rules, and helper
      invocation contracts.

Verification:

- [ ] Prompt line count drops for the affected agents.
- [ ] Helper scripts have fixture tests and live dry-run modes.
- [ ] Triggering a representative PR/post/QA flow creates one clear next-step
      issue, not duplicate or blocked work.

### Task 9: Backlog Hygiene Based On Proven Rules

- [ ] Classify open Paperclip issues into duplicate, superseded, stale report,
      active implementation, approval waiting, access blocked, merged PR parent,
      and strategic/product.
- [ ] Auto-close only safe classes with proof: merged PR parents, completed
      child smoke checks, duplicate access issues superseded by a canonical
      maintenance issue, and stale reports replaced by a newer report.
- [ ] Leave strategic/product/experiment issues open unless an explicit closure
      rule applies.
- [ ] Record every closure in the problem ledger with evidence.

Verification:

- [ ] Open issue count drops only in safe classes.
- [ ] No strategic/product/experiment issue is closed by accident.
- [ ] Re-running the classifier is idempotent.

### Task 10: Trigger, Wait, Re-Audit

- [ ] Trigger one candidate flow at a time: QA log scan, process health check,
      PR review dispatcher, daily channel post, and agent-config dry-run.
- [ ] Wait a bounded window after each trigger.
- [ ] Re-run the relevant audit and compare against the baseline.
- [ ] If a flow still blocks, update the ledger with the new proof and choose
      the next smallest fix.
- [ ] Stop after the configured iteration/time budget or after all high-priority
      blockers have verified fixes.

Verification:

- [ ] Each triggered flow has before/after evidence.
- [ ] High-priority evidence classes trend down.
- [ ] There is no new public-repo redaction failure.
- [ ] Final report names remaining blockers and the exact missing access/env
      names, not secret values.

## Suggested Ralphex Command

First run a review-only sanity check of this plan:

```bash
ralphex --review specs/paperclip-architecture-ralphex-plan.md
```

Then run the long repair loop in an isolated worktree:

```bash
ralphex \
  --worktree \
  --max-iterations 24 \
  --review-patience 2 \
  --session-timeout 45m \
  --idle-timeout 8m \
  --wait 30m \
  specs/paperclip-architecture-ralphex-plan.md
```

Optional dashboard in a separate terminal:

```bash
ralphex --serve --port 8081 --watch .ralphex/progress
```

Expected progress log:

```bash
tail -f .ralphex/progress/progress-paperclip-architecture-ralphex-plan.txt
```

## Babysitting Checklist

- [ ] Stop if Ralphex prints secrets, full trigger URLs, raw auth headers, DB
      URLs, session strings, or private webhook URLs.
- [ ] Stop if it edits upstream Paperclip source or broad product behavior under
      `src/` without a new approved scope.
- [ ] Stop if it runs `agents/deploy.sh` without `--dry-run` before an explicit
      apply task.
- [ ] Stop if it closes strategic/product/experiment issues without a proven
      closure rule.
- [ ] Stop if it starts new product experiments instead of repairing agent ops.
- [ ] Redirect if it tries to solve missing access by hunting secrets instead of
      reporting env var names and creating a maintenance issue.
- [ ] Require `git diff --check`, relevant unit tests, redaction audit, and the
      relevant Paperclip re-audit before accepting each completed repair.
