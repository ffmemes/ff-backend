# Paperclip Operations Runbook

## What went wrong (2026-03-27 incident)

### Sequence of events
1. GitHub webhook for PR auto-review was returning **401** — never worked
2. Investigation revealed `PAPERCLIP_DEPLOYMENT_EXPOSURE=private` blocks ALL unauthenticated requests, including `/api/routine-triggers/public/` endpoints
3. Changed env var to `public` via Coolify → triggered redeploy
4. `public` mode broke the Board API key auth (403 "Board access required")
5. Reverted to `private` → another redeploy
6. Redeploy lost `config.json` — Paperclip showed "Instance setup required"
7. Manually recreated config.json (too minimal) → validation error
8. Ran `npx paperclipai onboard --yes` → regenerated full config
9. Config pointed to existing DB, data intact, but auth session reset
10. Had to use bootstrap invite to re-create admin access

### Root causes
- **config.json is not on the persistent volume's safe path** — Coolify redeploys can wipe it
- **No backup of config.json** — single point of failure
- **Webhook design flaw** — Paperclip's `private` mode blocks public trigger endpoints
- **No documentation of recovery procedure** — had to improvise

## NEVER DO THIS

1. **Never change `PAPERCLIP_DEPLOYMENT_EXPOSURE`** — flipping between `public` and `private` breaks auth. The current mode is `private` and must stay that way.
2. **Never redeploy Paperclip without backing up config.json first** — the file at `/paperclip/instances/default/config.json` is critical. Without it, Paperclip thinks it's a fresh install.
3. **Never assume env var changes are safe to test** — Paperclip regenerates auth state on mode changes.

## Recovery procedure (if config.json is lost)

```bash
# 1. SSH into server
ssh root@65.108.127.32

# 2. Find Paperclip container
docker ps --format '{{.Names}}' | grep k4w804

# 3. Run onboard to regenerate config (preserves existing DB)
docker exec CONTAINER_NAME sh -c "cd /paperclip && PAPERCLIP_HOME=/paperclip npx paperclipai onboard --yes"

# 4. Restart container for clean port binding
docker restart CONTAINER_NAME

# 5. Open the bootstrap invite URL from the onboard output
# This re-creates admin access. All data is intact.

# 6. Get new Board API key from dashboard (Settings)
# Update docs/paperclip-api.md with the new key
```

## Pre-redeploy checklist

Before ANY Paperclip redeploy (Coolify or manual):

1. **Backup config.json**:
   ```bash
   docker exec CONTAINER sh -c "cat /paperclip/instances/default/config.json" > /tmp/paperclip-config-backup.json
   ```
2. **Verify persistent volume is mounted**: `/paperclip` must survive container replacement
3. **Do NOT change** `PAPERCLIP_DEPLOYMENT_EXPOSURE` or `PAPERCLIP_DEPLOYMENT_MODE`
4. **After redeploy**: verify `config.json` exists, run `curl https://org.ffmemes.com/api/health`

## Webhook fix (TODO)

The GitHub webhook for PR auto-review does NOT work in `private` mode. Options:
- **Cron-based polling**: Change "Review and merge PR" routine from webhook to cron (every 30min, runs `gh pr list --state open`)
- **Cloudflare Worker proxy**: Add auth header before forwarding to Paperclip
- **Wait for Paperclip fix**: File issue — `/public/` trigger endpoints should work in `private` mode

## Process gap: CTO → Release Engineer handoff

When the CTO agent creates a PR, it must also create a task assigned to the Release Engineer to review and merge it. Currently the CTO sets the task to `in_review` and nobody picks it up.

Fix: Update CTO agent instructions to include explicit handoff step.
