# Data scale: why 624, and what Telethon adds

**Date:** 2026-08-11

## Why the first lab had n=624

Not “the whole channel” — a **strict filter stack**:

| Filter | Effect |
|--------|--------|
| Rows in `crossposting` for `tgchannelru` | ~4287 total (since 2024) |
| + image + has telegram_message_id | ~3885 |
| + **18–36h snapshot** for true 24h label | **~625** only |

Dense 24h snaps exist mostly where the collector ran well (recent period). Older posts often have **live** `views`/`forwards` on `crossposting` but no snap in the 18–36h window → dropped from “24h” lab.

## DB-only expansion (no Telethon)

| Label mode | n |
|------------|--:|
| 24h snaps | **625** |
| **lifetime** (live columns, all history) | **3877** |

`export_raw.py --days 0` + `build_dataset.py --label-mode lifetime` → **n=3877**.

Walk-forward on lifetime (2026-08-11 re-run): **no model PASS** vs v4 (lift bar). Different target (lifetime vs 24h) + distribution shift; do not over-read as “ML failed forever”.

## Telethon full channel crawl

Script: `export_channel_telethon.py`  
Session: `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` + `TELEGRAM_SESSION_STRING` (same as stats_collector / zshrc).

| Metric | Value |
|--------|------:|
| Messages fetched | **11 928** (2019-07 → 2026-08) |
| With views | 11 915 |
| Joinable via `start=sc_{meme_id}_…` | **4897** |
| Already in `crossposting` | 3823 |
| **Only Telethon (new vs DB table)** | **1072** |
| Only DB, not in crawl join | 62 |

**Join rule (as you said):**  
parse caption/entities for `sc_<meme_id>`; if no deeplink → **cannot** link to bot meme → inventory only.

## Practical dataset sizes for ML

| Source | Joinable to bot | Label quality |
|--------|----------------:|---------------|
| 24h snaps | ~625 | best for “early virality” |
| DB lifetime | ~3877 | good bulk; target ≠ 24h |
| Telethon + sc_ | ~4897 | includes +1072 outside table; stats = **now** (lifetime) |
| Union (next step) | ~4.9k unique meme_ids | need pre-bot features for the +1072 |

## Next engineering step

1. Export `user_meme_reaction` pre-post for the **1072** new meme_ids (or full sc_ set).  
2. `build_dataset` union: DB lifetime ∪ Telethon-only sc_ rows.  
3. Re-run `validate.py` with explicit `label_mode=lifetime` and report separately from 24h.

Do **not** mix 24h and lifetime targets in one model without a flag.
