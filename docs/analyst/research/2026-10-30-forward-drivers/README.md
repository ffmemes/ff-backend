# RU channel: what content gets forwarded (blind-label study, 2026-10-30)

Question: at equal source and bot like volume, which content traits predict forwards on
the RU crosspost channel (`tgchannelru`)?

Result: two traits predict **fewer** forwards: a relatable everyday joke and a tweet or
Threads screenshot. Each one costs about −0.1 zf. Political or news memes get **more**
forwards (+0.19 zf), but only 57 posts have that label, so we log it and do not use it.

Experiment: [`experiments/2026-10-31-crosspost-content-tags.md`](../../../../experiments/2026-10-31-crosspost-content-tags.md).

## Data and method

- **Sample:** 870 RU image posts from ISO weeks 2026-W19 to W43 (25 weeks). Each post was at least 7 days old and had a forward count.
- **Target:** `zf = ln(1+forwards) − mean over the channel's ISO week`. `hit` is the top quartile of zf within the week.
- **Blind labels:** vision LLM labelers saw only the image. They did not see forwards, source or date. They followed [`codebook.md`](codebook.md) and wrote `labels.jsonl`, one row per meme.
- **Second labeler:** a different labeler independently labeled 60 of the images (`labels_overlap.jsonl`).
- **Controls:**
  - source fixed effect: sources with at least 20 posts in the sample, others pooled;
  - `lnl = ln(1 + nlikes)`, logged in the decision log at pick time;
  - MSK posting hour;
  - meme age bucket.
- **Standard errors:** clustered by week.

Pipeline: `scripts/posts.sql` → `scripts/build_posts.py` (adds zf and hit, writes posts.tsv)
→ `qa.py`, `qa_swap.py` → `analyze.py` → `robust.py`, `screen.py`, `timesplit2.py`.
Set `DATA_DIR` to the folder that holds `posts.tsv`. The analysis reads `../labels.jsonl`.
`posts.tsv` is not committed because it contains uploader identifiers. The QA scripts ran
on the raw label batches, before the swap fixes. Re-running `analyze.py` and
`timesplit2.py` with the committed labels reproduces every label-based number below.

## Label QA

- **Alignment check:** we compared each label's `desc` with the stored Describe Memes
  description and OCR. 403 of 870 rows had text to compare. Language and text-length
  conflicts appeared in 0–1 rows per file.
- **Swap fix:** we found 5 pairs of adjacent label swaps (10 rows) and confirmed each by
  viewing the images. `labels.jsonl` has them fixed. The estimated undetected swap rate
  is about 1.2–1.6%.
- **Spot check:** in 20 random and low-overlap rows, the label described the image every time.
- **Dropped field:** `foreign_watermark` is removed. One batch marked our own watermark as foreign.

Agreement between the two labelers (n=60):

| field | κ |
|-------|---|
| format | 0.74 |
| tweet_screenshot (binary) | 0.87 |
| relatable (binary) | 0.71 |
| politics_news (binary) | 1.0, with only 4 positives |
| timely | 0.85 |
| valence | 0.49 |

The two labelers' `forward_score` guesses agreed (Spearman 0.73). These guesses did not
predict real forwards: Spearman with zf was −0.05.

## Results

Single-feature screen with controls. BH correction is over 55 label features.

| feature | n | Δzf | 95% CI | BH q |
|---------|---|-----|--------|------|
| politics_news topic | 57 | **+0.19** | [+0.11, +0.26] | <0.001 |
| humor = relatable | 358 | **−0.11** | [−0.16, −0.06] | <0.001 |
| needs_context | 216 | +0.10 | [+0.04, +0.15] | 0.010 |
| format = tweet_screenshot | 263 | **−0.10** | [−0.16, −0.04] | 0.020 |
| format = single_caption | 339 | +0.08 | [+0.03, +0.12] | 0.022 |
| labeler forward_score (1–5) | 870 | −0.02 | [−0.07, +0.02] | 0.52 |

Robustness of the per-feature OLS effect:

| feature | train | test | v2 regime | v4 regime |
|---------|-------|------|-----------|-----------|
| tweet_screenshot | −0.055 | −0.181 | −0.058 | −0.138 |
| politics_news | +0.177 | +0.239 | +0.177 | +0.215 |

- In this model the tweet effect holds in both periods and both score regimes.
- Tweet screenshots also do worse inside 8 of 9 sources.
- The relatable effect holds in the time split below.

Time split: train on weeks up to 2026-W36 (n=659), test on the last 7 weeks (n=211).
The models are ridge regressions. The "≈v4" baseline uses source plus `lnl`.
Δ CIs come from a week-block bootstrap.

| model | test Spearman | ΔSpearman 95% CI |
|-------|---------------|------------------|
| base (src + lnl ≈ v4) | 0.01 | — |
| + relatable | 0.20 | [+0.03, +0.31] |
| + tweet | 0.16 | [+0.06, +0.20] |
| + relatable + tweet | **0.24** | [+0.07, +0.35] |
| + relatable + tweet + politics | 0.26 | [+0.08, +0.38] |

Top-20% hit lift is too noisy to judge: about 6 posts per week over 7 test weeks, and
every CI spans 0.

Refit on the same blind labels with the Gate B specification below:
n_flags coefficient −0.092, 95% CI [−0.127, −0.056].

Limits:
- We only see memes that were posted, not the whole candidate pool.
- Freshness is confounded with score regime. Under v2 the channel posted fresh memes;
  under v4 it posted old ones.

## Hypothesis

**H:** on the RU channel, relatable everyday jokes and tweet or Threads screenshots get
about 8–10% fewer forwards each, at equal source and bot likes.

Production proxy:

```
content_mult_v1 = 0.85 ** (relatable + (format == 'tweet_screenshot'))   # missing tags → 1.0
score_v5c       = score_v5 * content_mult_v1
```

0.85 comes from −0.08 zf divided by the `lnl` coefficient (0.10 per ln-unit), which is
about −0.8 on ln(nlikes+1) of about 5.

Tags come from Describe Memes. It adds `format`, `relatable` and `politics_news` to
`meme.ocr_result`. A shadow score is logged in the decision log for RU and EN.

## Decision rule

1. Backfill the tags on the already-posted RU memes. The daily free budget covers this.
2. Run [`../../crossposting-content-tags-gates.py`](../../crossposting-content-tags-gates.py):
   - **Gate A:** free-model tags must agree with the blind labels at κ ≥ 0.6 for both `relatable` and `tweet_screenshot`, on at least 150 overlapping memes.
   - **Gate B:** refit `zf ~ n_flags + C(src) + lnl + C(hour)` on the model's tags. The coefficient must be ≤ −0.05 with a 95% CI that excludes 0.
3. If both gates pass, make `score_v5c` the live RU pick multiplier and monitor for 8 weeks
   (about 280 posts). Roll back if the refit coefficient on the new posts is > 0.
4. A purely prospective test would need about 600 posts (about 4 months), so shadow-only
   logging is too slow to be the main gate.
