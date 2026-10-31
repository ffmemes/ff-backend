---
id: channel_hits_v1
status: killed
hypothesis: Showing proven channel hits (by 24h forward rate) to confirmed non-subscribers in their feed brings retained invited guests
primary_metric: retained new invitees per host (needed >=6 in treatment)
guardrails: host activity days 7-13, host reactions vs 28d baseline
unit: user
variants: control:50,treatment:50 (fixed host cohort)
started: 2026-09-05
check_on: 2026-09-19
decided: 2026-10-30
result: n 43/42 hosts; retained invitees 0 vs 1, new invitees 1 vs 4; host reactions vs baseline 0.95 vs 0.77; hosts active d7-13 79.1% vs 73.8%
learning: Channel hits in the feed did not create retained invitees and may cut host activity; inconclusive per protocol
code: removed in PR #369 (git history)
readout: docs/analyst/readouts/2026-10-30-experiment-closure.md
---

# Experiment: Channel hits v1

Added in PR #355 (2026-09-05), return-session fix in PR #356. Published channel memes
were excluded from every private feed, including users who do not subscribe to the
channels. The test showed channel hits (comparable 24h forward rates, conservative
smoothing, source affinity) to confirmed non-subscribers, with membership cached
from channel events and a rate-limited backfill. Fixed-cohort enrollment, flags
default off. Exposure window ended 2026-09-19.

## Result (2026-10-30 closure)

ITT, n = 43 control / 42 treatment hosts. Exposure was 531 hit rows (2.06% of the
treatment feed). New invitees 1 vs 4, retained invitees 0 vs 1, unique non-self link
recipients 1 vs 5. Hosts active in days 7-13 79.1% vs 73.8%. Host reactions vs the
28d baseline 0.95 vs 0.77. The study needed at least 6 retained guests in treatment
and got 1. Killed, code deleted in PR #369.

Readout: [2026-10-30 closure](../docs/analyst/readouts/2026-10-30-experiment-closure.md).
