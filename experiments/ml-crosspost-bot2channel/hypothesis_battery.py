#!/usr/bin/env python3
"""Offline hypothesis battery: many scorers × label modes × walk-forward.

Goal: find *any* simple signal that beats v4 on honest time folds for
"will this meme hit the channel?" — without a neural soup.

Does NOT change production. Writes:
  reports/YYYY-MM-DD-hypothesis-battery.md
  reports/YYYY-MM-DD-hypothesis-battery.html
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT_MD = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-hypothesis-battery.md"
OUT_HTML = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-hypothesis-battery.html"
OUT_JSON = ROOT / "reports" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-hypothesis-battery.json"

FOLDS = [(0.50, 0.15), (0.65, 0.15), (0.80, 0.15)]
PASS_DELTA = 0.05
PASS_MIN = 2
MIN_TEST = 60


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 15:
        return float("nan")
    ar = a[m].argsort().argsort().astype(float)
    br = b[m].argsort().argsort().astype(float)
    return float(np.corrcoef(ar, br)[0, 1])


def top20_lift(score: np.ndarray, y: np.ndarray) -> float:
    m = np.isfinite(score) & np.isfinite(y)
    score, y = score[m], y[m]
    if len(y) < 30:
        return float("nan")
    k = max(1, int(len(y) * 0.2))
    idx = np.argsort(-score)[:k]
    base = float(y.mean())
    if base <= 0:
        return float("nan")
    return float(y[idx].mean() / base)


def hit_rate_top20(score: np.ndarray, hit: np.ndarray) -> float:
    m = np.isfinite(score)
    score, hit = score[m], hit[m]
    k = max(1, int(len(score) * 0.2))
    idx = np.argsort(-score)[:k]
    return float(hit[idx].mean())


@dataclass
class Hyp:
    id: str
    name: str
    family: str  # volume | source | cohort | hybrid | maturity
    desc: str


def build_base_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Returns labels_24h, labels_life, reactions with user flags."""
    deep = pl.read_parquet(ROOT / "data" / "dataset_deep.parquet")
    # lifetime labels from deep
    life = deep.select(
        [
            "meme_id",
            "posted_at",
            "meme_source_id",
            pl.col("views_ch").alias("views"),
            pl.col("forwards_ch").alias("forwards"),
            pl.col("f1k_ch").alias("f1k"),
            pl.col("pre_likes").alias("all_pre_likes"),
            pl.col("src_prior_f1k"),
            pl.col("src_prior_n"),
        ]
    ).filter(pl.col("f1k").is_not_null() & pl.col("views").is_not_null() & (pl.col("views") > 0))

    lab24 = pl.read_parquet(RAW / "labels_24h.parquet").select(
        [
            "meme_id",
            "posted_at",
            pl.col("views_24h").alias("views"),
            pl.col("forwards_24h").alias("forwards"),
            pl.col("f1k_24h").alias("f1k"),
        ]
    )
    # attach source prior from deep when available
    lab24 = lab24.join(
        deep.select(["meme_id", "meme_source_id", "src_prior_f1k", "src_prior_n", "pre_likes"]),
        on="meme_id",
        how="left",
    ).rename({"pre_likes": "all_pre_likes"})

    reacts = pl.read_parquet(RAW / "reactions_deep.parquet")
    ut = pl.read_parquet(RAW / "users_tg_deep.parquet") if (RAW / "users_tg_deep.parquet").exists() else pl.DataFrame()
    users = pl.read_parquet(RAW / "users_deep.parquet") if (RAW / "users_deep.parquet").exists() else pl.DataFrame()

    if ut.height:
        reacts = reacts.join(ut, on="user_id", how="left")
    else:
        reacts = reacts.with_columns(pl.lit(False).alias("is_premium"))
    if users.height:
        reacts = reacts.join(users, on="user_id", how="left")
    else:
        reacts = reacts.with_columns(pl.lit("user").alias("type"))

    reacts = reacts.with_columns(
        [
            pl.col("is_premium").fill_null(False),
            (pl.col("type").is_in(["moderator", "admin"])).fill_null(False).alias("is_mod"),
            (
                (pl.col("reaction_id") == 1)
                & pl.col("sec_to_react").is_not_null()
                & (pl.col("sec_to_react") >= 5)
                & (pl.col("sec_to_react") <= 60)
            ).alias("engaged"),
            (
                (pl.col("reaction_id") == 2)
                & pl.col("sec_to_react").is_not_null()
                & (pl.col("sec_to_react") < 2)
            ).alias("instant_skip"),
        ]
    )

    # global user quality from this reaction dump
    u_stats = reacts.group_by("user_id").agg(
        [
            (pl.col("reaction_id") == 1).sum().alias("u_likes"),
            (pl.col("reaction_id") == 2).sum().alias("u_dislikes"),
            pl.len().alias("u_reacts"),
        ]
    )
    u_stats = u_stats.with_columns(
        (
            pl.col("u_likes") / (pl.col("u_likes") + pl.col("u_dislikes") + 1e-9)
        ).alias("u_lr")
    )
    # thresholds on full user population
    like_p80 = float(u_stats["u_likes"].quantile(0.80))
    like_p50 = float(u_stats["u_likes"].quantile(0.50))
    react_p20 = float(u_stats["u_reacts"].quantile(0.20))

    reacts = reacts.join(u_stats, on="user_id", how="left")
    reacts = reacts.with_columns(
        [
            (pl.col("u_likes") >= like_p80).alias("is_power"),
            (pl.col("u_likes") >= like_p50).alias("is_mid_plus"),
            (pl.col("u_reacts") <= react_p20).alias("is_rare"),
            ((pl.col("u_lr") < 0.35) & (pl.col("u_reacts") >= 20)).alias("is_hater"),
            ((pl.col("u_lr") > 0.65) & (pl.col("u_reacts") >= 20)).alias("is_lover"),
        ]
    )

    meta = {
        "like_p80": like_p80,
        "like_p50": like_p50,
        "react_p20": react_p20,
        "n_users": u_stats.height,
    }
    (ROOT / "data" / "cohort_thresholds.json").write_text(json.dumps(meta, indent=2))
    print("cohort thresholds", meta)
    return lab24, life, reacts


def pre_agg(reacts: pl.DataFrame, posts: pl.DataFrame, mask_expr) -> pl.DataFrame:
    """Aggregate pre-post likes under a user/reaction mask."""
    r = reacts.join(posts.select(["meme_id", "posted_at"]), on="meme_id", how="inner")
    r = r.filter(pl.col("reacted_at") < pl.col("posted_at"))
    r = r.filter(mask_expr)
    agg = r.group_by("meme_id").agg(
        [
            (pl.col("reaction_id") == 1).sum().alias("likes"),
            (pl.col("reaction_id") == 2).sum().alias("dislikes"),
            pl.len().alias("reacts"),
            pl.col("engaged").sum().alias("engaged_likes"),
            ((pl.col("reaction_id") == 1) & pl.col("is_premium")).sum().alias("prem_likes"),
        ]
    )
    return agg


def score_table(posts: pl.DataFrame, reacts: pl.DataFrame) -> pl.DataFrame:
    """Attach many hypothesis scores to each post row."""
    base = posts.select(
        [
            "meme_id",
            "posted_at",
            "views",
            "forwards",
            "f1k",
            "src_prior_f1k",
            "src_prior_n",
            "all_pre_likes",
        ]
    )

    masks = {
        "all": pl.lit(True),
        "likes_only": pl.col("reaction_id") == 1,
        "engaged": (pl.col("reaction_id") == 1) & pl.col("engaged"),
        "premium": (pl.col("reaction_id") == 1) & pl.col("is_premium"),
        "power": (pl.col("reaction_id") == 1) & pl.col("is_power"),
        "mid_plus": (pl.col("reaction_id") == 1) & pl.col("is_mid_plus"),
        "not_hater": (pl.col("reaction_id") == 1) & (~pl.col("is_hater")),
        "not_rare": (pl.col("reaction_id") == 1) & (~pl.col("is_rare")),
        "lover": (pl.col("reaction_id") == 1) & pl.col("is_lover"),
        "power_engaged": (pl.col("reaction_id") == 1) & pl.col("is_power") & pl.col("engaged"),
        "mod": (pl.col("reaction_id") == 1) & pl.col("is_mod"),
    }

    out = base
    for name, mask in masks.items():
        agg = pre_agg(reacts, posts, mask)
        out = out.join(
            agg.select(
                [
                    "meme_id",
                    pl.col("likes").alias(f"likes_{name}"),
                    pl.col("engaged_likes").alias(f"eng_{name}"),
                ]
            ),
            on="meme_id",
            how="left",
        )

    # fill
    like_cols = [c for c in out.columns if c.startswith("likes_")]
    out = out.with_columns([pl.col(c).fill_null(0) for c in like_cols])

    # hypothesis scores
    sp = pl.col("src_prior_f1k").fill_null(out["src_prior_f1k"].median())
    out = out.with_columns(
        [
            (pl.col("likes_all") + 1).log().alias("s_v4_all"),
            sp.alias("s_src_prior"),
            ((pl.col("likes_all") + 1).log() * sp).alias("s_v4_x_src"),
            (pl.col("likes_engaged") + 1).log().alias("s_engaged"),
            (pl.col("likes_premium") + 1).log().alias("s_premium"),
            (pl.col("likes_power") + 1).log().alias("s_power"),
            (pl.col("likes_mid_plus") + 1).log().alias("s_mid_plus"),
            (pl.col("likes_not_hater") + 1).log().alias("s_not_hater"),
            (pl.col("likes_not_rare") + 1).log().alias("s_not_rare"),
            (pl.col("likes_lover") + 1).log().alias("s_lover"),
            (pl.col("likes_power_engaged") + 1).log().alias("s_power_engaged"),
            (pl.col("likes_mod") + 1).log().alias("s_mod"),
            # hybrids
            ((pl.col("likes_power") + 1).log() * sp).alias("s_power_x_src"),
            ((pl.col("likes_engaged") + 1).log() * sp).alias("s_engaged_x_src"),
            ((pl.col("likes_not_hater") + 1).log() * sp).alias("s_clean_x_src"),
            # maturity band: boost mid volume, penalize extremes
            (
                pl.when((pl.col("likes_all") >= 15) & (pl.col("likes_all") <= 120))
                .then((pl.col("likes_all") + 1).log() * 1.15)
                .when(pl.col("likes_all") > 200)
                .then((pl.col("likes_all") + 1).log() * 0.85)
                .otherwise((pl.col("likes_all") + 1).log())
            ).alias("s_maturity_band"),
            (
                pl.when((pl.col("likes_all") >= 15) & (pl.col("likes_all") <= 120))
                .then((pl.col("likes_all") + 1).log() * sp * 1.1)
                .otherwise((pl.col("likes_all") + 1).log() * sp)
            ).alias("s_maturity_x_src"),
            # residual-ish: volume relative to source prior (avoid div0)
            (
                (pl.col("likes_all") + 1).log()
                / (sp / sp.median().clip(1.0) + 0.01)
            ).alias("s_vol_over_src"),
            # random control
            pl.lit(1.0).alias("s_random_const"),
        ]
    )
    return out


HYPS = [
    Hyp("s_v4_all", "v4 all likes", "volume", "ln(all pre likes+1) — prod-like"),
    Hyp("s_src_prior", "source prior f1k", "source", "historical same-source channel f1k"),
    Hyp("s_v4_x_src", "v4 × source", "hybrid", "volume × source prior"),
    Hyp("s_engaged", "engaged likes only", "cohort", "likes with dwell 5–60s"),
    Hyp("s_premium", "premium likers", "cohort", "Telegram Premium users only"),
    Hyp("s_power", "power users (top20% likes)", "cohort", "high-activity likers only"),
    Hyp("s_mid_plus", "mid+ users (top50%)", "cohort", "drop lowest-activity half"),
    Hyp("s_not_hater", "exclude serial haters", "cohort", "drop users with LR<0.35 & n≥20"),
    Hyp("s_not_rare", "exclude rare users", "cohort", "drop bottom 20% by react count"),
    Hyp("s_lover", "super-lovers only", "cohort", "users LR>0.65 & n≥20"),
    Hyp("s_power_engaged", "power × engaged", "cohort", "power users + dwell window"),
    Hyp("s_mod", "mods/admins only", "cohort", "internal raters (sparse)"),
    Hyp("s_power_x_src", "power × source", "hybrid", "power volume × source"),
    Hyp("s_engaged_x_src", "engaged × source", "hybrid", "engaged × source"),
    Hyp("s_clean_x_src", "no-haters × source", "hybrid", "clean volume × source"),
    Hyp("s_maturity_band", "maturity band volume", "maturity", "boost mid 15–120 likes, soft demote >200"),
    Hyp("s_maturity_x_src", "maturity × source", "hybrid", "band × source"),
    Hyp("s_vol_over_src", "volume / source scale", "hybrid", "ln(likes) adjusted by prior"),
]


def eval_label_mode(df: pl.DataFrame, label_name: str) -> list[dict]:
    df = df.filter(pl.col("f1k").is_not_null()).sort("posted_at")
    # need some bot signal for volume hyps fairness
    df = df.filter(pl.col("likes_all").fill_null(0) >= 3)
    n = df.height
    results = []
    if n < 200:
        print(f"skip {label_name}: n={n}")
        return results

    for h in HYPS:
        if h.id not in df.columns:
            continue
        fold_lifts = []
        fold_sp = []
        fold_hit = []
        for train_frac, test_frac in FOLDS:
            tr_end = int(n * train_frac)
            te_end = min(n, tr_end + int(n * test_frac))
            train = df.slice(0, tr_end)
            test = df.slice(tr_end, te_end - tr_end)
            if test.height < MIN_TEST or train.height < MIN_TEST:
                continue
            y_tr = train["f1k"].to_numpy().astype(float)
            y_te = test["f1k"].to_numpy().astype(float)
            p75 = float(np.nanpercentile(y_tr, 75))
            hit_te = (y_te >= p75).astype(float)
            score = test[h.id].to_numpy().astype(float)
            # nan score → median
            med = np.nanmedian(score) if np.isfinite(score).any() else 0.0
            score = np.where(np.isfinite(score), score, med)
            fold_lifts.append(top20_lift(score, y_te))
            fold_sp.append(spearman(score, y_te))
            fold_hit.append(hit_rate_top20(score, hit_te))

        if not fold_lifts:
            continue
        # v4 baseline lifts same folds
        v4_lifts = []
        for train_frac, test_frac in FOLDS:
            tr_end = int(n * train_frac)
            te_end = min(n, tr_end + int(n * test_frac))
            train = df.slice(0, tr_end)
            test = df.slice(tr_end, te_end - tr_end)
            if test.height < MIN_TEST:
                continue
            y_te = test["f1k"].to_numpy().astype(float)
            score = test["s_v4_all"].to_numpy().astype(float)
            med = np.nanmedian(score) if np.isfinite(score).any() else 0.0
            score = np.where(np.isfinite(score), score, med)
            v4_lifts.append(top20_lift(score, y_te))

        wins = 0
        for a, b in zip(fold_lifts, v4_lifts):
            if np.isfinite(a) and np.isfinite(b) and a >= b + PASS_DELTA:
                wins += 1
        results.append(
            {
                "label": label_name,
                "id": h.id,
                "name": h.name,
                "family": h.family,
                "desc": h.desc,
                "n": n,
                "n_folds": len(fold_lifts),
                "mean_lift": float(np.nanmean(fold_lifts)),
                "mean_spearman": float(np.nanmean(fold_sp)),
                "mean_hit_top20": float(np.nanmean(fold_hit)),
                "mean_v4_lift": float(np.nanmean(v4_lifts)),
                "wins_vs_v4": wins,
                "lifts": [float(x) if np.isfinite(x) else None for x in fold_lifts],
                "PASS": wins >= PASS_MIN,
            }
        )
    return results


def write_html(rows: list[dict], path: Path) -> None:
    # sort by wins then mean_lift within label
    def rows_for(label: str) -> list[dict]:
        r = [x for x in rows if x["label"] == label]
        r.sort(key=lambda x: (-x["wins_vs_v4"], -x["mean_lift"]))
        return r

    def table(label: str) -> str:
        r = rows_for(label)
        if not r:
            return f"<p class='muted'>No rows for {label}</p>"
        trs = []
        for x in r:
            cls = "pass" if x["PASS"] else ("base" if x["id"] == "s_v4_all" else "")
            pill = (
                "<span class='pill yes'>PASS</span>"
                if x["PASS"]
                else (
                    "<span class='pill base'>BASE</span>"
                    if x["id"] == "s_v4_all"
                    else "<span class='pill no'>no</span>"
                )
            )
            lifts = ", ".join(f"{v:.2f}" if v is not None else "—" for v in x["lifts"])
            trs.append(
                f"<tr class='{cls}'><td>{x['name']}</td><td class='fam'>{x['family']}</td>"
                f"<td class='n'>{x['wins_vs_v4']}/{x['n_folds']}</td>"
                f"<td class='n'>{x['mean_lift']:.3f}</td>"
                f"<td class='n'>{x['mean_v4_lift']:.3f}</td>"
                f"<td class='n'>{x['mean_spearman']:.3f}</td>"
                f"<td class='n'>{x['mean_hit_top20']:.3f}</td>"
                f"<td class='tiny'>{lifts}</td><td>{pill}</td></tr>"
            )
        return (
            "<table><thead><tr><th>Hypothesis</th><th>Family</th><th class='n'>Wins vs v4</th>"
            "<th class='n'>Mean lift</th><th class='n'>v4 lift</th><th class='n'>ρ</th>"
            "<th class='n'>HIT@top20</th><th>Per-fold lift</th><th></th></tr></thead><tbody>"
            + "".join(trs)
            + "</tbody></table>"
        )

    passes = [x for x in rows if x["PASS"] and x["id"] != "s_v4_all"]
    pass_html = (
        "<ul>"
        + "".join(
            f"<li><b>{p['label']}</b>: {p['name']} — wins {p['wins_vs_v4']}/{p['n_folds']}, "
            f"lift {p['mean_lift']:.3f} vs v4 {p['mean_v4_lift']:.3f}</li>"
            for p in sorted(passes, key=lambda z: (-z["wins_vs_v4"], -z["mean_lift"]))
        )
        + "</ul>"
        if passes
        else "<p><b>Ни одна гипотеза не прошла bar на walk-forward.</b> "
        "Но ranking table всё равно показывает, что ближе к цели.</p>"
    )

    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Hypothesis battery · bot→channel</title>
<style>
:root {{ --bg:#0c1017; --card:#151c28; --text:#e8eef7; --muted:#8b9bb4; --line:#2a3548;
--good:#3dd68c; --bad:#f07178; --accent:#6cb6ff; --warn:#e6c07b; }}
body {{ margin:0; font-family:Segoe UI,system-ui,sans-serif; background:var(--bg); color:var(--text); line-height:1.5; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:28px 16px 64px; }}
h1 {{ margin:0 0 8px; font-size:1.6rem; }}
h2 {{ margin:24px 0 10px; font-size:1.15rem; color:var(--accent); }}
.sub {{ color:var(--muted); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 20px; margin-top:14px; }}
table {{ width:100%; border-collapse:collapse; font-size:0.82rem; }}
th,td {{ padding:7px 8px; border-bottom:1px solid var(--line); text-align:left; }}
th {{ color:var(--muted); font-size:0.68rem; text-transform:uppercase; }}
td.n, th.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
td.tiny {{ font-size:0.75rem; color:var(--muted); }}
td.fam {{ color:var(--muted); font-size:0.78rem; }}
tr.pass td {{ background:rgba(61,214,140,.08); }}
tr.base td {{ color:var(--muted); }}
.pill {{ padding:2px 8px; border-radius:6px; font-size:0.72rem; font-weight:700; }}
.pill.yes {{ background:rgba(61,214,140,.2); color:var(--good); }}
.pill.no {{ background:rgba(240,113,120,.15); color:var(--bad); }}
.pill.base {{ background:#1e2838; color:var(--muted); }}
.badge {{ display:inline-block; padding:4px 10px; border-radius:999px; font-size:0.78rem; margin:4px 4px 0 0;
 border:1px solid var(--line); }}
.badge.ok {{ color:var(--good); border-color:rgba(61,214,140,.4); }}
.badge.no {{ color:var(--bad); border-color:rgba(240,113,120,.4); }}
ul {{ margin:8px 0; padding-left:1.2rem; }}
code {{ background:#1e2838; padding:1px 5px; border-radius:4px; }}
</style></head><body><div class="wrap">
<h1>Батарея гипотез: стрельнёт ли мем в канале?</h1>
<p class="sub">Walk-forward · top-20% lift f1k · bar: ≥ v4+0.05 на ≥2/3 фолдах · {datetime.now(timezone.utc).date()}</p>
<span class="badge">{"PASS ×"+str(len(passes)) if passes else "0 PASS"}</span>
<span class="badge">{" ".join(sorted({r['label'] for r in rows}))}</span>
<span class="badge">{len(HYPS)} scorers</span>

<div class="card">
<h2>Зачем это, а не «миллиард агентов»</h2>
<ul>
<li>Один датасет, <b>одни фолды</b>, много <b>фальсифицируемых</b> scorers — сравнимо.</li>
<li>Когорты = кто шумит: haters, rare users, cold users vs power/engaged/premium.</li>
<li>Сначала offline PASS → потом shadow в decision_log → canary soft boost → тюнинг.</li>
<li>Lifetime: f1k top-quartile (rate). Lifetime и 24h — <b>разные задачи</b>.</li>
</ul>
</div>

<div class="card">
<h2>Кто прошёл bar</h2>
{pass_html}
</div>

<div class="card">
<h2>Label: 24h snaps (early virality) · n≈{next((r['n'] for r in rows if r['label']=='24h'), '?')}</h2>
{table('24h')}
</div>

<div class="card">
<h2>Label: lifetime Telethon (long horizon) · n≈{next((r['n'] for r in rows if r['label']=='lifetime'), '?')}</h2>
{table('lifetime')}
</div>

<div class="card">
<h2>Как читать → что в прод</h2>
<ol>
<li><b>PASS offline</b> → shadow score в <code>decision_log</code> (не меняет pick).</li>
<li>14 дней: corr(score, 24h f1k) + lift на реальных постах.</li>
<li>Canary: soft multiply (cap) на 10–20% слотов / kill switch env.</li>
<li>Тюнинг только на shadow-метриках, не на «ощущениях».</li>
<li>Если PASS только на lifetime, а кросспост оптимизирует 24h — <b>не шипить</b>.</li>
</ol>
</div>
<footer class="sub" style="margin-top:24px;text-align:center">hypothesis_battery.py · offline only</footer>
</div></body></html>"""
    path.write_text(html)


def main() -> None:
    lab24, life, reacts = build_base_frames()
    print("labels 24h", lab24.height, "life", life.height, "reacts", reacts.height)

    print("scoring 24h…")
    s24 = score_table(lab24, reacts)
    print("scoring lifetime…")
    slife = score_table(life, reacts)

    rows: list[dict] = []
    rows += eval_label_mode(s24, "24h")
    rows += eval_label_mode(slife, "lifetime")

    # markdown
    lines = [
        f"# Hypothesis battery {datetime.now(timezone.utc).date()}",
        "",
        f"Bar: top20 f1k lift ≥ v4 + {PASS_DELTA} on ≥{PASS_MIN}/3 folds.",
        "",
        "| label | id | name | wins | mean_lift | v4_lift | ρ | PASS |",
        "|-------|----|------|-----:|----------:|--------:|---:|:----:|",
    ]
    for r in sorted(rows, key=lambda x: (x["label"], -x["wins_vs_v4"], -x["mean_lift"])):
        lines.append(
            f"| {r['label']} | `{r['id']}` | {r['name']} | {r['wins_vs_v4']}/{r['n_folds']} | "
            f"{r['mean_lift']:.3f} | {r['mean_v4_lift']:.3f} | {r['mean_spearman']:.3f} | "
            f"{'YES' if r['PASS'] else 'no'} |"
        )
    passes = [r for r in rows if r["PASS"] and r["id"] != "s_v4_all"]
    lines += ["", "## PASS list", ""]
    if passes:
        for p in passes:
            lines.append(
                f"- **{p['label']}** / {p['name']}: wins {p['wins_vs_v4']}, lift {p['mean_lift']:.3f}"
            )
    else:
        lines.append("- (none cleared bar)")
        # top 3 per label by mean_lift
        lines += ["", "## Closest (by mean lift)", ""]
        for lab in ("24h", "lifetime"):
            cand = sorted(
                [r for r in rows if r["label"] == lab],
                key=lambda x: -x["mean_lift"],
            )[:5]
            lines.append(f"### {lab}")
            for c in cand:
                lines.append(
                    f"- {c['name']}: lift {c['mean_lift']:.3f}, wins {c['wins_vs_v4']}, ρ {c['mean_spearman']:.3f}"
                )

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    OUT_JSON.write_text(json.dumps(rows, indent=2))
    write_html(rows, OUT_HTML)
    print("\n".join(lines))
    print(f"\nwrote {OUT_MD}\nwrote {OUT_HTML}")


if __name__ == "__main__":
    main()
