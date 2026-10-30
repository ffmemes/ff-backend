"""Gates for the crosspost content-tags hypothesis (read-only).

Experiment: experiments/active/2026-10-31-crosspost-content-tags.md
Research:   docs/analyst/research/2026-10-30-forward-drivers/

Usage (analyst machine, needs pandas + statsmodels + scikit-learn):

    python docs/analyst/crossposting-content-tags-gates.py --sql > /tmp/q.sql
    psql "$ANALYST_DATABASE_URL" --csv -f /tmp/q.sql > /tmp/ru_posts.csv
    python docs/analyst/crossposting-content-tags-gates.py /tmp/ru_posts.csv

Gate A: Cohen's kappa between Describe Memes tags (meme.ocr_result) and the
        blind labels, for `relatable` and `format == tweet_screenshot`.
        Needs >= 150 overlapping meme_ids; pass if both kappas >= 0.6.
Gate B: OLS zf ~ n_flags + C(src) + lnl + nl_na + C(hour), SE clustered by week,
        on all RU posts that have model tags. n_flags = relatable + tweet, the
        same count content_mult_v1 uses. Pass if coef <= -0.05 and the 95% CI
        excludes 0.
"""

import json
import sys
from pathlib import Path

LABELS = Path(__file__).parent / "research/2026-10-30-forward-drivers/labels.jsonl"

# Same target as the study (scripts/build_posts.py): RU image posts >= 7 days old,
# zf = ln(1+forwards) - mean over the channel's ISO week (UTC).
# lnl comes from the decision-log candidate logged at pick time.
SQL = """
WITH posts AS (
    SELECT c.meme_id, c.created_at,
           to_char(c.created_at, 'IYYY-"W"IW') AS wk,
           extract(hour FROM c.created_at + interval '3 hours')::int AS hour_msk,
           m.meme_source_id AS src,
           LN(1 + c.forwards) AS lfw,
           m.ocr_result->>'format' AS model_format,
           CASE WHEN jsonb_typeof(m.ocr_result->'relatable') = 'boolean'
                THEN (m.ocr_result->>'relatable')::boolean END AS model_relatable,
           CASE WHEN jsonb_typeof(m.ocr_result->'politics_news') = 'boolean'
                THEN (m.ocr_result->>'politics_news')::boolean END AS model_politics
    FROM crossposting c
    JOIN meme m ON m.id = c.meme_id
    WHERE c.channel = 'tgchannelru'
      AND m.type = 'image'
      AND COALESCE(c.score_version, 1) <> 0
      AND c.forwards IS NOT NULL
      AND c.created_at < now() - interval '7 days'
      AND c.created_at > now() - interval '365 days'
)
SELECT p.meme_id, p.wk, p.hour_msk, p.src,
       ROUND((p.lfw - AVG(p.lfw) OVER (PARTITION BY p.wk))::numeric, 4) AS zf,
       dl.nlikes AS dl_nlikes,
       p.model_format, p.model_relatable, p.model_politics
FROM posts p
LEFT JOIN LATERAL (
    SELECT (e->>'nlikes')::int AS nlikes
    FROM crossposting_decision_log d, jsonb_array_elements(d.candidates) e
    WHERE d.channel = 'tgchannelru'
      AND d.picked_meme_id = p.meme_id
      AND (e->>'meme_id')::bigint = p.meme_id
      AND d.decided_at BETWEEN p.created_at - interval '1 day' AND p.created_at + interval '1 hour'
    ORDER BY abs(extract(epoch FROM d.decided_at - p.created_at))
    LIMIT 1
) dl ON true
ORDER BY p.created_at
"""


def main(path: str) -> None:
    import numpy as np
    import pandas as pd
    import statsmodels.formula.api as smf
    from sklearn.metrics import cohen_kappa_score

    d = pd.read_csv(path)
    d["relatable"] = d.model_relatable.map({"t": 1, "f": 0, True: 1, False: 0})
    d["tweet"] = (d.model_format == "tweet_screenshot").astype(float)
    d.loc[d.model_format.isna(), "tweet"] = np.nan
    tagged = d.dropna(subset=["relatable", "tweet"]).copy()
    print(f"RU posts: {len(d)}, with model tags: {len(tagged)}")

    # Gate A — agreement with blind labels
    lab = pd.DataFrame([json.loads(x) for x in open(LABELS)])
    lab["lab_relatable"] = lab.humor.apply(lambda h: int("relatable" in h))
    lab["lab_tweet"] = (lab.format == "tweet_screenshot").astype(int)
    j = tagged.drop_duplicates("meme_id").merge(lab, on="meme_id")
    print(f"\nGate A: overlap with blind labels n={len(j)} (need >= 150)")
    gate_a = len(j) >= 150
    for model_col, lab_col in (("relatable", "lab_relatable"), ("tweet", "lab_tweet")):
        if len(j) == 0:
            gate_a = False
            continue
        k = cohen_kappa_score(j[model_col].astype(int), j[lab_col])
        agree = (j[model_col].astype(int) == j[lab_col]).mean()
        print(
            f"  {model_col:10s} kappa={k:.2f} agree={agree:.2f} "
            f"model_rate={j[model_col].mean():.2f} label_rate={j[lab_col].mean():.2f}"
        )
        gate_a &= k >= 0.6
    print(f"  GATE A {'PASS' if gate_a else 'FAIL'}")

    # Gate B — refit on model tags
    t = tagged
    vc = t.src.value_counts()
    t["src_fe"] = t.src.where(t.src.isin(vc[vc >= 20].index)).astype("Int64").astype(str)
    t["lnl"] = np.log1p(t.dl_nlikes.fillna(t.dl_nlikes.median()))
    t["nl_na"] = t.dl_nlikes.isna().astype(int)
    t["n_flags"] = t.relatable + t.tweet
    t["politics"] = t.model_politics.map({"t": 1, "f": 0, True: 1, False: 0}).fillna(0)
    groups = pd.factorize(t.wk)[0]
    ctrl = "C(src_fe) + lnl + nl_na + C(hour_msk)"
    fit = smf.ols(f"zf ~ n_flags + {ctrl}", t).fit(cov_type="cluster", cov_kwds={"groups": groups})
    b, (lo, hi) = fit.params.n_flags, fit.conf_int().loc["n_flags"]
    print(f"\nGate B: n={len(t)} weeks={t.wk.nunique()}")
    print(f"  n_flags coef={b:.3f} 95% CI [{lo:.3f}, {hi:.3f}] p={fit.pvalues.n_flags:.3g}")
    sep = smf.ols(f"zf ~ relatable + tweet + politics + {ctrl}", t).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )
    for f in ("relatable", "tweet", "politics"):
        ci = sep.conf_int().loc[f]
        print(
            f"  (info) {f:9s} coef={sep.params[f]:.3f} [{ci[0]:.3f}, {ci[1]:.3f}] "
            f"n={int(t[f].sum())}"
        )
    gate_b = b <= -0.05 and hi < 0
    print(f"  GATE B {'PASS' if gate_b else 'FAIL'}")
    print(f"\nBOTH GATES {'PASS' if gate_a and gate_b else 'FAIL'}")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--sql":
        print(SQL.strip() + ";")
    elif len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        sys.exit(__doc__)
