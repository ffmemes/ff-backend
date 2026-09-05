# Channel hits during return sessions

The initial pilot could only place a hit in the first five ordinary sends of the
first UTC-day session. A user who browsed earlier that day could not receive a
hit after returning, even if the first visit produced no experimental hit.

The revision allows one hit in the first five ordinary sends of each real
session after more than 30 minutes of inactivity, capped at three attempts in
the preceding 24 hours. A session can cross midnight. Both the old and new hit
labels count toward quota recovery from delivery history; atomic reservations
also count uncertain attempts. Missing candidates or operational errors keep
the ordinary feed available. Subscriber, known-delivery and duplicate filters
are preserved, with no Telegram membership HTTP calls in the feed.

## Evidence for the frequency change

Read-only production analysis covers August 12 through September 4 inclusive.
Earlier days were excluded from the primary result because broadcast origin
labels were not reliable throughout that history. Sessions are based on clean
ordinary deliveries, including sends with no reaction. They are computed across
midnight, then assigned to their start date. These are reconstructed browsing
episodes, not measured app opens.

For the frozen 85-user pilot, a 30-minute gap produces 4,075 sessions across
1,342 active user-days. A second or later session occurred on 67.4% of those
days; median sessions per active day were two. Median session depth was 13
deliveries, and the median pause between same-day sessions was about 78 minutes.
Later sessions had a median 11 deliveries, compared with 17 in the first session.

The conclusion is robust to the threshold: the fraction of active days with
multiple sessions was 71.4% at 15 minutes and 59.7% at 60 minutes. Reaction-based
sessionization gives 64.1% at 30 minutes. The broader 402-user population gives
55.5% at 30 minutes and includes the pilot; it is not an independent control.
Thirty minutes remains a practical existing convention, not an estimated
optimal threshold or proof of a unique natural boundary.

A historical replay gives 1,342 ideal daily opportunities, versus 1,929 with
one per session capped at two in rolling 24 hours, and 2,539 capped at three.
The selected three-attempt cap gives 1.89 times as many opportunities. This
simulation assumes a usable hit at each accepted session start and unchanged
user behavior; it does not estimate realized exposures or growth.

At the inventory check, all 42 treatment users had at least 37 eligible unseen
hits, with median 128.5. Forty had at least 42 candidates. Stock is not promised:
membership, moderation, ordinary consumption and rolling age can change it.
When a user has no eligible hit, continue the ordinary feed; never recycle a
known delivered meme to meet a frequency target.

## Preserve the experiment

Keep the same 42 treatment / 43 control users, baseline, original 14-day window
and outcome denominators. New deliveries use `channel_hit_session_v2`; the
original `channel_hit_v1` history remains intact. The readout reports both
cadence counts and their combined exposure. Record production activation time
and old/new exposure counts during rollout. Do not call cadence activation a
growth result, and do not rerandomize after looking at outcomes.

Reproducible evidence lives in
`docs/analyst/research/2026-09-05-growth/session-cadence/`. Existing stored
user/meme rows are mutable and can lose duplicate/repeat events; historical
session reconstruction is approximate. No raw user data was exported.

## Verification

The complete isolated release suite passed on Python 3.14: 772 tests passed,
two existing tests were skipped, and eight subtests passed. Ruff and the public
repository redaction audit passed. Disposable local PostgreSQL/Redis fixtures
were cleaned after validation; no production fixture data was written.

Required regression cases cover later same-day visits, missed first-visit slots,
cross-midnight sessions, the first-five boundary, rolling 24-hour quota,
concurrent reservations, Redis loss with durable deliveries, both cadence labels,
and ordinary-feed fallback. The analytical readout must retain zero-exposure
hosts and distinguish cadence labels without changing referral denominators.

The latest-six-send bound was checked against full histories in 100,000
deterministic generated sequences with no disagreements. A read-only production
preview for all 42 treatment users measured the session query at 1.42 ms median
and 1.81 ms p95; this is query time, not total feed request latency.

After total Redis data loss, only successful persisted deliveries can restore
the quota. Ambiguous attempts without a delivery row cannot be reconstructed;
do not claim durable preservation of those attempts across a cache reset.
