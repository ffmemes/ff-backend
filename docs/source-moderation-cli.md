# Source moderation CLI (operator-driven)

`scripts/admin/advance_source.py` advances a `meme_source` row through
moderation states (`in_moderation` → `parsing_enabled`, snooze, unsnooze,
language assignment) without driving the Telegram moderator UI.

## When to use

The moderator UI in `@ffmemesbot` requires a real Telegram identity. This CLI
gives operators and trusted automation a server-side path for sources discovered
by `/discoveredsources`, while calling the same business logic as the bot — see
`src/storage/moderation.py::advance_meme_source`.

Typical triggers:
- Source candidates surge in the discovery queue and require an operator pass.
- An operator needs to re-enable a source after a regression test.
- Auto-snooze fires on a source that was misclassified; an operator un-snoozes
  it after fixing the parser.

## How it runs

The CLI shares the prod DB env vars by running inside the `app`
container:

```bash
docker compose exec app python -m scripts.admin.advance_source \
    --id <meme_source_id> \
    --language ru \
    --status parsing_enabled \
    --moderator-id operator:maintenance
```

Flags:
- `--id` (required): `meme_source.id`.
- `--language`: ISO code (`ru`, `en`, …). Set on first promotion or to
  re-classify.
- `--status`: one of `in_moderation`, `parsing_enabled`,
  `parsing_disabled`, `snoozed`. Skip to leave unchanged.
- `--moderator-id` (required): stable identifier of the caller. Use a namespaced
  value such as `operator:maintenance` so the audit trail can distinguish CLI
  actions from human moderators (numeric Telegram user IDs).
- `--no-trigger-parse`: skip the platform parser kick-off after a flip
  to `parsing_enabled`. Default behavior is to trigger parsing for TG
  and VK sources (matches the bot moderator path).
- `--show`: read-only — dump the current row as JSON and exit.

The CLI prints a JSON result with `before_*`, `after_*`, snoozed /
unsnoozed counts, and whether parsing was triggered.

## Audit trail

Every status or language change appends an entry to
`meme_source.data.moderation_log`:

```json
{
  "moderation_log": [
    {
      "moderator": "agent:cto",
      "ts": "2026-05-10T21:30:00.000000",
      "changed": {
        "language_code": {"from": null, "to": "ru"},
        "status": {"from": "in_moderation", "to": "parsing_enabled"}
      }
    }
  ],
  "last_moderated_by": "agent:cto"
}
```

The Telegram moderator UI also writes to the same field with the
human's numeric user_id, so the trail is unified.

## Verification post-promotion

After flipping a source to `parsing_enabled`, parsing has been
triggered inline. Expected timing:

1. Within ~30s: `meme_raw_telegram` rows for the new source appear.
2. Within the next pipeline run (≤15 min): `meme(meme_source_id=…)`
   rows transition `created → ok`.

Quick sanity query (run via `psql $ANALYST_DATABASE_URL`):

```sql
SELECT
  ms.id,
  ms.url,
  ms.status,
  (SELECT count(*) FROM meme_raw_telegram WHERE meme_source_id = ms.id) AS raw_posts,
  (SELECT count(*) FROM meme WHERE meme_source_id = ms.id) AS memes_total,
  (SELECT count(*) FROM meme WHERE meme_source_id = ms.id AND status = 'ok') AS memes_ok
FROM meme_source ms
WHERE ms.id = ANY(ARRAY[21848, 21849]);
```

## Failure modes

- `error: not_found` — wrong id, or a candidate row was never promoted
  to `meme_source`. Check `meme_source_candidate.promoted_meme_source_id`.
- `error: bad_request` — invalid status string or no fields supplied.
- Parser errors (TG flood-wait, IG rate-limit) propagate as
  exceptions. The DB transition has already committed — the source
  row is marked `parsing_enabled` and the next scheduled parse run
  picks it up.
