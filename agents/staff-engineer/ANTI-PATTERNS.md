# Staff Engineer — Anti-Patterns Log

Append-only log of real production failure modes. Each entry maps to a specific Self-Check Gate path/item in `AGENTS.md` that catches recurrence. Do not edit history — only append at the bottom with the next number.

**Why this file exists**: every row was a "agent said done, reality was broken" incident. Reading the gate without the case log makes it look like paranoia; reading the case log without the gate makes it look like helplessness. Together, they're a closing feedback loop.

**Format per entry**:
- **#N (YYYY-MM-DD) — short title** [refs: PR #X | issue ID]
  - **What happened**: 1-2 sentences.
  - **Anti-pattern**: what NOT to do.
  - **Caught by**: gate path/item.

---

#1 (2026-04-17) — SE never engaged on PR for 6 days [PR #177]
- **What happened**: PR #177 was opened on 2026-04-17 04:06 UTC and sat 6.3 days unreviewed. The staff-engineer trigger never fired on the original PR open event. ohld manually closed and reopened the PR on 2026-04-23 to re-fire the webhook, after which a wake finally happened.
- **Anti-pattern**: Trusting that `PAPERCLIP_TASK_ID` is set on every PR event. The webhook can drop and the agent never knows it was supposed to wake. A wake-less agent has nothing to self-check.
- **Caught by**: Path A2/B2/C2/D1/E1 — the gate requires a review-signal artifact on GitHub before ANY close. If you woke without `PAPERCLIP_TASK_ID` and inbox-fallback returned empty, exit clean. Do not close any other PR's execution issue from a different wake.

#2 (2026-04-25) — Silent exit, zero artifact on GitHub [PR #199]
- **What happened**: PR #199 (alembic single-head CI check) was opened 13:06 UTC and merged 17 hours later at 06:12 UTC the next day with **zero** SE comments, zero SE reviews, no `STAFF ENGINEER REVIEW:` prefix anywhere on the PR. Either SE never woke, or it ran the workflow internally and exited without posting any GitHub-visible signal.
- **Anti-pattern**: Closing the execution issue based on internal "I ran the workflow" state instead of verifying public artifacts exist on GitHub. Internal success ≠ delivered review.
- **Caught by**: Path A2 — re-fetch `gh pr view ... --json comments,reviews` AFTER step 7 and confirm a `STAFF ENGINEER REVIEW: APPROVED|CHANGES REQUESTED` artifact exists. No artifact → did not deliver.

#3 (2026-04-25) — Auto-merge race during changes-requested [PR #201]
- **What happened**: PR #201 (the meta-fix for SE's merge cycle) needed 4 rounds of `/codex` review. A queued auto-merge from a prior wake fired during a later wake that was preparing `--request-changes`. Required mid-cycle out-of-band `gh api -X PATCH ... allow_auto_merge=true` flip to recover.
- **Anti-pattern**: Posting `--request-changes` (or its comment-fallback) without first cancelling any auto-merge queue from a prior wake. The race window between "queue cancel" and "request-changes signal" is small but real, and a CI green lands inside it.
- **Caught by**: Path D2 — re-verify `autoMergeRequest == null` AFTER posting the changes-requested signal. If non-null, you raced; cancel again and re-check.

#4 (2026-04-25) — Bare `gh pr merge` lost the CI race [PR #200]
- **What happened**: PR #200 (dead-code removal) hit the error `base branch policy prohibits the merge` 25 seconds after the agent woke. The agent had polled CI green and called bare `gh pr merge --squash`. The poll-then-merge gap is non-trivial; in this run, a transient policy state appeared between poll and merge.
- **Anti-pattern**: Bare `gh pr merge --squash` after polling CI green. The agent loses every race against GitHub state — `--auto` exists for this reason.
- **Caught by**: Path A1/B1 — after the merge call, must observe either `state=MERGED` (immediate) or `autoMergeRequest != null` (queued). If neither, the merge call did not take and the issue must be `blocked`, not `done`.

#5 (2026-04-26, user pain report) — Post-merge chain dies silently
- **What happened**: ohld reported that the full flow (PR → SE merge → Coolify deploy → QA post-deploy verification → E2E smoke) "doesn't quite work end to end". Webhooks at the GH→Coolify boundary occasionally fail to fire without alerting. The PR is `MERGED`, the agent closes its issue `done`, but the deploy never starts and QA never runs. The chain dies between SE-done and Coolify-deploy with no surfacing signal.
- **Anti-pattern**: Treating "auto-merge queued" or even `state=MERGED` as terminal for SE. Auto-merge queued ≠ deploy started ≠ QA verified. SE's deliverable spans up to "deploy reflects the merge commit" because that's the next observable handoff.
- **Caught by**: Path A3 — Coolify deploy probe by comparing `last_online_at` on `/api/v1/applications/<uuid>` (when the container last became healthy) against `mergedAt` from the PR. If after 5 minutes `last_online_at < mergedAt`, the deploy never fired — file `[chain-broken:coolify-not-triggered] PR #<n>` HIGH for CTO. Closing `done` is still correct (review+merge delivered) but the broken-link issue MUST be filed in the same wake. Note: Coolify's `git_commit_sha` field looks tempting but is unreliable for `dockercompose` build-pack apps (returns literal `"HEAD"`); use the timestamp probe.

#6 (2026-04-26) — `SC=$(gh pr view --json comments,...)` corrupts JSON
- **What happened**: While testing the Self-Check Gate locally, `SC=$(gh pr view 201 --json comments,reviews,...)` followed by `echo "$SC" | jq` failed with `parse error: Invalid string: control characters from U+0000 through U+001F must be escaped`. `gh pr view --json` emits the JSON value with literal newlines inside long comment bodies (it is not strict-spec valid). Bash captures it verbatim and `echo` re-emits it, so `jq` cannot re-parse.
- **Anti-pattern**: Storing `gh pr view --json comments,reviews,...` output in a bash variable and re-piping through `echo "$VAR" | jq`. Works fine for short PRs without multiline comments; fails silently for any PR with markdown bodies (which is most of them).
- **Caught by**: The Self-Check Gate now mandates writing to `/tmp/sc.json` and reading via `jq ... /tmp/sc.json`. The "use a tempfile, not a var" rule should be applied anywhere the gate reads multiline GitHub fields.

#7 (2026-04-26, codex review of this PR) — Approval grep too narrow for non-self-review-blocked authors
- **What happened**: First draft of the Self-Check Gate's A2/B2/C2 only grepped `^STAFF ENGINEER REVIEW: APPROVED` in comment/review bodies. But step 7 only falls back to that comment-prefix when GitHub self-review-blocks (i.e., ohld-authored PRs). For non-ohld internal authors and external authors, step 7 uses a real `gh pr review --approve -b "Review summary"` whose body does NOT start with the prefix. Those legitimate approvals would have failed the gate, leaving the execution issue stuck `blocked`.
- **Anti-pattern**: Writing a verification check around the *most common* artifact form (the comment-fallback for ohld) and forgetting the alternate form (formal review) used for the other 30% of cases. Asymmetric paths require asymmetric checks.
- **Caught by**: Path A2/B2/C2/D1/E1 — verification accepts EITHER a `.reviews[]` entry with `state == "APPROVED"|"CHANGES_REQUESTED"` OR a comment body starting with the `STAFF ENGINEER REVIEW:` prefix. Pre-merge codex review caught this before the prompt shipped to production.

#8 (2026-04-26, codex review of this PR) — Coolify deploy probe fires false alarms within the first 5 minutes
- **What happened**: First draft of A3 unconditionally compared `last_online_at` to `mergedAt`. Right after the agent merges, the GH→Coolify webhook fires, Coolify pulls + builds + restarts the container — typically a 3-5 minute cycle. During that window `last_online_at` is still the previous deploy's value (pre-merge). If the agent ran the gate immediately, it would file `[chain-broken:coolify-not-triggered]` for every healthy PR, drowning CTO in false-positive incidents and inverting the firefighting reduction the gate is supposed to deliver.
- **Anti-pattern**: Writing a "next-link probe" without modeling the latency of the next link. Probes need a grace window matched to the system's natural deploy cycle.
- **Caught by**: Path A3 — probe is gated on `now - mergedAt >= 300s`. If the merge is younger than 5 minutes, the probe is deferred (silently — QA's hourly Process Health Check covers stuck deploys). Only after the grace window does a pre-merge `last_online_at` count as evidence of chain-broken.
