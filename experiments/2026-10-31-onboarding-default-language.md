---
id: onboarding_default_language_v1
status: shipped
hypothesis: Defaulting unknown/bare-en users to en (instead of a blocking picker) gets every signup a first meme and more first reactions
primary_metric: share of signups with >=1 meme sent, share with a first reaction
guardrails: no-language signups = 0
unit: user
variants: none (pre/post bug fix)
started: 2026-10-31
check_on:
decided: 2026-11-15
result: first-meme delivery 49/62 -> 57/58; no-language 0/60 after merge; first tap 30/62 -> 18/58; mature reached-5 10/37 -> 10/38
learning: Keep the language bug fix; restored delivery does not establish activation uplift, which needs a separate randomized test
code: src/tgbot/handlers/start.py, language.py (PR #385)
readout: experiments/2026-10-31-onboarding-default-language.md (inline SQL)
---

# H13 — Default language instead of blocking picker

| Field | Value |
|-------|--------|
| **ID** | `onboarding_default_language_v1` |
| **Status** | **shipped**, review closed 2026-11-15 (not an A/B; bug fix) |
| **Code** | `src/tgbot/handlers/start.py` (language seeded above the deep-link ladder), `language.py` picker callback |

## Hypothesis

Bare-`en` / unknown Telegram users got only the language picker on /start, no
`user_language` row, and so no meme (feed joins on `user_language`). 6 weeks to
2026-10-31: 21/150 signups (14%) had no language row, 0 of them got a meme, 0
clicked the picker. Now they default to `en`, get welcome + first meme
immediately, and the picker follows the meme (`/lang` still works).

## Growth bar

Share of signups with ≥1 meme sent → ~100% (minus blocked); share with a first
reaction should rise. Baseline 6w: got meme 128/150 (85%), reacted 79/150
(53%); last 2 weeks 42/56 (75%) and 27/56 (48%). Guardrail: no-language
signups = 0.

```sql
SELECT date_trunc('week', u.created_at)::date wk, count(*) signups,
  count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM user_language l WHERE l.user_id=u.id)) no_lang,
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM user_meme_reaction r WHERE r.user_id=u.id)) got_meme,
  count(*) FILTER (WHERE EXISTS (SELECT 1 FROM user_meme_reaction r
    WHERE r.user_id=u.id AND r.reacted_at IS NOT NULL)) reacted
FROM "user" u WHERE u.created_at >= now() - interval '42 days' GROUP BY 1 ORDER BY 1;
```

## Next check

Closed on **2026-11-15**. No further experiment checkpoint; ordinary delivery monitoring continues.

Not doing: a multi-select language picker for new users (it is already one tap; `/lang` is settings).


## Readout 2026-11-15

Interim: 14d pre/post first-meme delivery 49/62 -> 57/58, first tap 30/62 -> 18/58; post-merge no-language 0/60. Bug fixed, activation uplift not established. [Full snapshot](../docs/analyst/readouts/2026-11-15-experiment-review.md).

## Decision 2026-11-15

Keep the already deployed fix and close the delivery review as shipped. This is
not a win for the activation hypothesis: in equally mature cohorts, reached-5
was 10/37 before and 10/38 after. The non-randomized comparison cannot attribute
the first-tap decline to this fix. Test activation separately in the proposed
[humor-preview experiment](2026-11-15-humor-preview-onboarding.md).
