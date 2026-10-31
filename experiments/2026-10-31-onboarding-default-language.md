---
id: onboarding_default_language_v1
status: running
hypothesis: Defaulting unknown/bare-en users to en (instead of a blocking picker) gets every signup a first meme and more first reactions
primary_metric: share of signups with >=1 meme sent, share with a first reaction
guardrails: no-language signups = 0
unit: user
variants: none (pre/post bug fix)
started: 2026-10-31
check_on: 2026-11-14
decided: 
result: unknown
learning: 
code: src/tgbot/handlers/start.py, language.py (PR #385)
readout: experiments/2026-10-31-onboarding-default-language.md (inline SQL)
---

# H13 — Default language instead of blocking picker

| Field | Value |
|-------|--------|
| **ID** | `onboarding_default_language_v1` |
| **Status** | **live** (not an A/B; bug fix) |
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

**2026-11-14**.

Not doing: a multi-select language picker for new users (it is already one tap; `/lang` is settings).
