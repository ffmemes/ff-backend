#!/usr/bin/env python3
"""Next-wave offline experiments for channel hit prediction.

Scorers (time walk-forward top-20% f1k lift vs v4 all-time likes):
  - v4 all-time ln(pre_likes+1)
  - source prior
  - v4 × source
  - maturity band volume / × source
  - early gem (mid sends, not burned)
  - **channel subscribers ∩ bot** pre-likes (and × source)
  - core heavy users pre-likes
  - last-7d likes (control; expected weak)

Usage:
  set -a; source .env; set +a
  python exp_next_wave.py
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
import numpy as np

ROOT = Path(__file__).resolve().parent
OUT_MD = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-next-wave.md"
OUT_HTML = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-next-wave.html"
OUT_JSON = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-next-wave.json"

RU_CHANNEL_CHAT_ID = -1001152876229
FOLDS = [(0.50, 0.15), (0.65, 0.15), (0.80, 0.15)]
PASS_DELTA = 0.05
PASS_MIN = 2


def spearman(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 30:
        return float("nan")
    ar = a[m].argsort().argsort().astype(float)
    br = b[m].argsort().argsort().astype(float)
    return float(np.corrcoef(ar, br)[0, 1])


def top20_lift(score, y) -> float:
    score, y = np.asarray(score, float), np.asarray(y, float)
    m = np.isfinite(score) & np.isfinite(y)
    score, y = score[m], y[m]
    if len(y) < 40:
        return float("nan")
    k = max(1, int(0.2 * len(y)))
    idx = np.argsort(-score)[:k]
    base = float(y.mean())
    return float(y[idx].mean() / base) if base > 0 else float("nan")


async def load(conn) -> dict:
    labs = await conn.fetch(
        """
        WITH posts AS (
          SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id,
                 m.meme_source_id
          FROM crossposting cp
          JOIN meme m ON m.id = cp.meme_id
          WHERE cp.channel = 'tgchannelru'
            AND cp.created_at > now() - interval '120 days'
            AND cp.created_at < now() - interval '36 hours'
            AND m.type = 'image'
            AND cp.telegram_message_id IS NOT NULL
        )
        SELECT DISTINCT ON (p.meme_id)
          p.meme_id, p.posted_at, p.meme_source_id,
          s.views, s.forwards,
          1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
        FROM posts p
        JOIN crossposting_snapshots s
          ON s.channel = 'tgchannelru'
         AND s.telegram_message_id = p.telegram_message_id
         AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                               AND p.posted_at + interval '36 hours'
         AND s.views > 0
        ORDER BY p.meme_id,
          abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
        """
    )
    meme_ids = [int(r["meme_id"]) for r in labs]
    posted = {int(r["meme_id"]): r["posted_at"] for r in labs}
    src = {int(r["meme_id"]): r["meme_source_id"] for r in labs}
    y_f1k = {int(r["meme_id"]): float(r["f1k"]) for r in labs}
    y_fwd = {int(r["meme_id"]): float(r["forwards"]) for r in labs}

    # source prior from labels themselves (time-safe later)
    # subscribers
    subs = await conn.fetch(
        """
        SELECT user_tg_id AS user_id
        FROM user_tg_chat_membership
        WHERE chat_id = $1
        """,
        RU_CHANNEL_CHAT_ID,
    )
    sub_set = {int(r["user_id"]) for r in subs}

    # core heavy
    core_rows = await conn.fetch(
        """
        WITH act AS (
          SELECT user_id, count(*) n
          FROM user_meme_reaction
          WHERE reacted_at > now() - interval '30 days'
          GROUP BY 1 HAVING count(*) >= 10
        ),
        thr AS (SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY n) p95 FROM act)
        SELECT a.user_id FROM act a, thr t WHERE a.n >= t.p95
        """
    )
    core_set = {int(r["user_id"]) for r in core_rows}

    # active bot users among subs
    if sub_set:
        act_subs = await conn.fetch(
            """
            SELECT DISTINCT user_id
            FROM user_meme_reaction
            WHERE reacted_at > now() - interval '30 days'
              AND user_id = ANY($1::bigint[])
            """,
            list(sub_set),
        )
        sub_active = {int(r["user_id"]) for r in act_subs}
    else:
        sub_active = set()

    # nmemes_sent at analysis time (approx; point-in-time leak mild for offline)
    stats = await conn.fetch(
        """
        SELECT meme_id, nlikes, ndislikes, nmemes_sent
        FROM meme_stats WHERE meme_id = ANY($1::int[])
        """,
        meme_ids,
    )
    nsent = {int(r["meme_id"]): int(r["nmemes_sent"] or 0) for r in stats}
    nlikes_ms = {int(r["meme_id"]): int(r["nlikes"] or 0) for r in stats}

    # reactions pre-post
    likes_all = defaultdict(int)
    likes_7d = defaultdict(int)
    likes_sub = defaultdict(int)
    likes_core = defaultdict(int)
    likes_sub_eng = defaultdict(int)
    dis_all = defaultdict(int)

    for i in range(0, len(meme_ids), 400):
        batch = meme_ids[i : i + 400]
        rows = await conn.fetch(
            """
            SELECT meme_id, user_id, reaction_id, reacted_at, sent_at
            FROM user_meme_reaction
            WHERE meme_id = ANY($1::int[])
            """,
            batch,
        )
        for r in rows:
            mid = int(r["meme_id"])
            pt = posted[mid]
            ra = r["reacted_at"]
            if ra is None or ra >= pt:
                continue
            uid = int(r["user_id"])
            if r["reaction_id"] == 2:
                dis_all[mid] += 1
                continue
            if r["reaction_id"] != 1:
                continue
            likes_all[mid] += 1
            age_d = (pt - ra).total_seconds() / 86400
            if age_d <= 7:
                likes_7d[mid] += 1
            if uid in sub_set:
                likes_sub[mid] += 1
                if r["sent_at"] is not None:
                    sec = (ra - r["sent_at"]).total_seconds()
                    if 5 <= sec <= 60:
                        likes_sub_eng[mid] += 1
            if uid in core_set:
                likes_core[mid] += 1

    # source prior f1k (leakage-safe mean of earlier posts)
    by_src = defaultdict(list)
    for mid in sorted(meme_ids, key=lambda m: posted[m]):
        by_src[src[mid]].append(mid)
    src_prior = {}
    hist = defaultdict(list)
    for mid in sorted(meme_ids, key=lambda m: posted[m]):
        s = src[mid]
        if hist[s]:
            src_prior[mid] = float(np.mean(hist[s][-20:]))  # last up to 20 prior
        else:
            src_prior[mid] = float("nan")
        hist[s].append(y_f1k[mid])

    meta = {
        "n_labeled": len(meme_ids),
        "n_channel_members_tracked": len(sub_set),
        "n_members_active_in_bot_30d": len(sub_active),
        "n_core": len(core_set),
        "pct_posts_with_sub_like": round(
            100 * sum(1 for m in meme_ids if likes_sub[m] > 0) / max(len(meme_ids), 1), 1
        ),
        "mean_sub_likes": round(float(np.mean([likes_sub[m] for m in meme_ids])), 2),
        "mean_all_likes": round(float(np.mean([likes_all[m] for m in meme_ids])), 2),
    }

    # build feature dicts mid -> score
    def ln1(x):
        return math.log(x + 1.0)

    med_src = float(np.nanmedian([src_prior[m] for m in meme_ids if np.isfinite(src_prior[m])]))

    def src_m(m):
        v = src_prior[m]
        return v if np.isfinite(v) else med_src

    def maturity_mult(likes):
        if 15 <= likes <= 120:
            return 1.15
        if likes > 200:
            return 0.85
        return 1.0

    def early_gem(m):
        # prefer not-burned: nsent 20-150 or all_likes 15-100; score by ln(likes)*lr-ish
        L = likes_all[m]
        D = dis_all[m]
        ns = nsent.get(m, 0) or (L + D)
        lr = L / (L + D + 1e-9)
        if ns < 15 or ns > 180:
            return 0.0  # hard demote burned / too cold for this scorer
        return ln1(L) * (0.5 + lr) * src_m(m)

    scores = {
        "v4_all": {m: ln1(likes_all[m]) for m in meme_ids},
        "src_prior": {m: src_m(m) for m in meme_ids},
        "v4_x_src": {m: ln1(likes_all[m]) * src_m(m) for m in meme_ids},
        "maturity": {m: ln1(likes_all[m]) * maturity_mult(likes_all[m]) for m in meme_ids},
        "maturity_x_src": {
            m: ln1(likes_all[m]) * maturity_mult(likes_all[m]) * src_m(m) for m in meme_ids
        },
        "early_gem": {m: early_gem(m) for m in meme_ids},
        "sub_likes": {m: ln1(likes_sub[m]) for m in meme_ids},
        "sub_x_src": {m: ln1(likes_sub[m]) * src_m(m) for m in meme_ids},
        "sub_engaged_x_src": {m: ln1(likes_sub_eng[m]) * src_m(m) for m in meme_ids},
        "core_likes": {m: ln1(likes_core[m]) for m in meme_ids},
        "core_x_src": {m: ln1(likes_core[m]) * src_m(m) for m in meme_ids},
        "likes_7d": {m: ln1(likes_7d[m]) for m in meme_ids},
        "likes_7d_x_src": {m: ln1(likes_7d[m]) * src_m(m) for m in meme_ids},
    }

    return {
        "meme_ids": meme_ids,
        "posted": posted,
        "y_f1k": y_f1k,
        "y_fwd": y_fwd,
        "scores": scores,
        "meta": meta,
        "likes_all": likes_all,
        "likes_sub": likes_sub,
    }


def eval_scores(data: dict) -> list[dict]:
    ids = sorted(data["meme_ids"], key=lambda m: data["posted"][m])
    n = len(ids)
    y = data["y_f1k"]
    results = []
    v4_lifts_by_fold = []

    # precompute v4 lifts per fold
    for train_frac, test_frac in FOLDS:
        tr_end = int(n * train_frac)
        te_end = min(n, tr_end + int(n * test_frac))
        test = ids[tr_end:te_end]
        if len(test) < 50:
            continue
        sc = np.array([data["scores"]["v4_all"][m] for m in test])
        yt = np.array([y[m] for m in test])
        v4_lifts_by_fold.append(top20_lift(sc, yt))

    for name, scmap in data["scores"].items():
        fold_lifts = []
        fold_sp = []
        for fi, (train_frac, test_frac) in enumerate(FOLDS):
            tr_end = int(n * train_frac)
            te_end = min(n, tr_end + int(n * test_frac))
            test = ids[tr_end:te_end]
            if len(test) < 50:
                continue
            sc = np.array([scmap[m] for m in test])
            yt = np.array([y[m] for m in test])
            fold_lifts.append(top20_lift(sc, yt))
            fold_sp.append(spearman(sc, yt))
        if not fold_lifts:
            continue
        wins = 0
        for a, b in zip(fold_lifts, v4_lifts_by_fold):
            if np.isfinite(a) and np.isfinite(b) and a >= b + PASS_DELTA:
                wins += 1
        results.append(
            {
                "name": name,
                "mean_lift": float(np.nanmean(fold_lifts)),
                "mean_spearman": float(np.nanmean(fold_sp)),
                "mean_v4_lift": float(np.nanmean(v4_lifts_by_fold)),
                "wins_vs_v4": wins,
                "n_folds": len(fold_lifts),
                "lifts": [float(x) if np.isfinite(x) else None for x in fold_lifts],
                "PASS": wins >= PASS_MIN,
            }
        )
    results.sort(key=lambda r: (-r["wins_vs_v4"], -r["mean_lift"]))
    return results


def write_reports(meta: dict, results: list[dict], online: dict) -> None:
    lines = [
        f"# Next-wave offline experiments — {datetime.now(timezone.utc).date()}",
        "",
        "## Setup",
        f"- n_labeled (24h channel): **{meta['n_labeled']}**",
        f"- Channel members tracked in bot membership table: **{meta['n_channel_members_tracked']}**",
        f"- Of them active in bot 30d: **{meta['n_members_active_in_bot_30d']}**",
        f"- Core heavy users (p95): **{meta['n_core']}**",
        f"- Posts with ≥1 sub-like pre-post: **{meta['pct_posts_with_sub_like']}%**",
        f"- Mean pre-likes all / sub: {meta['mean_all_likes']} / {meta['mean_sub_likes']}",
        "",
        "## Online v4 (context)",
        f"- {online}",
        "",
        "## Walk-forward (top20 f1k lift; PASS = ≥v4+0.05 on ≥2/3 folds)",
        "",
        "| scorer | wins | mean lift | v4 lift | ρ | PASS | per-fold |",
        "|--------|-----:|----------:|--------:|---:|:----:|----------|",
    ]
    for r in results:
        pf = ", ".join(f"{x:.2f}" if x is not None else "—" for x in r["lifts"])
        lines.append(
            f"| `{r['name']}` | {r['wins_vs_v4']}/{r['n_folds']} | {r['mean_lift']:.3f} | "
            f"{r['mean_v4_lift']:.3f} | {r['mean_spearman']:.3f} | "
            f"{'YES' if r['PASS'] else 'no'} | {pf} |"
        )
    passes = [r for r in results if r["PASS"] and r["name"] != "v4_all"]
    lines += ["", "## Verdict", ""]
    if passes:
        lines.append("**PASS:** " + ", ".join(f"`{p['name']}`" for p in passes))
    else:
        lines.append("**No scorer cleared PASS bar.** Closest by mean lift:")
        for r in results[:5]:
            lines.append(
                f"- `{r['name']}`: lift {r['mean_lift']:.3f}, wins {r['wins_vs_v4']}, ρ {r['mean_spearman']:.3f}"
            )
    lines += [
        "",
        "## Hypotheses recorded",
        "",
        "### H-sub: channel subscribers ∩ bot",
        "Likes from users in `user_tg_chat_membership` for @fastfoodmemes may proxy "
        "channel taste better than global bot likes.",
        "",
        "### H-maturity / H-early-gem / H-v4×src",
        "See table above.",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    OUT_JSON.write_text(json.dumps({"meta": meta, "online": online, "results": results}, indent=2))

    # simple HTML
    rows_html = ""
    for r in results:
        cls = "pass" if r["PASS"] else ("base" if r["name"] == "v4_all" else "")
        pill = (
            "<span class=yes>PASS</span>"
            if r["PASS"]
            else ("<span class=base>BASE</span>" if r["name"] == "v4_all" else "<span class=no>no</span>")
        )
        rows_html += (
            f"<tr class='{cls}'><td><code>{r['name']}</code></td>"
            f"<td class=n>{r['wins_vs_v4']}/{r['n_folds']}</td>"
            f"<td class=n>{r['mean_lift']:.3f}</td>"
            f"<td class=n>{r['mean_v4_lift']:.3f}</td>"
            f"<td class=n>{r['mean_spearman']:.3f}</td><td>{pill}</td></tr>"
        )
    html = f"""<!DOCTYPE html><html lang=ru><head><meta charset=utf-8>
<title>Next-wave experiments</title>
<style>
body{{font-family:system-ui;background:#0c1017;color:#e8eef7;margin:0;padding:24px}}
.wrap{{max-width:900px;margin:auto}}
.card{{background:#151c28;border:1px solid #2a3548;border-radius:12px;padding:16px;margin:12px 0}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:8px;border-bottom:1px solid #2a3548;text-align:left}}
td.n,th.n{{text-align:right}}
tr.pass td{{background:rgba(61,214,140,.08)}}
.yes{{color:#3dd68c;font-weight:700}}.no{{color:#f07178}}.base{{color:#8b9bb4}}
.muted{{color:#8b9bb4}} h1{{margin:0 0 8px}}
</style></head><body><div class=wrap>
<h1>Next-wave: maturity · gems · subscribers</h1>
<p class=muted>{datetime.now(timezone.utc).date()} · walk-forward top20 f1k lift · bar v4+0.05 on ≥2/3 folds</p>
<div class=card>
<p><b>Subs tracked:</b> {meta['n_channel_members_tracked']} ·
<b>active in bot:</b> {meta['n_members_active_in_bot_30d']} ·
<b>posts w/ sub-like:</b> {meta['pct_posts_with_sub_like']}% ·
<b>n labeled:</b> {meta['n_labeled']}</p>
<p class=muted>Online v4: {online}</p>
</div>
<div class=card>
<table><thead><tr><th>Scorer</th><th class=n>Wins</th><th class=n>Lift</th>
<th class=n>v4</th><th class=n>ρ</th><th></th></tr></thead>
<tbody>{rows_html}</tbody></table>
</div>
<div class=card>
<h3>Как читать</h3>
<ul>
<li><code>sub_*</code> = лайки от людей, которые есть в membership канала (бот знает, что они в @fastfoodmemes).</li>
<li><code>early_gem</code> = не выжатые мемы (sends 15–180) × LR × source.</li>
<li><code>maturity_*</code> = soft boost mid volume, demote super-heated.</li>
<li>PASS → кандидат в shadow decision_log; не hard pick.</li>
</ul>
</div>
</div></body></html>"""
    OUT_HTML.write_text(html)
    print("\n".join(lines))
    print(f"wrote {OUT_MD}\n{OUT_HTML}")


async def main():
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("need ANALYST_DATABASE_URL")
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        await conn.execute("SET statement_timeout = '300s'")
        online = await conn.fetchrow(
            """
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at, cp.score_version, cp.telegram_message_id
              FROM crossposting cp JOIN meme m ON m.id=cp.meme_id
              WHERE cp.channel='tgchannelru' AND m.type='image'
                AND cp.telegram_message_id IS NOT NULL
                AND cp.created_at < now()-interval '36 hours'
                AND (
                  (cp.score_version=4 AND cp.created_at > '2026-08-10')
                  OR (cp.score_version=2 AND cp.created_at > now()-interval '14 days'
                      AND cp.created_at < '2026-08-10')
                )
            ),
            snap AS (
              SELECT DISTINCT ON (p.meme_id) p.score_version, s.forwards,
                1000.0*s.forwards/nullif(s.views,0) f1k
              FROM posts p
              JOIN crossposting_snapshots s ON s.channel='tgchannelru'
               AND s.telegram_message_id=p.telegram_message_id
               AND s.snapshot_at BETWEEN p.created_at+interval '18 hours'
                                     AND p.created_at+interval '36 hours'
               AND s.views>0
              ORDER BY p.meme_id, abs(extract(epoch from (s.snapshot_at-(p.created_at+interval '24 hours'))))
            )
            SELECT score_version, count(*)::int n,
              round(avg(forwards)::numeric,2) avg_fwd,
              round(avg(f1k)::numeric,2) avg_f1k,
              round((100.0*count(*) FILTER (WHERE f1k>=30.9 OR forwards>=12)/count(*))::numeric,1) hit
            FROM snap GROUP BY 1 ORDER BY 1
            """
        )
        # fetch both rows
        onl = await conn.fetch(
            """
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at, cp.score_version, cp.telegram_message_id
              FROM crossposting cp JOIN meme m ON m.id=cp.meme_id
              WHERE cp.channel='tgchannelru' AND m.type='image'
                AND cp.telegram_message_id IS NOT NULL
                AND cp.created_at < now()-interval '36 hours'
                AND (
                  (cp.score_version=4 AND cp.created_at > '2026-08-10')
                  OR (cp.score_version=2 AND cp.created_at > now()-interval '14 days'
                      AND cp.created_at < '2026-08-10')
                )
            ),
            snap AS (
              SELECT DISTINCT ON (p.meme_id) p.score_version, s.forwards,
                1000.0*s.forwards/nullif(s.views,0) f1k
              FROM posts p
              JOIN crossposting_snapshots s ON s.channel='tgchannelru'
               AND s.telegram_message_id=p.telegram_message_id
               AND s.snapshot_at BETWEEN p.created_at+interval '18 hours'
                                     AND p.created_at+interval '36 hours'
               AND s.views>0
              ORDER BY p.meme_id, abs(extract(epoch from (s.snapshot_at-(p.created_at+interval '24 hours'))))
            )
            SELECT score_version, count(*)::int n,
              round(avg(forwards)::numeric,2) avg_fwd,
              round(avg(f1k)::numeric,2) avg_f1k,
              round((100.0*count(*) FILTER (WHERE f1k>=30.9 OR forwards>=12)/count(*))::numeric,1) hit
            FROM snap GROUP BY 1 ORDER BY 1
            """
        )
        online = {int(r["score_version"]): dict(r) for r in onl}
        online_s = f"v4 n={online.get(4,{}).get('n')} fwd={online.get(4,{}).get('avg_fwd')} f1k={online.get(4,{}).get('avg_f1k')} hit={online.get(4,{}).get('hit')}% | v2 n={online.get(2,{}).get('n')} fwd={online.get(2,{}).get('avg_fwd')} f1k={online.get(2,{}).get('avg_f1k')} hit={online.get(2,{}).get('hit')}%"

        print("loading features…")
        data = await load(conn)
        print("meta", data["meta"])
        print("evaluating…")
        results = eval_scores(data)
        write_reports(data["meta"], results, online_s)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
