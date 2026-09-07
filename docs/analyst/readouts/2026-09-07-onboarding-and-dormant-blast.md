# Onboarding leak + dormant blast — 2026-09-07

**Clock:** analyst DB `2026-09-07 ~12:32 UTC`  
**SQL to re-run:** [`docs/analyst/onboarding-funnel.sql`](../onboarding-funnel.sql), [`docs/analyst/broadcast-reengagement.sql`](../broadcast-reengagement.sql)  
**Hypotheses:** H3c (viral push), H9 (first-tap), H10 (fresh first meme), H11 (drop 3-2-1) in [`docs/growth/HYPOTHESES.md`](../../growth/HYPOTHESES.md)

Growth bar for any follow-up: **less leaky funnel** (first-tap, first-like, reached-5) and/or **k-factor** (unique non-self share clicks, new-user invites). Session length stays a guardrail.

## Founder calls (do not re-litigate)

1. Exponential reengagement **15m → 24h → 48h → 1w → 2w → 4w** is intended while the user is still fresh. Habit, not spam. After that, **one monthly reminder** for people who already used the bot.
2. Do **not** kill that cadence. Lever is **meme quality** in the push, not fewer early nudges.
3. Today's one-shot `dormant-channel-viral-2026-09-07` **finishes**. Next time: not all idle ghosts; prefer 7–28d with holdout.
4. Language picker / share-skip-onboarding are **not** the first thing to rewrite.

## Measurement pitfall

`user_stats.nmemes_sent` often stays **0** until a reaction. Silent users look like they got 0–1 memes. Count sends from `user_meme_reaction`. Include `user.type IN ('user','blocked_bot')` for all-time block funnels (`blocked_bot` is a legacy type, ~10.5k rows).

---

## 1. Onboarding steps (as shipped)

| Step | Empty `/start` | Share `s_` / `m_` |
|------|----------------|-------------------|
| 1. Entry | logged in `user_deep_link_log` | same |
| 2. Language | auto (Cyrillic name / CIS → `ru`; `uk`/`es`/`fa`/`hi` → that code) or **one-tap** `ol:{lang}` | language of **that** meme added |
| 3. Explain | welcome + **~9s 3-2-1** | skipped |
| 4. First meme | `cold_start_explore` | the shared meme (`share_link`) |
| 5. First tap | like/skip | like/skip, then welcome+countdown runs |
| 6. Feed | `next_message` | same |

New-user picker is already exclusive (`set_user_languages_exclusive`). Multi-select with checkmarks is **`/lang` settings**, not first start.

---

## 2. 90-day new-user funnel (`type=user`, n=415)

| Stage | n |
|-------|--:|
| Registered | 415 |
| Got a meme | 402 |
| Ever reacted | 252 |
| Reacted within 1h of first send | 246 |
| Got meme, never reacted | **150** |
| Never got a meme | 13 (3 blocked in ~5s, 10 alive, all no language) |
| No `user_language` | 43 (16 blocked / 27 alive) |

**Leak is step 5**, not step 2 or 4. 402/415 saw a meme; 150/402 (~37%) never tapped.

### By entry

| Entry | n | Got meme | Ever reacted | % of registered | p50 to first meme |
|-------|--:|---------:|-------------:|----------------:|------------------:|
| empty `/start` | 310 | 298 | 189 | **61.0%** | 11.6s |
| share `s_`/`m_` | 31 | 31 | 22 | **71.0%** | 0.2s |
| channel `sc_` | 21 | 20 | 14 | 66.7% | 11.5s |
| other | 53 | 53 | 27 | 50.9% | 11.7s |

Share skips welcome+picker and **converts better**, not worse. First like on share first-meme: 12/31 (36%) vs cold-start 83/371 (22%). After a share tap we still fire welcome+countdown — odd, not the leak.

### Empty start, time to first meme

| Lag | n | Reacted | First like | First skip |
|-----|--:|--------:|-----------:|-----------:|
| no meme | 12 | 0 | 0 | 0 |
| 8–15s (countdown) | 233 | 140 (**60%**) | 55 (24%) | 85 |
| 15–60s (picker) | 58 | 46 (**79%**) | 18 (31%) | 28 |

Picker users convert **better** than auto-language + countdown. Volume leak is the 233 countdown people.

### Silent after first meme (90d)

- Blocked silent: **84**. 44 got exactly 1 meme. p50 **~3 min** from first meme to block.
- Alive silent: **66**. Almost none with 1 meme; 57 already have 6+ sends (`cold_start_explore` + later `lr_smoothed` + `broadcast_*`). We keep writing into a chat that never tapped.

Global unblocked, no language: **598** (532 never reacted). Viral/HQ picks skip them.

---

## 3. All-time never-reacted (`user` + `blocked_bot`) = 9,161

| Bucket | n | Exactly 1 meme | Block in 5m from start | Block in 5m after first meme |
|--------|--:|---------------:|-----------------------:|-----------------------------:|
| alive, got meme, silent | 4,492 | 278 | — | — |
| blocked, no meme | 2,015 | — | **1,421** | — |
| blocked, got meme, silent | 2,011 | 906 | 631 | **690** |
| alive, no meme | 643 | — | — | — |

Historically both “start then delete before a meme” and “one meme then delete” were large. **Last 90 days** the first pattern is almost gone (3 people). The remaining hole is “saw first meme, did not tap”.

---

## 4. First cold-start meme is old (observational)

`cold_start_explore` floors: ≥25 explicit reactions, raw LR ≥0.50, order by `lr_smoothed`. **No recency filter.** Catch-22: a fresh post from a strong TG channel often cannot enter the first slot until the bot has already shown it a lot.

90d first `cold_start_explore` meme (n=371):

| Age at send | n | First like % | React % |
|-------------|--:|-------------:|--------:|
| 0–7d | 163 | 22.7 | 57.7 |
| 7–30d | 17 | 17.6 | 52.9 |
| 30–90d | 36 | 27.8 | 66.7 |
| 90d+ | 155 | 21.3 | 57.4 |

Median age **40 days**, mean **192**, half older than a month, mean **315** bot likes.

Age **did not** move first-like in this cut (~22% fresh and old). Hypothesis “old = automatically bad” is **unproven**. What is proven: we systematically show a **bot-proven old hit**, not a **fresh channel outlier**. Share first-memes are fresher (p50 **6 days**) and like more — but those users chose the meme.

Parser already keeps per-source outliers (top 5 of last 10 posts by views; drop below 30% of source median). That inventory does not automatically become the first onboarding meme.

Earlier cold-start notes (Jul–Aug, small n) said first meme was “fine” and skip exploded from position 2. This 90d cut says **37% never even tap the first**. Both can be true in different windows; H9 treats first-tap as the current primary leak.

---

## 5. Dormant blast `dormant-channel-viral-2026-09-07`

One-shot to users idle **7+ days** (12,223 dry-run). Picker: last-7d channel-viral by forwards, else HQ, else queue. Delay 0.3s. Started **2026-09-07 11:27 UTC**. Founder: **let it finish**.

~12:32 UTC (still sending):

| Lifetime | Blasted | First meme was this blast | Prior exactly 1 | Prior 2–5 | Prior 6+ | p50 prior sends |
|----------|--------:|--------------------------:|----------------:|----------:|---------:|----------------:|
| ever reacted | 5,048 | 0 | 0 | 14 | 5,034 | 62.5 |
| **never reacted** | **1,378** | **11** | 11 | 1,000 | 356 | **5.0** |

“Never reacted” in this blast ≠ onboarding drop-off. They already had a median **5** prior sends (reactivations). Only 11 people got today's meme as their first ever.

Earlier in the send (~11:57 UTC, ~3.1–3.4k delivered): viral LR among reactors **70.8%** (n=48) vs HQ **58.3%** (n=12). React-in-1h ~2% (dormant; live HQ baseline ~33%). Ordinary users who continued after a react: next-feed LR **56.2%** (51 users, 337 sends) — feed after push was not garbage. Two viral memes dominated (`10084067`, `10173160`) because unseen+lang → same #1 for ghosts.

**Process lesson:** blasting all 7d+ idle (including 90d+ never-reacted) was worse than A/B on 7–28d. Cadence 15m–4w stays. Extra all-idle waves should not become the default.

---

## 6. What not to “fix”

- Multi-language onboarding keyboard — already one tap for new users.
- Share skipping welcome/picker — best converting entry in 90d.
- Killing 15m/24h/48h/1w/2w/4w — rejected; habit while fresh.
- MTProto full-user scrape for language — names already used; mass scrape is ToS/flood.

## 7. Next measurements

- **2026-09-08** (T+24h blast): `broadcast-reengagement.sql` + never-reacted share of sends, block rate since 11:20Z, viral vs HQ react-in-1h.
- **2026-09-14** (T+7d): same, plus whether reactors started a second session / invited anyone.
- Re-run `onboarding-funnel.sql` when H9–H11 ship, same 90d window definition.
