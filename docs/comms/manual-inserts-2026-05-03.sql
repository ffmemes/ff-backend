-- One-off backfill for editorial_posts rows that were posted to @ffmemes
-- before the Comms agent had write access (see FFM-919 / FFM-918).
--
-- Run once on prod against the ff database as a superuser (or as the app's
-- writer role — comms_writer cannot upsert here because the rows pre-date
-- the role's existence and we want this run audited).
--
-- After both rows exist, the stats collector will start tracking
-- views/forwards/reactions on its next run.

\set ON_ERROR_STOP on

BEGIN;

-- May 3, 2026 — telegram_message_id=234 — activation-record post.
INSERT INTO editorial_posts
  (channel, telegram_message_id, draft_hash, category, entity_id,
   topic_slug, text, has_media, validation_version, created_at)
VALUES (
  'ffmemes', 234,
  '6a3e2f8c1b4d5a9e0712345678901234',
  'C', 'cohort_week:2026-04-27', 'activation-record',
  E'<b>Интересное:</b> 77% новичков...\n\n↳ @ffmemesbot',
  true, 1, '2026-05-03 07:12:37'
)
ON CONFLICT (draft_hash) DO NOTHING;

-- April 29, 2026 backfill — see FFM-918 for the post text + draft_hash.
-- Replace the placeholders with the real values from the published archive
-- (docs/comms/published/2026-04-29-new-user-activation-lift.md) before
-- running. If the row already exists with a non-NULL telegram_message_id,
-- the ON CONFLICT clause is a safe no-op.

-- INSERT INTO editorial_posts
--   (channel, telegram_message_id, draft_hash, category, entity_id,
--    topic_slug, text, has_media, validation_version, created_at)
-- VALUES (
--   'ffmemes', <APR29_MSG_ID>,
--   '<APR29_DRAFT_HASH>',
--   '<CATEGORY>', '<ENTITY_ID>', '<TOPIC_SLUG>',
--   E'<full post text>',
--   true, 1, '2026-04-29 07:00:00'
-- )
-- ON CONFLICT (draft_hash) DO NOTHING;

-- Verify both rows landed.
SELECT id, channel, telegram_message_id, category, entity_id, topic_slug, created_at
FROM editorial_posts
WHERE channel = 'ffmemes'
  AND created_at >= '2026-04-29'
ORDER BY created_at;

COMMIT;
