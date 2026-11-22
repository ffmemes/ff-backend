---
id: dormant_push_exploration_v1
status: running
hypothesis: Uniform exploration among up to three HQ candidates increases the chance of a button press within 24 hours of the existing one-week push
primary_metric: first assigned person's callback on the accepted selected meme within 24h of assignment (ITT)
guardrails: ambiguous dispatch or stale reservations, accepted and failed deliveries, recorded blocks, candidate coverage and latency
unit: user
variants: hq:50,explore:50 within the existing 1w send arm
started: 2026-11-21
check_on: 2026-11-23
decided:
result: unknown
learning:
code: DORMANT_PUSH_EXPLORATION_ENABLED, src/broadcasts/exploration.py
readout: docs/analyst/dormant-push-exploration.sql
---

# One-week push content exploration

Enrollment starts on production activation and ends at **2027-01-17 00:00 UTC**.
Check operations on November 23 and after each failure alert. The fixed final
readout is **2027-02-01 00:00 UTC**, after every enrolled person's fourteen-day
follow-up. Record the actual deployment and first assignment below.

The existing cadence send/no-send split selects the audience first. Only the
one-week sending arm enters this independent, stable 50/50 user assignment.
Ordinary users qualify; excluded, moderator and admin accounts stay outside the
experiment. HQ chooses the first candidate from the usual HQ ranking. Explore
chooses uniformly among its first one to three eligible candidates. The same
quality floors, language and eligibility rules apply to both. An empty HQ pool
uses the shared feed fallback and stays in the assigned denominator.

A durable opportunity records the audience anchor, arm, candidate order and
scores, chosen index, selection probability and Telegram receipt. A retry or
parallel worker reuses that opportunity. An ambiguous send stays quarantined.
The first enrolled opportunity per person is the primary unit. Every first
assignment counts, including empty pools, recheck skips and failed sends.
Subsequent enrolled opportunities retain that person's arm and are operational
diagnostics. Opportunities after enrollment closes or above the per-run cap use HQ.
People who later become moderators or admins remain in their original assigned
cohort. Project-excluded automated accounts are omitted from the readout.

## Outcomes and interpretation

The primary success is a valid persisted like or next callback on the accepted
chosen meme, from dispatch attempt through the first assignment's 24-hour
boundary. Match the exact user, meme, delivery path and delivery timestamp. A
Telegram acceptance is distinct from successful local reaction bookkeeping.
Report accepted receipts with missing reaction rows as a measurement failure.

The secondary outcome is at least one canonical `v_feed_session` with a reaction
and a session start in days 7–14 after assignment. This uses the project's session
definition and excludes push sends. Also report recorded blocks in fourteen days,
accepted receipts, failed/unknown/skipped attempts, fallback, pool coverage and
non-top choices. A send can discover an old silent block, and unblocking clears
the stored block timestamp. Recorded block counts measure that operational signal.

This comparison estimates the two content policies under the existing cadence.
Each arm's later feed and other scheduled steps continue using their normal
policies. Effects of whether to send are evaluated in the existing cadence
holdout. Its December 11 one-week send/no-send readout consequently estimates
sending this mixture of HQ and exploration. Record the activation timestamp and
report before/after activation separately. If that cadence decision disables the
one-week step, enrollment ends immediately with its achieved sample and the
content test is read at the fixed final date. Candidate probabilities condition on the recorded HQ pool. Feed queue
fallback has an unknown pool-generation probability and is outside future
candidate-policy weighting. Its outcomes remain in the randomized comparison.
The laptop models are prediction baselines. This experiment supplies randomized
candidate outcomes for future local learning and prospective model tests.

## Frozen decision rule and power

A read-only check on November 21 found 226 ordinary users newly assigned to the
one-week send arm and 71 to holdout since October 30. The last complete weeks had
82 and 72 new send users. Of 222 send users with mature outcomes, 39 had a valid
callback on a push delivered within one hour of assignment, approximately 17.6%.
These historical matches provide a planning estimate, because the previous
sender lacked the new durable delivery receipts.

At approximately ten new send users daily, eight weeks yields roughly 280–300
people per content arm. At a 17.6% baseline, a two-sided 5% test has approximately
80% power only for an absolute gain around 9–10 percentage points. A one-point
gain would require tens of thousands of people per arm. Declare the result
inconclusive if either arm has fewer than 200 mature first assignments at the
fixed final date. Do not extend enrollment after seeing an efficacy estimate.

At the final readout report the raw rates, explore-minus-HQ absolute difference
and two-sided 95% uncertainty. The SQL supplies a large-sample interval; verify
with a two-binomial interval before any adoption. Consider promotion only if
both arms have at least 200 people, the interval excludes zero in the positive
direction, and the downstream outcome and operational diagnostics show no harm.
Report an inconclusive result when uncertainty crosses zero. Pool overlap and
fallback dilute the policy contrast and must accompany the result.

The dispatcher automatically pauses experimental enrollment on an ambiguous
send or receipt/bookkeeping exception. A sending reservation older than two
minutes automatically pauses new enrollment. Investigate any reservation still
in-flight after ten minutes and pause for an unresolved bookkeeping inconsistency
or an actual duplicate delivery. A retry claiming an existing unique reservation
is expected and skips delivery. Automatically pause if failed or unknown sends
exceed 5% after at least twenty attempted enrolled opportunities in either arm.
For block harm the automatic rule uses Forbidden delivery discoveries, counted
across enrolled opportunities. Pause if both arms have at least fifty attempts
and Explore has at least five Forbidden events with an event rate at least three
percentage points above HQ. These operational denominators include repeat
opportunities. The final fourteen-day recorded-block readout uses first assigned
people. These checks can stop enrollment for harm. They cannot authorize early
promotion. The feature switch and enrollment deadline must retain the existing opportunity reservation
so a later retry cannot send twice.

## Log

- 2026-11-21 — Preregistered before exposure. Local historical aggregates measured
  through November 21. The first scheduled exposure follows production activation.

- 2026-11-21 21:31 UTC — Production activation verified after [PR #400](https://github.com/ffmemes/ff-backend/pull/400). The dedicated Prefect runner loaded `f3bea4fc`, the database was at revision `b6d8f0a2c4e6`, and the weekly deployment was ready with its hourly schedule active. The experiment, HQ picker and 20% silent cadence holdout were enabled. The aggregate readout returned zero assignments at activation. Eligible users enter on ordinary scheduled runs.

## November 22 review

First assignment November 21 at 23:07 UTC, rounded. At November 22 14:30 UTC, HQ enrolled six and Explore two. Telegram accepted all eight, with three recorded candidates and a matching delivery for each. One Explore assignment chose a non-top meme. One exact-meme callback had arrived. Zero people had mature 24-hour or 14-day outcomes. All 17 hourly runs completed. Keep the November 23 operations check. [November 22 evidence](../docs/analyst/readouts/2026-11-22-experiment-check.md).
