---
id: friend_challenge_h12
status: killed
hypothesis: A 'five memes for a friend' game turns regular users' friends into retained feed readers
primary_metric: retained new invitees per 100 assigned senders (>=3 feed memes reacted on days 7-13)
guardrails: recipient block rate <30%
unit: user
variants: treatment:90,holdout:10
started: 2026-10-30
check_on: 
decided: 2026-10-31
result: 0 participations ever
learning: Nobody played, so the friend-invite idea is untested, not disproven
code: FRIEND_CHALLENGE_ENABLED (default false), removed in a follow-up PR
readout: docs/analyst/friend-challenge-h12.sql
---

# Experiment: Friend challenge "Пять мемов для друга" (H12)

Merged 2026-10-30 in PR #364 behind `FRIEND_CHALLENGE_ENABLED` (default false).
Design: [docs/growth/2026-09-05-friend-meme-challenge.md](../docs/growth/2026-09-05-friend-meme-challenge.md)
(the 2026-10-30 header block overrides the September protocol).

- After an ordinary feed like, an eligible user (active on >=8 of the last 28 days,
  >=20 likes in that window, not blocked; about 234 users) was assigned once in
  `experiment_assignment` (`friend_challenge_h12`): 10% holdout, 90% treatment.
- Treatment users got one offer (also `/friend`): pick five memes, share a
  `start=fc_<token>` link. The friend rates 5 memes, sees "N из 5", continues into
  their own feed; a new friend gets `user.inviter_id` = sender.
- Ambitious target: double weekly activated new users (baseline ~10/week) within 6
  weeks. Kill: <5 retained invitees per 100 senders at d28 or recipient block rate >30%.

## Log
- 2026-10-30: merged behind the flag.
- 2026-10-31: killed (0 participations ever); code removal is in a separate PR.
