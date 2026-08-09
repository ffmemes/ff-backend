# Meme Share Button Readout: 2026-06-04

## Context

Question: did the "send to a friend" button above the like/skip buttons make
users share memes more and bring more new people into the bot?

Relevant launches:

- 2025-10-12: `bb5014d6` added the original persistent referral/share button
  to meme keyboards and recorded the product hypothesis in `README.md`.
- 2026-05-03: `specs/product-ideas-2026-05-03.md` framed "Send To A Friend"
  and warned that `t.me/share/url` only gives deep-link clicks, not send events.
- 2026-05-25: `ddc23cb1`, `e2f0bd6e`, and `a4e81b01` shipped the newer share
  implementation: `m_{sharer_user_id}_{meme_id}` links, exact shared-meme
  opening, safe shared-meme reactions, and docs that treat `m_` plus legacy
  `s_` as in-bot share attribution.

Production read was run from read-only analytics Postgres via
`ANALYST_DATABASE_URL`. DB time was `2026-06-04 16:29 UTC`; latest
`user_deep_link_log.created_at` was `2026-06-04 16:05 UTC`. Full-day
before/after comparisons below exclude the partial UTC day `2026-06-04`.

## Measurement Rule

Do not use raw `share_clicks` as "shares". Raw rows are heavily polluted by
self-clicks on a user's own meme link.

Use this rule for in-bot meme share attribution:

```sql
deep_link ~ '^[ms]_[0-9]+_[0-9]+$'
AND user_id <> split_part(deep_link, '_', 2)::bigint
```

Terms:

- `m_...`: current in-bot share deep link.
- `s_...`: legacy in-bot share deep link.
- `nonself_share_click`: a different user opened the shared meme link.
- `new share user`: a new `user_tg` row whose acquisition `deep_link` matches
  `^[ms]_[0-9]+_[0-9]+$`.

## Main Result

Compared with the nine full days before the 2026-05-25 rollout, the nine full
days after rollout show a real lift in useful share-click conversion:

| Window | Dates UTC | Memes sent | Raw share clicks | Self clicks | Non-self clicks | Unique clickers | Unique sharers | `m_` clicks | `s_` clicks | New share users | Non-self / 1k sent |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Pre | 2026-05-16..2026-05-24 | 212,188 | 324 | 318 | 6 | 5 | 4 | 0 | 324 | 4 | 0.028 |
| Launch day | 2026-05-25 | 28,181 | 61 | 52 | 9 | 3 | 3 | 8 | 53 | 0 | 0.319 |
| Post | 2026-05-26..2026-06-03 | 204,462 | 119 | 93 | 26 | 20 | 18 | 114 | 5 | 8 | 0.127 |

Interpretation:

- Useful recipient clicks increased from 6 to 26 while send volume stayed
  similar. Rate per 1,000 sent memes increased from 0.028 to 0.127, about 4.5x
  by Poisson rate ratio approximation (95% CI about 1.85x to 10.93x).
- The lift is not concentrated in one person or one meme. In the post window,
  26 non-self clicks came from 18 sharers and 20 memes. The top sharer had
  3 clicks; the top meme had 3 clicks.
- Raw share clicks fell because old direct-link self-clicks dropped. That is
  good for metric cleanliness and should not be read as lower sharing.
- Almost all useful post-rollout signal is from the new `m_` format: 24
  non-self `m_` clicks versus 2 non-self legacy `s_` clicks.

## New People

Total new-user volume did not step up:

| Window | Total new users | New users with share deep link | Share-origin share | New users with inviter |
|---|---:|---:|---:|---:|
| Pre, 2026-05-16..2026-05-24 | 48 | 4 | 8.33% | 1 |
| Post, 2026-05-26..2026-06-03 | 47 | 8 | 17.02% | 7 |

Interpretation:

- Share-attributed new users doubled from 4 to 8, but the absolute change is
  only +4 people over nine days.
- Total new users stayed flat, 48 before versus 47 after. There is not yet
  evidence that the button materially increased total acquisition.
- First-24-hour quality is not clearly better. Pre share users were 4 people
  with 83 reactions and 47 likes in their first 24 hours. Post share users were
  8 people with 23 reactions and 3 likes in their first 24 hours. This is tiny
  sample size, but it argues against claiming better-quality acquisition yet.

## Longer Baseline

The original 2025-10-12 button did not show a durable immediate lift:

| Window | Dates UTC | Memes sent | Non-self clicks | Non-self / 1k sent | New share users |
|---|---:|---:|---:|---:|---:|
| Initial pre 30d | 2025-09-12..2025-10-11 | 1,003,665 | 54 | 0.054 | 58 |
| Initial post 30d | 2025-10-13..2025-11-11 | 1,065,028 | 44 | 0.041 | 41 |
| Recent pre 30d | 2026-04-25..2026-05-24 | 721,969 | 32 | 0.044 | 23 |
| Recent post 9d | 2026-05-26..2026-06-03 | 204,462 | 26 | 0.127 | 8 |

The May 2026 implementation is the first visible positive signal in this read.

## Experiment/A-B Caveat

Do not use `experiment_assignment` for a URL-vs-inline conclusion yet.

- `TELEGRAM_INLINE_SHARE_ENABLED` was not set in the environment used for this
  read, so the code falls back to `url_share`.
- `experiment_assignment` has only 17 `meme_share_button` rows, all within
  `2026-05-25 15:58..16:03 UTC` (9 `inline_query`, 8 `url_share`).
- There were no `inline_search_chosen_result_logs` rows with exact
  `query ~ '^#[0-9]+$'` after launch. Inline sharing was not meaningfully
  exposed, so chosen inline result is not available as a send proxy.

## Decision

Keep the URL share button running. It appears to increase useful in-bot
share-click conversion and cleans up the old self-click-heavy signal.

Do not claim that it has already grown the bot materially. The observed
new-user lift is too small, total new users are flat, and early engagement of
post share users is weaker on a very small sample.

## Next Measurement

Future Analyst or Paperclip agents should:

1. Re-run after at least 21 full post-launch days or 100 non-self share clicks.
2. Always exclude the current partial UTC day from before/after comparisons.
3. Report both absolute counts and normalized `nonself_share_clicks / memes_sent`.
4. Keep new-user attribution separate from click attribution:
   `user_tg.deep_link ~ '^[ms]_[0-9]+_[0-9]+$'` for acquisition, and
   `user_deep_link_log` for all share-click behavior.
5. If an actual send proxy is needed, either enable and measure the inline
   variant properly or add a new explicit instrumentation point. `t.me/share/url`
   cannot prove that a user sent the link; it only lets us observe later
   recipient starts.
