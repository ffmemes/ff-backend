# Domain Context

## Share Attribution

Telegram bot-sent meme messages do not expose a native forward/share event to the
bot. If a user forwards a meme message to another chat, the backend cannot
observe that forwarding action directly.

Bot meme forwarding is inferred only when someone clicks the deep link embedded
under the forwarded meme. The in-bot meme link format is
`s_{sharer_user_id}_{meme_id}`. A `/start s_...` event means a user clicked a
link under a shared meme; it does not prove how many times the original bot
message was forwarded.

For Telegram channel posts, separate channel analytics can observe post-level
views and forwards. Those channel post metrics are distinct from private bot
feed share attribution.

Use these terms consistently:

- Share click: a `/start s_{sharer_user_id}_{meme_id}` event recorded in
  `user_deep_link_log`.
- Unique share clickers: distinct users who clicked `s_...` links for a meme,
  including both existing and new users.
- New-user invite: a newly created user attributed to an inviter through an
  `s_...` link and recorded on `user.inviter_id`.
- Meme click conversion: the meme-level count/rate of users who clicked its
  `s_...` link after it was shared.

## Moderator Community

**Moderator Chat**:
The community chat for loyal moderators where the bot can run discussion and source-scouting loops.
_Avoid_: upload review chat, moderation queue

**Upload Review Chat**:
The operational chat where uploaded memes are approved or rejected.
_Avoid_: moderator community chat

**Source Candidate**:
A public meme source discovered or submitted for possible addition to the bot.
_Avoid_: approved source, trial source

**Source Trial**:
A temporary parsing/evaluation period for a source that passed an initial community gate.
_Avoid_: permanent approval

**Telegram Handler Registrar**:
A feature-level function that registers python-telegram-bot handlers for one product area.
_Avoid_: router

## Relationships

- A **Source Candidate** may become a **Source Trial** after a moderator-community vote.
- A **Source Trial** becomes durable only after regular-user feed outcomes are measured.
- The **Moderator Chat** is for community loops; the **Upload Review Chat** is for upload decisions.
- A **Telegram Handler Registrar** owns handler registration for one feature area; the FastAPI webhook router remains separate.

## Flagged ambiguities

- "модераторский чат" can mean the community chat or the uploaded-meme review chat. Resolved: use **Moderator Chat** for the community chat and **Upload Review Chat** for uploaded meme review.
- "router" can mean FastAPI routing or Telegram handler registration. Resolved: use **Telegram Handler Registrar** for python-telegram-bot handler grouping.
