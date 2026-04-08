# Experiment: Upload Promotion Day 1

**Status:** archived
**Created:** 2026-03-29
**Measure after:** 2026-04-12 (14-day window)

## Hypothesis

Cohort analysis shows upload is the strongest habit predictor: 36.8% of super users upload memes vs 0.2% of churned users. Most new users never discover the upload feature.

Sending a friendly message on Day 1 (after ~10 memes seen) explaining that users can upload their own memes will increase upload adoption and drive retention by creating a repeat-use habit loop.

## Changes Required

- Send a one-time message to new users after they've seen ~10 memes (or after first session ends, whichever comes first)
- Message content: brief, friendly explanation that they can send memes to the bot and they'll be shared with other users
- A/B split: 50% of new users get the message, 50% don't (control)
- Track which users received the message via a flag (e.g., user.data JSONB field)

## A/B Test Design

- **Group A (treatment):** Receives upload promotion message after ~10 memes
- **Group B (control):** No message (current behavior)
- **Split method:** user_id % 2 == 0 (treatment) vs == 1 (control)
- **Minimum sample:** 50 users per group (expect ~100 new users in 14 days at current organic rate)

## Metrics to Track

| Metric | Baseline | Target |
|--------|----------|--------|
| Upload rate (Day 7) | ~0.2% (churned cohort baseline) | >5% |
| D7 retention | TBD (measure control group) | +10pp vs control |
| Session length (Day 7) | 18 (North Star) | no regression |
| Upload-to-approved rate | TBD | >50% (quality check) |

## Success Criteria

- Upload rate in treatment group >5% within 7 days
- D7 retention in treatment group is higher than control by >5pp
- No session length regression

## Failure Criteria

- Upload rate stays <2% (message doesn't drive behavior)
- D7 retention is lower in treatment (message annoyed users)
- Spam uploads increase significantly (quality problem)

## Notes

- Runs alongside cold_start_v2 (different funnel stage: cold_start = first 5-15 memes quality, upload promo = Day 1 habit formation)
- No attribution conflict: cold_start_v2 measures first-meme LR and 10-meme retention, this measures upload adoption and D7 retention
- Message timing matters: too early (first session) feels spammy, too late (Day 3+) misses the habit window. Day 1 after first session is the sweet spot.
- Message should feel personal, not promotional. "Did you know you can send your own memes? Just send an image to this chat and it'll be shared with other users who might love it."

### CEO Review Notes (Apr 6, Day 8)

- D1 retention converged: treatment 28.1% ≈ control 28.6% — no signal
- Upload rate: treatment 3.2% vs control 8.8% — negative signal (control uploads more!)
- D7 data first available today (Apr 6). Requested FFM-304 analyst report.
- **Decision point:** If D7 shows no retention lift, archive experiment. Promo message format/timing needs complete rethink, not iteration.
- Possible issues: message too passive ("did you know?"), timing too early (10 memes = still exploring), no CTA (no button to start uploading)

### CEO Review Notes (Apr 7, Day 9)

- Still no D7 data — analyst reports missing Apr 6-7. Requested FFM-326 (HIGH priority).
- D1 retention: no signal (converged at ~28% both groups since Apr 5).
- Upload rate: still negative (treatment 3.2% < control 8.8% as of Apr 5).
- **Decision: BLOCKED on D7 data.** If D7 shows no retention lift, archive immediately.
- If D7 data still unavailable by Apr 8, archive based on D1+upload signals alone (both negative/neutral).

## Metrics After

| Metric | Baseline | Target | Result |
|--------|----------|--------|--------|
| Upload rate (Day 7) | ~0.2% | >5% | 3.2% treatment vs 8.8% control — **NEGATIVE** |
| D7 retention | TBD | +10pp vs control | **No data** (analyst reports missing Apr 6-8) |
| D1 retention | — | — | 28.1% treatment ≈ 28.6% control — **No signal** |
| Session length | 18 | no regression | 16-20 range (within normal) |

## Conclusion

**ARCHIVED (Apr 8, Day 10).** No positive signal on any metric after 10 days:

1. **D1 retention:** Converged at ~28% both groups — no lift from promo message
2. **Upload rate:** Treatment group (3.2%) actually uploads LESS than control (8.8%) — promo may discourage uploads by making the feature feel "pushed"
3. **D7 data:** Never obtained despite 3 HIGH-priority requests (FFM-304, FFM-326). Analyst reports missing since Apr 5.
4. **Session length:** No regression, but no improvement either

**Root cause analysis:** The "did you know?" passive message format was ineffective. No CTA button, no friction reduction, no social proof. The message told users about uploading but didn't make them want to upload. The negative upload rate signal suggests the message may have created psychological reactance ("they want me to do work for them").

**Next steps:** Upload promotion concept is still valid (36.8% super users upload vs 0.2% churned), but needs a completely different approach:
- Interactive CTA ("Send me a meme right now and I'll share it with 500+ users")
- Social proof ("47 users uploaded memes this week — join them!")
- Timing: after positive experience (like streak), not arbitrary meme count
- Consider upload-based onboarding rather than Day 1 promotion

**Freed experiment slot** for next priority (per-user goat recency filter, FFM-305).
