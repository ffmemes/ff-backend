# Parsing & ETL Pipeline

## Meme Lifecycle

```
Source Channels (TG/VK/IG)
  -> Parser (hourly cron) -> meme_raw_telegram/vk/ig tables
  -> ETL: filter single-media, detect type -> meme table (status='created')
  -> Download from source URL
  -> Watermark (image only, @ffmemesbot, 35% opacity, adaptive corner)
  -> Upload to TG storage chat -> telegram_file_id
  -> OCR (if enabled, currently OFF)
  -> Ad filter (caption keyword check, 48 stop words)
  -> Dedup (OCR text trigram similarity, if OCR enabled)
  -> status='ok' (enters recommendation pool)
```

## Parsing Schedule

| Source | Cron | Frequency | Parser File |
|--------|------|-----------|-------------|
| Telegram | `40 * * * *` | Hourly at :40 | `src/storage/parsers/tg.py` |
| VK | `20 * * * *` | Hourly at :20 | `src/storage/parsers/vk.py` |
| Instagram | `30 0 * * *` | Daily at 00:30 | `src/storage/parsers/ig.py` |

Cron definitions: `flow_deployments/parsers.py`

## Parsers

**Telegram**: BeautifulSoup HTML scraping on `t.me/s/{username}`. Extracts: post_id, URL, date, content, media (with dimensions), views, forwarded_url (repost detection), mentions, hashtags. 10 posts per page with pagination.

**VK**: VK API (v5.92). Filters ads (`marked_as_ads`), multi-media posts. Extracts best quality image from attachments.

**Instagram**: HikerAPI (3rd-party). Stores user_info in meme_source.data JSONB. Currently not in active use (pending evaluation).

## Source Management

- `meme_source` table: 750 sources, status = in_moderation | parsing_enabled | parsing_disabled | snoozed
- `get_meme_sources_to_parse()` selects up to 10 sources per run, ordered by `parsed_at` ASC (NULLS FIRST)
- Sources can be added by users (`added_by` FK) or admins

## ETL Filters

1. **Single-media only**: `JSONB_ARRAY_LENGTH(media) = 1` — removes carousels
2. **Type detection**: video (has duration), animation (.mp4 no duration), image (default)
3. **Repost dedup (TG only)**: `DISTINCT ON (COALESCE(forwarded_url, random()::text))` — within-source only
4. **24h window**: Only processes posts from last 24 hours
5. **Ad filter**: 48 Russian/English stop words + length > 200 chars
6. **Link cleanup**: Removes @mentions, http links, t.me/ links from captions

## Status Progression

```
created (initial ETL)
  ├── broken_content_link (download/upload fails)
  ├── ad (caption analysis matches ad keywords)
  ├── duplicate (OCR text matches existing, when OCR enabled)
  ├── disabled (manually disabled)
  ├── rejected (moderator rejection)
  └── ok (all checks pass -> enters recommendations)
```

Only `status='ok'` memes are served to users.

## Repost Detection Gap

Current: Only detects Telegram forwards within same source via `forwarded_url` field.

NOT detected:
- Cross-source duplicates (same meme in TG and VK)
- Cropped/watermarked/edited versions
- Same meme reposted in different TG channels without forward attribution

See [dedup.md](dedup.md) for improvement plan.

## Key Files

| File | Purpose |
|------|---------|
| `src/storage/parsers/tg.py` | Telegram HTML scraper |
| `src/storage/parsers/vk.py` | VK API parser |
| `src/storage/parsers/ig.py` | Instagram HikerAPI parser |
| `src/storage/etl.py` | Raw -> processed meme transformation |
| `src/storage/service.py` | DB queries, find_meme_duplicate() |
| `src/storage/watermark.py` | Image watermarking (Pillow) |
| `src/storage/ads.py` | Ad keyword detection |
| `src/flows/storage/memes.py` | Pipeline orchestration (tg/vk/ig_meme_pipeline) |
| `flow_deployments/parsers.py` | Cron schedule definitions |
