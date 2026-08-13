# Admin meme inspect API

Internal HTTP endpoints for agents and operators to inspect a meme without
hand-joining SQL tables, and to **download media via the production Telegram
bot token** (file_id cannot be resolved from SQL alone).

## Auth

Set `ADMIN_API_TOKEN` in the app environment (long random secret). When unset,
routes return **503**.

```http
Authorization: Bearer $ADMIN_API_TOKEN
```

or

```http
X-Admin-Token: $ADMIN_API_TOKEN
```

Never commit the token. Never paste real values into the public repo.

## Endpoints

### `GET /admin/memes/{meme_id}`

Compact JSON card:

| Field | Contents |
|-------|----------|
| `meme` | id, status, type, language, caption, dates, duplicate_of, has_telegram_file_id |
| `source` | id, type, url, status, language |
| `stats` | nlikes, ndislikes, nmemes_sent, lr_smoothed, engagement_score, age_days, … |
| `ocr` | has_ocr, calculated_at, description, text, language, model, failures |
| `media` | available, download_path, content_type, filename |

Optional query: `?include_media=true` — embeds base64 when the file is **≤ 4MB**.
Larger files return `media.inline_error` and you should use the media route.

### `GET /admin/memes/{meme_id}/media`

Raw image/video bytes (`Content-Type: image/jpeg` / `video/mp4` / `image/gif`).
Downloaded through `download_meme_content_from_tg` using `TELEGRAM_BOT_TOKEN`.

## Agent usage

```bash
# Info only
curl -sS -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "$SITE_BASE_URL/admin/memes/123456" | jq .

# Save media for visual inspection (images work with the image read tool)
curl -sS -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  "$SITE_BASE_URL/admin/memes/123456/media" -o /tmp/meme_123456.jpg
```

`$SITE_BASE_URL` is the production app origin (private ops notes / Coolify).
Do not commit hostnames into this public repo.

Related Telegram-only command: moderators can still use `/meme <id>` in the bot
([`src/tgbot/handlers/moderator/get_meme.py`](../src/tgbot/handlers/moderator/get_meme.py)).
That path is not available to HTTP agents.

## Code

| Piece | Path |
|-------|------|
| Router | [`src/admin/router.py`](../src/admin/router.py) |
| Payload builder | [`src/admin/service.py`](../src/admin/service.py) |
| Auth | [`src/admin/auth.py`](../src/admin/auth.py) |
| Config | `ADMIN_API_TOKEN` in [`src/config.py`](../src/config.py) |
| Tests | [`tests/admin/test_meme_inspect.py`](../tests/admin/test_meme_inspect.py) |
