# Offline: meme-level bot features × RU channel 24h labels

**When:** 2026-08-09  
**Channel:** `tgchannelru` (@fastfoodmemes)  
**Sample:** image posts, last **120d**, mature 24h snapshot (18–36h window)  
**n = 611** labeled posts  

Method: timestamp-safe features only (`reacted_at` / deep_link `created_at` **&lt; posted_at**).  
Source prior = mean channel signal of **prior** same-source posts in last 30d  
(`forwards * sqrt(views/100)` and avg f1k/fwd).  
Residual = outcome − source prior mean (within-source re-rank question).

Reproduce: analyst DB + ad-hoc Python (see appendix) or re-run logic below.

---

## Labels (how to measure performance)

| Metric | p25 | p50 | p75 | p90 |
|--------|-----|-----|-----|-----|
| **fwd_per_1k_24h** | 16.3 | **23.3** | **30.9** | 38.3 |
| **forwards_24h** | 6 | **8** | **11** | 14 |

**Recommended hit definition (rolling, not fixed forever):**

```text
HIT  = fwd_per_1k_24h >= channel_p75_120d   (~31 today)
    OR forwards_24h   >= 12
MISS = fwd_per_1k_24h <  p25 (~16) AND forwards_24h < 6
```

Hit rate under this rule on sample: **164/611 = 26.8%** (close to “top quartile” intent).

**Do not use a single absolute “shares &gt; X”** without views: 8 forwards on 200 views ≠ 8 on 500 views. Prefer **dual rule** (rate **or** abs).

Weekly ranker north star:

```text
hit_rate_24h = % posts with HIT
secondary: mean forwards_24h, mean views_24h (guardrail)
growth: sc_ unique users / week (funnel, separate)
```

---

## Coverage (critical)

| Feature | Coverage |
|---------|----------|
| Pre-post bot reactions ≥5 | **100%** (avg **100** rx/meme, **55** likes) |
| Pre-post bot reactions ≥20 | **83%** |
| Pre-share users &gt;0 (m_/s_ non-self) | **2.6%** (16 posts) |
| Source prior ≥3 prior posts | **90%** |

**Implication:** meme-level **bot engagement is dense** on channel candidates.  
Exact-meme in-bot share is still **too sparse** as a primary rank term (confirms May 22 correction).

---

## Correlations (Spearman)

| Feature | vs f1k | vs forwards | vs **resid_f1k** | vs **resid_fwd** |
|---------|--------|-------------|------------------|------------------|
| source_signal | 0.13 | 0.16 | −0.20 | −0.25 |
| source_avg_f1k | **0.20** | 0.19 | −0.18 | −0.17 |
| **pre_lr** (bot) | **0.04** | 0.07 | **0.03** | 0.03 |
| **pre_likes** | 0.12 | 0.08 | **0.16** | **0.16** |
| **pre_engaged_likes** (like, 5–60s) | **0.17** | 0.14 | **0.20** | **0.20** |
| pre_instant_skip_rate | −0.05 | −0.04 | −0.07 | −0.06 |
| pre_share_users | 0.13 | 0.14 | 0.15 | 0.16 |
| caption present | −0.04 | −0.03 | −0.06 | −0.06 |

### Read

1. **Like rate in the bot does NOT predict channel virality** (again). Quintiles of `pre_lr` are flat (~23–25 f1k).
2. **Volume of pre-post likes / engaged likes does** — including **after controlling for source** (residual spearman ~0.16–0.20). That is the meme-within-source signal.
3. Source prior remains the floor; alone it is weak positive (~0.15–0.20).
4. Instant-skip rate is weakly negative residual — directionally H-cp3, not ship-grade alone.
5. Pre-share users correlate mildly but **2.6% coverage** → boost only when &gt;0, not main score.

---

## Top-20% lift (full 120d, label-neutral ties)

Target = **forwards_24h** (absolute growth of shares):

| Score | n | lift (top20 / mean) | top mean fwd |
|-------|---|---------------------|--------------|
| source_signal | 579 | 1.09 | 9.7 |
| source_avg_f1k | 579 | 1.10 | 9.7 |
| pre_lr | 611 | 1.05 | 9.2 |
| pre_likes | 611 | 1.08 | 9.5 |
| **hybrid: src × log1p(pre_likes)** | 579 | **1.14** | **10.1** |
| hybrid: src × (0.5+pre_lr) | 579 | 1.09 | 9.7 |
| hybrid: src × share boost | 579 | 1.12 | 10.0 |
| hybrid full (+lr+share+caption) | 579 | 1.10 | 9.7 |

Target = **f1k**: best again **src × log1p(pre_likes)** lift **1.14**.

### Time split (train before 2026-07-05, test n≈180)

| Score | Test lift on forwards |
|-------|------------------------|
| source_signal | **0.93** (top20 *worse* than mean — overfit / drift) |
| pre_lr | 1.14 |
| hybrid src×lr | 1.01 |
| **hybrid src×log1p(likes)** | **1.14** (top≈10.2 vs all≈9.0) |

**This is the money result:** on held-out time, pure source prior fails; **source × meme like-volume** still lifts ~14% absolute forwards in top quintile.

---

## Hypothesis verdicts

| ID | Claim | Verdict |
|----|--------|---------|
| H-cp1 | Meme-level bot signals beat source-only for channel forwards | **Partial PASS** — volume/engaged likes yes; **LR no** |
| H-cp2 | Pre-share users help | **Weak / sparse** — keep as optional boost only |
| H-cp3 | Instant-skip hurts channel | **Weak negative** — log only / tiny weight |
| H-cp4 | Threshold policy | Use **p75 f1k≈31 or fwd≥12** as HIT; floor optional later |
| Superuser / LR-based meme rank | | **REJECT** again |

---

## What to build next (not ship full ML yet)

### Ship-shaped v2.1 / v3 candidate (RU only)

```text
score =
  source_forward_prior          # existing
  * log1p(pre_post_likes)       # NEW meme-level, timestamp-safe
  * (1 + 0.15 * min(pre_share_users, 5))   # optional, mostly no-op
  * caption_guard               # keep mild penalty
  * diversity / image / nlikes floors
```

Prefer **pre_likes** (or engaged likes) over **pre_lr**.  
`invited_count` all-time in v2 is a cousin of like-volume but less clean; replacing with timestamp-safe pre_likes is the offline-justified move.

### Offline gate before cron

- Time-split top-20% lift on forwards ≥ **+10%** vs source-only (already ~14% on this run — recheck after implementation shadow).  
- No views drop &gt;15%.  
- Empty slot rate unchanged.

### ML later

Only if residual models (ridge on eng_likes + inst_skip + share) beat **src × log1p(likes)** by ≥5% lift on a fresh split. Sample n=611 is small; don’t start with deep models.

### Funnel (parallel)

Channel HIT rate can rise without subs if `sc_` dead — track `sc_` users/week separately.

---

## Appendix: feature definitions

```text
pre_likes          = # reaction_id=1 with reacted_at < posted_at
pre_skips          = # reaction_id=2 with reacted_at < posted_at
pre_lr             = pre_likes / (pre_likes+pre_skips)
pre_engaged_likes  = likes with sec_to_react in [5, 60]
pre_instant_skips  = skips with sec_to_react in [0, 2]
pre_share_users    = distinct non-self m_/s_ clickers before posted_at
source_signal      = mean over prior same-source posts:
                     forwards_24h * sqrt(views_24h/100)
resid_*            = outcome - source_avg_*
```

Labels from `crossposting_snapshots` nearest to posted_at+24h in [+18h, +36h].
