# Experiment: Crosspost content tags (relatable / tweet screenshot)

- **Created:** 2026-10-31
- **Status:** active. Tags are collected and a shadow score is logged; the production pick is unchanged.
- **Channels:** `tgchannelru` decides. `tgchannelen` is logged for reference only.
- **Check date:** **2026-11-20**
- **Research:** [`docs/analyst/research/2026-10-30-forward-drivers/`](../../docs/analyst/research/2026-10-30-forward-drivers/README.md)
- **Gates:** [`docs/analyst/crossposting-content-tags-gates.py`](../../docs/analyst/crossposting-content-tags-gates.py)
- **Shadow readout:** [`docs/analyst/crossposting-content-tags-shadow.sql`](../../docs/analyst/crossposting-content-tags-shadow.sql)

## Evidence

We blind-labeled 870 RU posts (25 weeks). The single-feature screen controlled for
source, ln(1+nlikes), hour and age:

- relatable joke: −0.11 zf;
- tweet or Threads screenshot: −0.10 zf.

Both survive BH correction over 55 features and a train/test time split. Adding both to a
source + likes baseline lifts test Spearman from 0.01 to 0.24. politics_news has
+0.19 zf (n=57) and is logged only.

## Hypothesis

Relatable everyday jokes and tweet screenshots get about 8–10% fewer forwards on the RU
channel, at equal source and bot likes. Down-weighting them should raise forwards per post.

## What shipped

- Describe Memes asks for three more fields and stores them in `meme.ocr_result`:
  - `format`: one of single_caption, multi_panel, tweet_screenshot, chat_screenshot, photo_no_text, drawing_comic, other;
  - `relatable`: bool;
  - `politics_news`: bool.

  Invalid values are stored as null.
- Each candidate in `crossposting_decision_log.candidates[]` gets these fields (RU and EN):
  - `content_format`, `relatable`, `politics_news`;
  - `content_mult_v1 = 0.85 ** (relatable + tweet_screenshot)`, or 1.0 when the tags are missing;
  - `score_v5c = score_v5 * content_mult_v1`;
  - `shadow_v5c_rank` and `shadow_v5c_pick_meme_id`.

## Gates (run once the backfill covers ≥150 blind-labeled memes)

- **A:** κ(model tag, blind label) ≥ 0.6 for both `relatable` and `tweet_screenshot`, on
  at least 150 overlapping memes.
- **B:** refit `zf ~ n_flags + C(src) + lnl + nl_na + C(hour)` on the model's tags over all
  RU posts that have tags, with SE clustered by week. Pass if the coefficient is ≤ −0.05
  and its 95% CI excludes 0. The blind labels give −0.092 [−0.127, −0.056].

## Decision rule (frozen 2026-10-31)

| Outcome | Action |
|---------|--------|
| A and B pass | Make `score_v5c` the live RU pick multiplier. Monitor for 8 weeks (about 280 posts). Roll back if the refit coefficient on the new posts is > 0 |
| A fails | The free-model tags are too noisy. Keep logging, try a prompt revision, then re-run A |
| B fails while A passes | Kill: the effect does not carry over to the model's tags. Remove the multiplier fields |

Also report `crossposting-content-tags-shadow.sql`:
`corr_v5c − corr_v5`, `tagged_pct`, and `zf_flagged` against `zf_clean`.

## Metrics after

_(fill on 2026-11-20)_
