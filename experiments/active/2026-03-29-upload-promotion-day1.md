# Experiment: Upload Promotion Day 1

**Status:** active
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

## Metrics After

*(Fill in after 2026-04-12)*

## Conclusion

*(Fill in after measurement)*
