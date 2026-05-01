Daily build-in-public post for @ffmemes (RU).

Run the workflow in `agents/comms-manager/AGENTS.md` ("What Triggers You", steps 0–7). That file is the source of truth — don't re-derive a parallel workflow here.

Things that trip people up:

- Post via `src.comms.publishing.publish_editorial_post()`. Single sanctioned path. Raw curl, sendPhoto, or sendMessage to the channel splits the post into photo-without-caption + text — we shipped that once.
- Step 0 — read `experiments/reports/channel-stats-YYYY-MM-DD.md` for yesterday's performance.
- Step 1 — pick the strongest `Chart-worthy: yes` finding from `experiments/reports/anomalies-YYYY-MM-DD.md`.
- Step 7 — archive to `docs/comms/published/YYYY-MM-DD-slug.md` and close this issue with a one-liner pointing at the archive.
- CEO approval is not publication. If approval is required, the routine may close
  its execution issue with `outcome=draft_created`, but the linked `[post:...]`
  issue must later be reassigned to Comms and closed only after
  `publish_editorial_post()` returns `message_id` / `editorial_post_id`.

Validation, rotation, and the topic ban-list are enforced in code. If `EditorialValidationError` fires, fix the draft.
