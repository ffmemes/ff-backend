# Product surface & commands — living notes

**Status:** living product notes (started 2026-08-11)  
**Audience:** founder + agents prioritising what to build next  
**Companion data SQL:** [`docs/analyst/command-surface-proxies.sql`](../analyst/command-surface-proxies.sql)

This is **not** a full SPEC. It captures product nuance, what users actually do,
and decisions about the bot command surface (`/help`, menu, `/last`).

---

## Core product (what actually matters)

| Layer | Reality |
|-------|---------|
| **Primary loop** | Infinite meme feed. Like ❤️ / skip ⏬ on the keyboard. Session north star = memes per session. |
| **`/start`** | Telegram platform default, not a “feature menu”. Delivers a meme + handles **deep links** (share `m_`/`s_`, channel `sc_`, `kitchen`, giveaways, acquisition refs). Do **not** sell `/start` in `/help` as a product capability unless it becomes a real hub. |
| **Like / skip** | Visible on every meme keyboard. Do **not** document them as “commands”. Skip is closer to TikTok “next” than “hate this” (see growth notes / dwell). |
| **Growth** | Organic via share deep links under memes + inline. See [`docs/growth/virality-loop.md`](../growth/virality-loop.md). |

Everything else is secondary surface: economy, upload, lang, chat agent, wrapped, stats.

---

## Founder notes (2026-08-11)

### Burgers 🍔

- Internal currency earned for bot use (daily activity), uploads, share clicks, invites, weekly upload tops, etc.
- **Spend today is weak:** mainly **1 🍔 per reply** when the bot is in a group and someone triggers the DeepSeek agent (`bot_reply_payment`).
- Quality of group chat replies is **poor vs peers** (e.g. countdurovbot prompts feel better).
- Original hope: people add the bot to chats so it **occasionally posts memes** with **low LLM cost** — not a full chat companion.
- Open strategic question: is the economy a real product loop, a joke meta, or scaffolding for a future sink (meme drops in groups, boosts, cosmetics…)? Until there is a good sink, **don’t put burgers in the centre of the menu**.

### Languages (`/lang`)

- Current UI: multi-select picker of content languages.
- **Not intuitive.** Telegram `language_code` is a weak signal (`en` often means nothing about meme taste).
- Content language is really: **`meme_source.language_code` + OCR / describe_memes** on the meme.
- Product intent for lang should be “what languages of memes do I want?”, not “what language is my Telegram app?”.
- Refactor candidate (later): smarter default from TG + first share/source affinity; simplify picker to 1–2 primary languages; stop looking like a settings dump.

### Command surface philosophy

- Prefer **almost empty BotFather menu**: maybe **`/last`** (re-show previous meme) + **`/help`** (catalog of the rest).
- Do not clutter help with base loop (like/skip) or platform `/start` unless deep links need explaining in one line.
- Kitchen/balance/leaderboard are optional depth for people who care about 🍔 — discoverable from `/help`, not necessarily from ☰.

### `/last` (aka `/previous` / `/prev`)

- Real pain: after skip, the bot **replaces** the previous meme message → “brain hadn’t processed it, meme is gone”.
- Multiple users have asked.
- v1: **command only**, re-send last meme (no keyboard button, no multi-step history, no undo-dislike stats rewrite).
- Name options: `/last` (short, clear) vs `/previous` / `/prev`. Prefer one public name + aliases.

---

## Instrumentation (commands)

### What we already had (and what we didn't)

| Store | Scope | Slash commands in private DM? |
|-------|--------|-------------------------------|
| `message_tg` | **Group/channel** messages (chat-agent context) | **No** — private `/kitchen` never landed here |
| `user_deep_link_log` | `/start <payload>` deep links only | Only when args present |
| `inline_search_logs` | Inline queries | N/A |
| `treasury_trx` | Economy side effects | Indirect proxy only |

So “логи всех сообщений” = **group AI context**, not a private command audit trail.

### Now shipping

- **Private DMs → `message_tg`**: inbound private messages (text, media, `/commands`) are saved via PTB group `-1` → `save_telegram_message`. Groups already used this path for the chat agent.
- Command usage readout: `message_tg` where `chat_id > 0` and `text LIKE '/%'` (see analyst SQL).
- **Not logged:** like/skip callbacks (still `user_meme_reaction`); bot outbound meme sends (same ledger).
- Menu `set_my_commands`: **`/last` first**, then `/help` (localized ru/en/uk).
- `/last` (`/previous`, `/prev`): re-send last delivered meme by `sent_at` (like or skip), with buttons; **re-reaction allowed**.

Readout SQL: `docs/analyst/command-surface-proxies.sql`.

### Domain tables still exist on purpose

| Store | Job |
|-------|-----|
| `message_tg` | Transport: groups **and** private inbound DMs |
| `user_deep_link_log` | Growth attribution |
| `user_meme_reaction` | Core feed send + reaction |
| `treasury_trx` / inline / agent | Economy, inline, LLM cost |

Outbound bot messages and callbacks are not mirrored into `message_tg` (volume + PII). Product ledgers stay the source of truth for those.

---

---

## Real usage snapshot (prod readonly, ~2026-08-11)

Window: last **30 days** unless noted. Active ≈ `user.last_active_at`.

### Core loop (orders of magnitude above everything)

| Signal | 7d | 30d |
|--------|----|-----|
| Users who reacted | **390** | **626** |
| Reactions | ~141k | ~609k |
| Skip share of reactions (7d) | **66%** skip / 34% like | — |

Skip is the majority action → **re-show last meme is high-leverage UX**, not a niche power-user toy.

### Secondary features (unique users, 30d proxies)

| Feature / proxy | Users 30d | Notes |
|-----------------|-----------|--------|
| Feed reactors | **626** | Core |
| Daily reward earners | **494** | Auto from activity, not a command |
| Nickname set (active users) | **127** | ~17% of 762 active-30d |
| Uploaders | **40** | Strong UGC core of a small power group |
| Non-self share clickers | **22** | Growth still thin |
| Share-click rewards (`meme_shared`) | **13** | |
| Inviters | **11** | |
| Inline searchers | **12** (58 queries) | Historically larger (10k searches all-time); currently cold |
| Bot chat payers (`bot_reply_payment`) | **12** | Spend sink barely used |
| Kitchen **deep link** only | **10** | `/kitchen` command itself **unmeasured** |
| Stars `purchase_token` | **3 ever** | Economy not monetising |
| `user_wrapped` rows | **0** | Seasonal; dead outside campaigns |

### Group chat agent (burgers sink)

| Metric | Value |
|--------|--------|
| Agent calls 30d | **25** |
| Distinct users 30d | **10** |
| Distinct chats 30d | **2** |
| All-time top chat | Moderator chat dominates volume |
| Chats with `bot_status=member` | handful |

**Read:** group-LLM companion is not a product people use. It burns product attention and LLM quality debt for ~dozens of calls/month. Aligns with founder gut: either **meme-in-chat with low cost**, or deprioritise agent quality work.

### Languages

| Signal | Value |
|--------|--------|
| Active 30d multi-lang (`≥2` codes) | **359 / 762** |
| Lang rows added **after** first hour (90d) | **11 users** |

**Read:** multi-lang is mostly **onboarding / auto-seed**, not deliberate multi-picker use. Investing in multi-select polish is low ROI vs smarter defaults + OCR/source language quality.

### Deep links 30d (entry intents we *do* see)

| Bucket | Events | Users |
|--------|--------|-------|
| empty `/start` | 566 | 190 |
| share `m_`/`s_` | 258 | 105 |
| channel `sc_` | 149 | 45 |
| kitchen | 12 | 10 |
| inline_search_request | 7 | 7 |
| wrapped | 5 | 3 |

Share/start still dominate intentional deep links. Kitchen/wrapped almost unused as links.

---

## What this implies for the menu

### Evidence-based ranking of surfaces

1. **Feed + skip/like** — the product. No command needed.
2. **`/last`** — fills a hole created by our own replace-on-skip UX; skip is 66% of reactions.
3. **`/help`** — needed because discoverability is oral + kitchen footer + popups; menu is not code-owned.
4. **Upload** (send media, not a command) — small but real power-user loop; keep visible in help.
5. **Share / inline** — strategic for growth; low current volume; don’t bury forever, but don’t centre menu on them until share loop improves.
6. **🍔 economy commands** (`/balance`, `/kitchen`, `/leaderboard`, `/nickname`) — secondary. Nickname has some adoption; kitchen deep-link almost none; paid spend near zero.
7. **`/lang`** — needed for wrong-language pain, but UX should be redesigned later; one line in help is enough.
8. **Group agent** — do not promote in user menu until strategy is clear.
9. **`/stats`, `/wrapped`, `/delete`, admin/mod** — help footnote or hidden.

### Concrete menu (shipped)

**Telegram ☰ (order matters):**

1. `/last` — Предыдущий мем / Show previous meme  
2. `/help` — Что умеет бот / What this bot can do

**`/help` body (short):**

- One line: лента = лайк/скип под мемом (not a command list item).
- `/last` — вернуть прошлый мем.
- Пришли мем боту — загрузка; `/uploads` если есть.
- Поделиться — кнопка под мемом / `@ffmemesbot` inline.
- Языки мемов — `/lang` (one line).
- Бургеры — `/kitchen` (collapse detail there).
- Написать нам — `/chat`.
- Данные — `/delete`.
- Do **not** lead with `/start`.

Aliases: `/last` = `/previous` = `/prev` if cheap.

### Shipping order

| Step | Why |
|------|-----|
| 1. `user_command_log` (or equivalent) | Stop flying blind |
| 2. `set_my_commands` + `/help` | Own the surface in code |
| 3. `/last` re-show | Highest user-visible pain vs effort |
| 4. Re-read command log after 2–4 weeks | Decide whether kitchen/lang deserve ☰ slots |
| 5. Lang UX refactor | After defaults/OCR clarity |
| 6. Burgers strategy | Separate product decision: meme-in-chat sink vs sunset promotion of agent |

---

## Open product bets (not decided)

1. **Burgers:** joke points vs real economy. Needs a non-LLM sink people want (e.g. “send meme to this chat”, boosts, cosmetics) or honest de-emphasis.
2. **Bot in groups:** meme poster on a schedule / on emoji trigger **without** chat-LLM — closer to original idea and to cost structure.
3. **`/lang`:** reduce to primary language + optional “also show EN/RU”, driven by source+OCR quality.
4. **Inline:** historically used, now cold — is that discovery, quality, or ranking? Separate investigation.
5. **Share loop still tiny** (22 non-self clickers / 30d) vs 626 reactors — growth work still dominates long-term value; command cleanup is hygiene, not north star.

---

## Related code

| Area | Where |
|------|--------|
| Handler registration | `src/tgbot/app.py` |
| Feed keyboard | `src/tgbot/senders/keyboards.py` |
| Replace-on-skip | `src/tgbot/senders/next_message.py` (`should_replace_previous`) |
| Economy copy | `src/tgbot/handlers/treasury/commands.py` (`/kitchen`) |
| Group agent charge | `src/tgbot/handlers/chat/chat.py` |
| Deep links | `src/tgbot/handlers/start.py`, `user_deep_link_log` |
| No `set_my_commands` today | (gap) |

---

## Changelog

- **2026-08-11:** Initial notes from founder conversation + first prod proxy readout (no direct command telemetry).
- **2026-08-11:** Private DMs → `message_tg` (no separate command table); `/last` + `/help` menu (`last` first); re-reaction allowed.

