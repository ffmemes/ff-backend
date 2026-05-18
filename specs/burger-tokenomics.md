# Burger Tokenomics and Commands

Current state as of 2026-05-18. This file describes the implementation that exists
today, not an ideal future design.

## Code Map

Core tokenomics code:

- Ledger table: [`treasury_trx`](../src/database.py)
- Payout constants and transaction types: [`treasury/constants.py`](../src/tgbot/handlers/treasury/constants.py)
- Balance, leaderboard, supply, transfer helpers: [`treasury/service.py`](../src/tgbot/handlers/treasury/service.py)
- Idempotent mint/charge wrappers: [`treasury/payments.py`](../src/tgbot/handlers/treasury/payments.py)
- User-facing burger commands: [`treasury/commands.py`](../src/tgbot/handlers/treasury/commands.py)
- Command registry: [`tgbot/app.py`](../src/tgbot/app.py)

Flows and handlers that create burger transactions:

- Upload review payouts: [`upload/moderation.py`](../src/tgbot/handlers/upload/moderation.py)
- Invite/share deep links: [`deep_link.py`](../src/tgbot/handlers/deep_link.py)
- Channel publication payout: [`crossposting/meme.py`](../src/flows/crossposting/meme.py)
- Weekly uploaded-meme rewards: [`rewards/uploaded_memes.py`](../src/flows/rewards/uploaded_memes.py)
- Daily activity reward: [`rewards/daily.py`](../src/flows/rewards/daily.py)
- Chat transfers and chat reward drops: [`chat/send_tokens.py`](../src/tgbot/handlers/chat/send_tokens.py)
- Paid chat-agent replies: [`chat/chat.py`](../src/tgbot/handlers/chat/chat.py)
- Channel boost reward: [`admin/boost.py`](../src/tgbot/handlers/admin/boost.py)
- Giveaway claims: [`treasury/giveaway.py`](../src/tgbot/handlers/treasury/giveaway.py)
- Weekly burger economy channel report: [`weekly_report.py`](../src/flows/crossposting/weekly_report.py)

## Ledger Model

All burger movement is stored as append-only rows in `treasury_trx`:

| Column | Meaning |
| --- | --- |
| `user_id` | Owner of this ledger row. |
| `type` | One of `TrxType` from `treasury/constants.py`. |
| `amount` | Positive mints/receipts, negative charges/sends. |
| `external_id` | Idempotency key for "pay once" operations. |
| `created_at` | Used for weekly windows and reports. |

The displayed balance is `SUM(treasury_trx.amount)` for the user. The denormalized
`user.balance` field is only a cache updated after balance reads.

Current supply is `SUM(treasury_trx.amount)` across all users. It is not capped.

## Payout Table

Current values from `PAYOUTS`:

| Transaction type | Amount | Trigger | Idempotency |
| --- | ---: | --- | --- |
| `meme_uploader` | +5 | Uploaded meme approved in manual review. | `meme.id` |
| `meme_upload_reviewer` | +1 | Moderator reviews an uploaded meme. | `meme.id` |
| `meme_published` | +50 | Uploaded meme is posted to RU or EN public channel. | `meme.id` |
| `meme_shared` | +10 | Existing user clicks a shared meme deep link from another user. | Current date |
| `user_inviter` | +100 | New user joins from another user's meme deep link. | Invited user id |
| `user_inviter_premium` | +200 | Same as above, but invited user has Telegram Premium. | Invited user id |
| `uploader_top_weekly_1` | +500 | Weekly uploaded-meme top 1. | Current date |
| `uploader_top_weekly_2` | +300 | Weekly uploaded-meme top 2. | Current date |
| `uploader_top_weekly_3` | +200 | Weekly uploaded-meme top 3. | Current date |
| `uploader_top_weekly_4` | +100 | Weekly uploaded-meme top 4. | Current date |
| `uploader_top_weekly_5` | +50 | Weekly uploaded-meme top 5. | Current date |
| `daily_reward` | +1 | User reaches exactly 10 memes watched today. | Current date |
| `booster_channel` | +500 | User boosts RU or EN public channel. | Current date |
| `giveaway` | +77 | User claims a giveaway deep link. | Giveaway deep link |
| `purchase_token` | variable | Successful Telegram Stars purchase. | Telegram payment charge id |
| `receive` | variable | User receives a manual group-chat transfer. | Sender user id |
| `send` | negative variable | User sends burgers in group chat. | Recipient user id |
| `bot_reply_payment` | -1 | Bot is mentioned/replied to in a group while chat agent is enabled. | Chat id + message id |

Important current behavior: leaderboard and weekly economy "minted" totals count
every positive row. This includes purchases, receives, giveaways, boost rewards,
daily rewards, and inviter rewards, not only "earned by contribution" payouts.

## User Commands

### `/balance` and `/b`

Private chat only. Shows the user's current ledger-summed balance and renders
purchase buttons for 100, 1000, and 10000 burgers.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Rendered by [`handle_show_balance`](../src/tgbot/handlers/treasury/commands.py)
- Purchase invoice flow in [`payments/purchase.py`](../src/tgbot/handlers/payments/purchase.py)

### `/kitchen`

Private chat only. Explains how to earn and spend burgers. It also sends the
current explainer video when `KITCHEN_EXPLAINER_VIDEO_FILE_ID` is configured.

Localization rule: if `user_language` contains `ru`, show Russian copy. Otherwise
show English copy. Telegram app language is not used for this command.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Rendered by [`handle_show_kitchen`](../src/tgbot/handlers/treasury/commands.py)

### `/leaderboard` and `/l`

Private chat only. Shows top users by positive burger transactions in the last
7 days, total supply, and the requesting user's own place when available.

Localization rule: if `user_language` contains `ru`, show Russian copy. Otherwise
show English copy.

Current ranking rules:

- Window: last 7 days, from `LEADERBOARD_WINDOW_DAYS`.
- Included rows: `treasury_trx.amount > 0`.
- Tie-breaker: smaller `user.id` first.
- Nicknames come from `user.nickname`; missing nicknames get a random emoji fallback.
- User-entered nicknames are HTML-escaped before display.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Rendered by [`handle_show_leaderbaord`](../src/tgbot/handlers/treasury/commands.py)
- Data from [`get_leaderboard`](../src/tgbot/handlers/treasury/service.py) and
  [`get_user_place_in_leaderboard`](../src/tgbot/handlers/treasury/service.py)

### `/nickname <name>`

Private chat only. Stores a public nickname in `user.nickname`. The nickname is
shown in `/leaderboard`, weekly channel reports, and other public places.

Current validation:

- Required as first command argument.
- Max length: 32 characters.
- Disallowed characters: `<` and `>`.

Code: [`handle_change_nickname`](../src/tgbot/handlers/treasury/commands.py).

### `/uploads`

Private chat only. Shows stats for the user's uploaded memes and recent upload
media. It does not directly change burger balance, but it is part of the upload
economy surface.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Rendered by [`upload/stats.py`](../src/tgbot/handlers/upload/stats.py)

### `/refund`

Private chat only, admin-only in the handler. Calls Telegram Stars refund by
payment charge id. It currently does not reverse local `purchase_token` ledger
rows.

Code: [`refund_command`](../src/tgbot/handlers/payments/purchase.py).

### Group chat `+<number>`

Group chats only, reply-only. Transfers burgers from the sender to the author of
the replied-to message.

Rules:

- Sender must have enough balance.
- Recipient must be an existing non-blocked bot user.
- Sending to self is ignored.
- Creates one negative `send` row for the sender and one positive `receive` row
  for the recipient.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Transfer logic in [`send_tokens_to_reply`](../src/tgbot/handlers/chat/send_tokens.py)
- Ledger write in [`transfer_tokens`](../src/tgbot/handlers/treasury/service.py)

### Group chat `+fire <n>`

Group chats only. Rewards active chat users with `active_in_chat` burgers.

Code:

- Registered in [`tgbot/app.py`](../src/tgbot/app.py)
- Logic in [`reward_active_chat_users`](../src/tgbot/handlers/chat/send_tokens.py)

### Chat-agent replies in groups

When the chat agent is enabled and the bot is mentioned/replied to, a successful
agent request charges `bot_reply_payment` (`-1`) from the requester.

Code: [`handle_agent_trigger`](../src/tgbot/handlers/chat/chat.py).

## Non-Treasury Commands

These are registered commands that are not themselves burger-economy commands:

| Command | Scope | Notes |
| --- | --- | --- |
| `/start` | Private | Onboarding, deep links, giveaway links, shared meme links. |
| `/lang` | Private | Bot meme-language settings in `user_language`. |
| `/chat`, `/c`, `/с` | Private text prefix | Feedback/chat to admins. Implemented as a message regex, not `CommandHandler`. |
| `/wrapped` | Private | Wrapped stats flow. |
| `/wrapped_clear` | Private | Clears wrapped cache/state. |
| `/stats` | Private | User stats. |
| `/delete` | Private | User data deletion flow. |
| `/promotemod` | Private | Admin/moderator operation. |
| `/broadcastru`, `/broadcastru1` | Private | Admin broadcast operations. |
| `/discoveredsources`, `/meme`, `/show` | Private | Moderator/source operations. |

Users can also upload photo/video/animation media in private chat; this starts
the upload moderation path that can later mint `meme_uploader` and
`meme_published` burgers.

## Weekly Channel Reports

The weekly burger economy report posts to `@fastfoodmemes` via
`TELEGRAM_CHANNEL_RU_CHAT_ID`.

Current report metrics:

- `minted`: sum of positive rows in the last 7 days.
- `spent`: absolute sum of negative rows in the last 7 days.
- `active_earners`: distinct users with positive rows in the last 7 days.
- `total_supply`: all-time sum of all ledger rows.
- `top_earners`: top 5 users by positive rows in the last 7 days.

Top earners now include `user.nickname`; missing nicknames are rendered as
`без /nickname`.

Code: [`weekly_report.py`](../src/flows/crossposting/weekly_report.py).

## Open Refactor Questions

These are current design debts worth resolving before changing values:

- Should purchases and user-to-user `receive` rows count in `/leaderboard`, or
  should public leaderboards count only contribution rewards?
- Should daily rewards and giveaways count in weekly top earners?
- Should `user.balance` be removed or made strictly transactional? Today it is
  a cache, while the ledger is source of truth.
- Should `send` and `receive` become one atomic transaction with a shared
  transfer id?
- Should `/refund` reverse local burger ledger rows when Telegram Stars are
  refunded?
- Should all command copy move into YAML localization instead of being embedded
  in handlers?
- Should `meme_shared` be per-link, per-clicking-user, or remain one reward per
  sharer per day?
