# Parsing & ETL Pipeline

## Meme Lifecycle

```
Source Channels (TG/VK)
  -> Parser (hourly cron) -> meme_raw_telegram / meme_raw_vk
  -> ETL: filter single-media, detect type -> meme table (status='created')
  -> Download from source URL
  -> Watermark (image only, @ffmemesbot, 35% opacity, adaptive corner)
  -> Upload to TG storage chat -> telegram_file_id
  -> Ad filter (caption keyword check)
  -> Dedup (OCR text trigram similarity when OCR present)
  -> status='ok' (enters recommendation pool)
  -> Describe Memes (async, every 15min, OpenRouter free vision) -> ocr_result JSONB
```

Note: Legacy Modal OCR has been removed. [Describe Memes](describe-memes.md) is the
active system for image analysis.

**Instagram:** parser and `ig_meme_pipeline` are **removed**. Historical
`meme_raw_ig` rows may remain; do not document IG as an active source.

## Parsing Schedule

| Source | Cron | Frequency | Parser File |
|--------|------|-----------|-------------|
| Telegram | `40 * * * *` | Hourly at :40 | `src/storage/parsers/tg.py` |
| VK | `20 * * * *` | Hourly at :20 | `src/storage/parsers/vk.py` |

Cron definitions: `scripts/serve_flows.py`

## Parsers

**Telegram**: BeautifulSoup HTML scraping on `t.me/s/{username}`. Extracts: post_id, URL, date, content, media (with dimensions), views, forwarded_url (repost detection), mentions, hashtags.

**VK**: VK API. Filters ads (`marked_as_ads`), multi-media posts. Extracts best quality image from attachments.

## Source Management

- `meme_source` table: status includes `in_moderation` | `parsing_enabled` | `snoozed` (plus legacy strings)
- Prepared sources (`in_moderation`) must not ETL into the user feed until promoted — TG ETL guards on `parsing_enabled` (ADR-0003). VK parity is incomplete debt.
- Sources can be added by users (`added_by` FK), moderators, or discovery → candidate promotion

## ETL Filters

1. **Single-media only**: `JSONB_ARRAY_LENGTH(media) = 1` — removes carousels
2. **Type detection**: video / animation / image (TG); VK currently often forces image
3. **Repost dedup (TG only)**: `DISTINCT ON (COALESCE(forwarded_url, …))`
4. **24h window**: only recent raw posts
5. **Ad filter**: stop words + length > 200 chars (`src/storage/ads.py`)
6. **Link cleanup**: removes @mentions / http / t.me from captions
7. **TG engagement filters**: top-view / median view quality gates (VK lacks these — drift)

## Status Progression

```
created (initial ETL)
  ├── broken_content_link (download/upload fails)
  ├── ad (caption analysis matches ad keywords)
  ├── duplicate (OCR text matches existing)
  ├── disabled / snoozed / rejected
  └── ok (enters recommendations)
```

Only `status='ok'` memes are served to users.

## Repost Detection Gap

Current: only Telegram forwards within same source via `forwarded_url`.

NOT detected:

- Cross-source duplicates (same meme in TG and VK)
- Cropped/watermarked/edited versions
- Same meme in different TG channels without forward attribution

See [dedup.md](dedup.md).

## Key Files

| File | Purpose |
|------|---------|
| `src/storage/parsers/tg.py` | Telegram HTML scraper |
| `src/storage/parsers/vk.py` | VK API parser |
| `src/storage/etl.py` | Raw → processed meme transformation |
| `src/storage/service.py` | Shared DB queries and meme status updates |
| `src/storage/deduplication/` | File ID / OCR duplicate detection |
| `src/storage/watermark.py` | Image watermarking (Pillow) |
| `src/storage/ads.py` | Ad keyword detection |
| `src/flows/storage/memes.py` | `tg_meme_pipeline` / `vk_meme_pipeline` / `final_meme_pipeline` |
| `scripts/serve_flows.py` | Cron schedule definitions |
