# Virality loop — product thesis & measurement

**Status:** living product compass (2026-06 cleanup)  
**North star for feed:** session length (memes / session)  
**North star for growth:** organic new users via meme share deep links

## What we believe

Memes are viral content. People already repost them outside the bot. We should:

1. **Ingest** good content from TG channels and VK publics (ETL + quality filters).
2. **Rank** memes for each user so sessions stay long (recommendation engines).
3. **Surface** memes that get shared, and attribute that share to growth.
4. **Close the loop**: feed more of what drives *share clicks* and *new-user invites*,
   not only like rate.

Like rate alone is a weak proxy (dislike ≠ bad meme; text-heavy skip is common).
Share clicks and invites are higher-intent signals.

## Canonical attribution vocabulary

See root [`CONTEXT.md`](../../CONTEXT.md) **Share Attribution**:

| Term | Signal | Storage |
|------|--------|---------|
| Share click | `/start s_{sharer}_{meme_id}` | `user_deep_link_log` |
| New-user invite | new user with inviter from `s_...` | `user.inviter_id` |
| Meme click conversion | clickers / sends for a meme | derived from deep links + sends |

Telegram does **not** give us native forward events on bot DMs. Only link clicks
are observable. Channel post views/forwards are a separate surface
(`crossposting` + Telethon stats).

## Measurement stack (already in the product)

| Layer | Where | Use for |
|-------|--------|---------|
| Reactions | `user_meme_reaction` | session, LR, engines |
| Meme stats | `meme_stats` (`nlikes`, `lr_smoothed`, `engagement_score`, `invited_count`, …) | ranking, crosspost |
| Deep links | `user_deep_link_log` | virality attribution |
| Experiment assignment | `experiment_assignment` | A/B on blend weights / UI |
| Share button variants | experiment + keyboard | CTA copy/placement tests |
| Channel crosspost | `crossposting` decision logs + channel stats | external distribution |
| Analyst SQL | `docs/analyst/*.sql` | readouts |

## What “good experiment” means here

A shippable ranking/growth experiment should have:

1. **Hypothesis** in one sentence (e.g. “boosting high share-click memes in mature blend increases invites/user-day without killing session length”).
2. **Assignment** via `experiment_assignment` (not ad-hoc user_id % 2 in three files).
3. **Primary metric** + **guardrails**:
   - Primary growth: unique share clickers, new-user invites, invites per 1k memes sent
   - Guardrails: session continuation, LR, block rate
4. **Readout SQL** committed under `docs/analyst/` or `experiments/active/…`
5. **Control weights** imported from `src/feed_turn/planner.py` (`MATURE_BLEND_WEIGHTS` / `GROWING_BLEND_WEIGHTS`), never copy-pasted.

## Architecture we want next (not done in Wave A)

To make product tests cheaper:

1. **Deepen meme delivery prep** — one module for caption + share button + keyboard so CTA experiments touch one seam.
2. **Engine template / viral score module** — explicit “virality score” from share clicks + invites + (optional) channel forwards, as a first-class engine or re-ranker, not buried in inline search SQL only.
3. **Experiment harness** — flags in `config.py` + assignment helpers only; hard-disabled experiments either deleted or gated by settings (no silent `enabled=False` with full code paths).
4. **VK ETL parity** — same `parsing_enabled` / quality gates as TG so the supply side is comparable.
5. **Analyst dashboard queries** for weekly: top memes by share-click conversion, engines by continuation, invite funnel by language.

## Related living docs

- [`specs/recommendations.md`](../../specs/recommendations.md) — engines & blender
- [`specs/reaction-flow.md`](../../specs/reaction-flow.md) — hot path
- [`specs/channel-growth-optimization.md`](../../specs/channel-growth-optimization.md) — channel side
- [`specs/crossposting-share-optimization-2026-05-18.md`](../../specs/crossposting-share-optimization-2026-05-18.md) — channel share experiments
- [`specs/data-hypotheses.md`](../../specs/data-hypotheses.md) — data findings
- [`experiments/README.md`](../../experiments/README.md) — how to run A/B write-ups

## Anti-patterns

- Optimizing only for like rate.
- Treating channel forwards as bot-feed share attribution.
- Shipping blend weight changes without assignment rows + readout SQL.
- Reintroducing Instagram pipeline “because docs said so” — IG is decommissioned.
