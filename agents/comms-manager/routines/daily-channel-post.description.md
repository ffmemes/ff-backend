Daily RU channel post. Product/process/build-in-public updates target @ffmemes;
fun meme findings may target @fastfoodmemes when they stand alone for the wider
main-channel audience.

Run the workflow in `agents/comms-manager/AGENTS.md` ("What Triggers You", steps 0–7). That file is the source of truth — don't re-derive a parallel workflow here.

Things that trip people up:

- Post via `src.comms.publishing.publish_editorial_post()`. Single sanctioned path. Raw curl, sendPhoto, or sendMessage to the channel splits the post into photo-without-caption + text — we shipped that once.
- For generated/local visuals, pass `photo_bytes=png` directly. Do not post the image to the moderator chat for staging or `file_id` extraction.
- Step 0 — read `experiments/reports/channel-stats-YYYY-MM-DD.md` for yesterday's performance.
- Step 1 — pick the strongest `Chart-worthy: yes` finding from `experiments/reports/anomalies-YYYY-MM-DD.md`.
- Step 2 — avoid the last 14 topic families, not just exact slugs. A new
  session-length/North-Star slug is still a repeated session-length post.
- Step 2b — search open/blocked `[post:...]` issues before drafting; blocked or
  approved-unpublished drafts count as already used topics.
- Step 7 — archive to `docs/comms/published/YYYY-MM-DD-slug.md` and close this issue with a one-liner pointing at the archive.
- Outcome comments must include the actual public channel and Telegram URL.
  `telegram_message_id` alone is ambiguous because @ffmemes and @fastfoodmemes
  are different chats with different message id sequences.
- CEO approval is not publication. The routine may close its execution issue with
  `outcome=draft_created`, but the linked `[post:...]` issue must carry a
  CEO-authored `decision=approved_to_publish` marker for the latest draft
  revision. It is closed only after CEO returns it to Comms and
  `publish_editorial_post()` returns `result.message_id` /
  `result.editorial_post_id`.

Validation, rotation, and the topic ban-list are enforced in code. If `EditorialValidationError` fires, fix the draft.
