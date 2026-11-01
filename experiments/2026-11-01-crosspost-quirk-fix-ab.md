---
id: crosspost_quirk_fix_ab
status: running
hypothesis: Fixing the two crosspost scoring quirks (impression penalty 0 instead of 0.8 RU / 0.5 EN; x0.5 instead of x1.0 for sources without history) lets better memes reach the channels and raises forwards per post
primary_metric: mean zf (fix - control) per channel, 95% CI
guardrails: avg views per post not lower than control; no posting gaps
unit: channel_post (random arm per decision, 50/50)
variants: control (RU v4 / EN v2, score_version 4 / 2); fix (RU v4q / EN v2q, score_version 9 / 8)
started: 2026-11-01
check_on: 2026-11-28
decided: 
result: unknown
learning: 
code: src/crossposting/scoring.py (AB_ARMS, impr_factor_q, src_quality_q)
readout: docs/analyst/crossposting-quirk-fix-ab.sql
---

# Experiment: Crosspost scoring quirk fix (live A/B)

- **Created:** 2026-11-01
- **Why:** the 2026-11-01 scoring refactor (#392) found two behaviours nobody chose:
  1. `impr_penalty` was bound as an integer, so it has always been 0, not 0.8 (RU) / 0.5 (EN).
     Memes outside the top quartile of their source (`raw_impr_rank > 1`) can never be posted.
  2. `GREATEST(0.5, NULL)` gives sources without enough history x0.5, not a neutral x1.0.
- **Design:** each crosspost decision picks control or fix at random (`AB_ARMS`), and that score
  does both the top-N preselect and the final pick. Both fixes ship together in one arm:
  at ~5.5 posts/day per channel a 2x2 would have ~35 posts per cell by the check date.
- **Power:** ~75 posts per arm per channel by 2026-11-28; only a large effect will show.
  If the CI still spans 0, decide on `changed_pct` and views: no harm → keep the fix (it is
  the intended behaviour), harm → revert.
- **Overlap:** v5f shadow (`crosspost_src_fwd_v5f`) is log-only and still ranks within whichever
  top-N the arm preselected. Its Spearman readout pools both arms.
- **End the test:** remove the channel from `AB_ARMS`, then set `LIVE`/`PRESELECT` to the winner.
