# Public Repo Redaction Rule

This repository is public. Anything tracked here can be cloned by anyone, and
git history preserves it forever. AI agents read these files as instructions,
so a single leaked secret can also become a worked example for future runs.

## Allowed in tracked files

- Environment variable names (e.g. `PAPERCLIP_API_KEY`, `ANALYST_DATABASE_URL`).
- Paperclip secret names (the human-readable handle, not the UUID id).
- Public dashboard hostnames (`org.ffmemes.com`, `t.me/ffmemes`).
- Redacted issue identifiers (`FFM-1234`) and routine titles (`QA Log Scan`).
- Stable lookup paths (e.g. "Sentry Internal Integration → Paperclip QA
  trigger public URL in the Paperclip dashboard").

## Forbidden in tracked files

- API keys, bot tokens, session strings, or any other secret values.
- Database URLs that contain a real password (placeholders such as
  `app:app@`, `changeme`, or `<password>` in `.env.example` are fine).
- Authorization headers with a literal bearer token. Use `$VAR_NAME` or a
  `${VAR_NAME}` reference; never `Bearer eyJ...`.
- Paperclip routine trigger public paths or public IDs
  (`/api/routine-triggers/public/<publicId>/fire`). The `publicId` itself
  acts as a shared secret. Reference triggers by routine title, not URL.
- Paperclip secret UUIDs. Reference secrets by their env var name.
- Internal hostnames, private webhook URLs, or anything else that grants
  access to production by knowing the URL.
- Inlined private keys.

## How this is enforced

`scripts/redaction_audit.py` scans every tracked file for the patterns above.
CI and the pre-commit hook should run it.

```bash
python3 scripts/redaction_audit.py             # scan all tracked files
python3 scripts/redaction_audit.py path/to/f   # scan a subset
python3 scripts/redaction_audit.py --list-patterns
```

If a finding is intentional (a fixture or this rule itself), add the file path
to `ALLOWLIST_PATHS` or `PLACEHOLDER_PATHS` in `scripts/redaction_audit.py`.
Do not silence individual lines.

## When something does leak

1. Rotate the secret immediately (Paperclip dashboard → Settings → Secrets,
   GitHub Actions → Secrets, Coolify → Environment).
2. Remove the value from the working tree and commit a redacted version.
3. Note the rotation in the relevant runbook section so the next agent
   knows the lookup path is now clean.

Do not rely on rewriting git history. Treat any committed secret as
public from the moment of the push.
