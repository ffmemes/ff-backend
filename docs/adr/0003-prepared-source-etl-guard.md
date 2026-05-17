# ADR-0003: Prepared Source ETL Guard

Status: Accepted

## Context

The moderator community loop can create a "подготовленный источник": a
`meme_source` parked in `in_moderation` with cached raw Telegram posts while
the community vote is pending.

## Decision

Telegram ETL must only transform raw posts for sources whose
`meme_source.status = 'parsing_enabled'`.

Prepared sources may cache raw posts, but they must not create user-visible
memes or recommendations before a successful vote enables the source.

## References

- [AGENTS.md](../../AGENTS.md)
- [Moderator community loop spec](../../specs/moderator-community-loop.md)
- [Canonical domain vocabulary](../../CONTEXT.md)
