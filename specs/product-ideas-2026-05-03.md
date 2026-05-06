# Product Ideas: Text Density, Language Segments, Meme Sharing

Date: 2026-05-03

Scope: three product/data ideas to validate before changing recommendation or bot UX.

## 1. Text-Heavy Memes

Hypothesis: memes with a lot of OCR text get skipped because users do not want to read them in a fast feed. If true, these memes should either be routed only to users who like them or excluded from broad distribution.

Why this is testable now:

- `meme.ocr_result` stores OCR text at `ocr_result->>'text'`.
- `meme_stats` stores aggregate `nlikes`, `ndislikes`, `nmemes_sent`, `sec_to_react`, `lr_smoothed`, and `engagement_score`.
- `user_meme_reaction` stores impression-level `sent_at`, `reaction_id`, and `reacted_at`, so text-heavy memes can be measured by like rate and reaction speed.
- `describe_memes_flow` still uses OpenRouter free multimodal models for OCR, humor description, and language extraction. It is slow by design.
- Current deployment in `scripts/serve_flows.py` runs every 15 minutes with `batch_size=9` (about 864/day) under the $10 lifetime-purchase OpenRouter free-model tier. A Redis guard stops OpenRouter calls at 900 free-model attempts/day.
- Current priority is: recent user uploads from the last 24h first, then highest `meme_stats.nlikes`, then newest IDs.

Useful definitions:

- `ocr_chars`: `length(coalesce(m.ocr_result->>'text', ''))`
- `ocr_words`: word count after whitespace split.
- `text_heavy`: start with percentiles, not a hard threshold. Compare P50/P75/P90/P95 buckets.
- `read_skip`: reaction is skip/dislike and `reacted_at - sent_at` is short. Existing specs treat fast skips differently from genuine dislikes.

First SQL pass:

```sql
WITH meme_text AS (
    SELECT
        m.id AS meme_id,
        m.language_code,
        length(coalesce(m.ocr_result->>'text', '')) AS ocr_chars,
        CASE
            WHEN trim(coalesce(m.ocr_result->>'text', '')) = '' THEN 0
            ELSE cardinality(regexp_split_to_array(trim(m.ocr_result->>'text'), '\s+'))
        END AS ocr_words,
        coalesce(ms.nlikes, 0) AS nlikes,
        coalesce(ms.ndislikes, 0) AS ndislikes,
        coalesce(ms.nmemes_sent, 0) AS nmemes_sent,
        ms.sec_to_react,
        ms.lr_smoothed,
        ms.engagement_score
    FROM meme m
    LEFT JOIN meme_stats ms ON ms.meme_id = m.id
    WHERE m.status = 'ok'
      AND m.type = 'image'
      AND m.ocr_result->>'calculated_at' IS NOT NULL
),
bucketed AS (
    SELECT
        *,
        ntile(10) OVER (ORDER BY ocr_chars) AS char_decile
    FROM meme_text
    WHERE nlikes + ndislikes >= 10
)
SELECT
    char_decile,
    count(*) AS memes,
    round(avg(ocr_chars), 1) AS avg_chars,
    round(avg(ocr_words), 1) AS avg_words,
    round(100.0 * sum(nlikes) / nullif(sum(nlikes + ndislikes), 0), 1) AS like_rate,
    round(avg(sec_to_react)::numeric, 2) AS avg_sec_to_react,
    round(avg(lr_smoothed)::numeric, 3) AS avg_lr_smoothed,
    round(avg(engagement_score)::numeric, 3) AS avg_engagement_score
FROM bucketed
GROUP BY char_decile
ORDER BY char_decile;
```

OCR coverage sanity check:

```sql
SELECT
    count(*) FILTER (WHERE m.type = 'image' AND m.status = 'ok') AS ok_images,
    count(*) FILTER (
        WHERE m.type = 'image'
          AND m.status = 'ok'
          AND m.ocr_result->>'calculated_at' IS NOT NULL
    ) AS described_ok_images,
    count(*) FILTER (
        WHERE m.type = 'image'
          AND m.status = 'ok'
          AND m.ocr_result->>'calculated_at' > (now() - interval '24 hours')::text
    ) AS described_last_24h,
    max((m.ocr_result->>'calculated_at')::timestamptz) AS latest_described_at,
    count(*) FILTER (
        WHERE coalesce((m.ocr_result->>'describe_failures')::int, 0) >= 3
    ) AS permanently_skipped
FROM meme m;
```

Segmented follow-up:

- Split by `m.language_code`, because text density may hurt more when the user language does not match the meme language.
- Split by user maturity: `<10`, `10-29`, `30-99`, `100+` memes sent. New users may abandon long-text memes more than power users.
- Split by reaction speed: fast skip, slow skip, like.
- Check if high-text memes have a small group of strong fans. If yes, add a candidate source/feature for personalization instead of globally suppressing them.

Potential actions:

- If text-heavy memes underperform across segments: down-rank or exclude from cold start.
- If they underperform only for new users: keep them out of first 30 memes.
- If they polarize: add a text-density feature to user affinity and route them to users with above-baseline like rate on high-text memes.
- If no negative effect: do nothing. Avoid adding a content heuristic without evidence.

## 2. Language Audiences And Misconfigured Users

Hypothesis: there are at least three relevant audiences:

- Russian/CIS users.
- Non-Russian users.
- Users whose inferred or selected languages do not match the content they actually receive or like, causing weak activation/retention.

Why this is testable now:

- Telegram language is stored in `user_tg.language_code`.
- Bot-selected meme languages are stored in `user_language`.
- Meme language is stored in `meme.language_code`; Describe Memes can update it for known languages.
- `init_user_languages_from_tg_user()` seeds `ru` for CIS Telegram languages and `en` otherwise, then also stores the raw Telegram language code.
- If the Telegram language is `en`, `ru` is added only when the full name contains Cyrillic characters. Russian-speaking users with English Telegram and Latin names are likely initialized as EN-only.
- Recommendations inner join `user_language` to `meme.language_code`, so a bad language row can directly starve or mis-route the feed.

Audience sizing query:

```sql
WITH user_langs AS (
    SELECT
        u.id AS user_id,
        utg.language_code AS tg_lang,
        array_remove(array_agg(ul.language_code ORDER BY ul.language_code), NULL) AS selected_langs,
        coalesce(us.nmemes_sent, 0) AS nmemes_sent,
        coalesce(us.nlikes, 0) AS nlikes,
        coalesce(us.ndislikes, 0) AS ndislikes,
        us.first_reaction_at,
        us.last_reaction_at
    FROM "user" u
    LEFT JOIN user_tg utg ON utg.id = u.id
    LEFT JOIN user_language ul ON ul.user_id = u.id
    LEFT JOIN user_stats us ON us.user_id = u.id
    GROUP BY u.id, utg.language_code, us.nmemes_sent, us.nlikes, us.ndislikes,
             us.first_reaction_at, us.last_reaction_at
),
segmented AS (
    SELECT
        *,
        CASE
            WHEN selected_langs && ARRAY['ru', 'uk', 'be', 'kk', 'kz', 'uz', 'az']
                THEN 'ru_or_cis_selected'
            WHEN selected_langs && ARRAY['en'] THEN 'en_selected'
            WHEN cardinality(selected_langs) = 0 THEN 'no_selected_language'
            ELSE 'other_selected'
        END AS lang_segment
    FROM user_langs
)
SELECT
    lang_segment,
    count(*) AS users,
    round(avg(nmemes_sent), 1) AS avg_memes_sent,
    percentile_disc(0.5) WITHIN GROUP (ORDER BY nmemes_sent) AS median_memes_sent,
    round(100.0 * sum(nlikes) / nullif(sum(nlikes + ndislikes), 0), 1) AS like_rate,
    round(100.0 * count(*) FILTER (WHERE nmemes_sent >= 30) / count(*), 1) AS activation_30_pct
FROM segmented
GROUP BY lang_segment
ORDER BY users DESC;
```

Mismatch query:

```sql
WITH reactions_by_language AS (
    SELECT
        umr.user_id,
        m.language_code AS meme_lang,
        count(*) AS reactions,
        count(*) FILTER (WHERE umr.reaction_id = 1) AS likes,
        count(*) FILTER (WHERE umr.reaction_id = 2) AS skips
    FROM user_meme_reaction umr
    JOIN meme m ON m.id = umr.meme_id
    WHERE umr.reaction_id IS NOT NULL
    GROUP BY umr.user_id, m.language_code
),
best_lang AS (
    SELECT DISTINCT ON (user_id)
        user_id,
        meme_lang AS best_observed_lang,
        reactions,
        round(100.0 * likes / nullif(likes + skips, 0), 1) AS observed_like_rate
    FROM reactions_by_language
    WHERE reactions >= 10
    ORDER BY user_id, likes::float / nullif(likes + skips, 0) DESC, reactions DESC
),
user_profiles AS (
    SELECT
        u.id AS user_id,
        utg.language_code AS tg_lang,
        array_remove(array_agg(ul.language_code ORDER BY ul.language_code), NULL) AS selected_langs
    FROM "user" u
    LEFT JOIN user_tg utg ON utg.id = u.id
    LEFT JOIN user_language ul ON ul.user_id = u.id
    GROUP BY u.id, utg.language_code
)
SELECT
    up.tg_lang,
    up.selected_langs,
    bl.best_observed_lang,
    count(*) AS users,
    round(avg(bl.observed_like_rate), 1) AS avg_observed_like_rate
FROM best_lang bl
JOIN user_profiles up ON up.user_id = bl.user_id
GROUP BY up.tg_lang, up.selected_langs, bl.best_observed_lang
ORDER BY users DESC
LIMIT 100;
```

Russian-affinity check for `tg_lang = 'en'` users:

```sql
WITH profiles AS (
    SELECT
        u.id AS user_id,
        utg.language_code AS tg_lang,
        (coalesce(utg.first_name, '') || coalesce(utg.last_name, '')) ~* '[А-Яа-яЁё]' AS has_cyrillic_name,
        array_remove(array_agg(ul.language_code ORDER BY ul.language_code), NULL) AS selected_langs,
        coalesce(us.nmemes_sent, 0) AS nmemes_sent
    FROM "user" u
    LEFT JOIN user_tg utg ON utg.id = u.id
    LEFT JOIN user_language ul ON ul.user_id = u.id
    LEFT JOIN user_stats us ON us.user_id = u.id
    GROUP BY u.id, utg.language_code, utg.first_name, utg.last_name, us.nmemes_sent
),
reaction_lang AS (
    SELECT
        umr.user_id,
        m.language_code AS meme_lang,
        count(*) AS reactions,
        count(*) FILTER (WHERE umr.reaction_id = 1) AS likes
    FROM user_meme_reaction umr
    JOIN meme m ON m.id = umr.meme_id
    WHERE umr.reaction_id IS NOT NULL
      AND m.language_code IN ('ru', 'en')
    GROUP BY umr.user_id, m.language_code
),
pivoted AS (
    SELECT
        p.user_id,
        p.has_cyrillic_name,
        p.selected_langs,
        p.nmemes_sent,
        coalesce(sum(reactions) FILTER (WHERE meme_lang = 'ru'), 0) AS ru_reactions,
        coalesce(sum(likes) FILTER (WHERE meme_lang = 'ru'), 0) AS ru_likes,
        coalesce(sum(reactions) FILTER (WHERE meme_lang = 'en'), 0) AS en_reactions,
        coalesce(sum(likes) FILTER (WHERE meme_lang = 'en'), 0) AS en_likes
    FROM profiles p
    LEFT JOIN reaction_lang rl ON rl.user_id = p.user_id
    WHERE p.tg_lang = 'en'
    GROUP BY p.user_id, p.has_cyrillic_name, p.selected_langs, p.nmemes_sent
)
SELECT
    has_cyrillic_name,
    selected_langs,
    count(*) AS users,
    round(avg(nmemes_sent), 1) AS avg_memes_sent,
    count(*) FILTER (WHERE ru_reactions >= 10 AND en_reactions >= 10) AS users_exposed_to_both,
    round(100.0 * sum(ru_likes) / nullif(sum(ru_reactions), 0), 1) AS ru_like_rate,
    round(100.0 * sum(en_likes) / nullif(sum(en_reactions), 0), 1) AS en_like_rate
FROM pivoted
GROUP BY has_cyrillic_name, selected_langs
ORDER BY users DESC;
```

What to decide from the data:

- If Russian/CIS dominates and non-RU retention is weak, focus product quality on RU first instead of spreading content/UX work too thin.
- If EN/non-RU has meaningful size and retention, segment onboarding, content sources, and growth channels by language.
- If many users have `nmemes_sent < 10` and no viable language match, add an early language correction prompt or a one-tap "show me Russian / English / Spanish memes" recovery.
- If Telegram language is a poor proxy, stop treating it as strong evidence and prefer explicit selection plus early reaction behavior.
- If `tg_lang = 'en'` users who see both RU and EN memes prefer RU, add RU exploration for Telegram-English users rather than relying on Telegram language. This should be an experiment, because EN-only users have censored data: if they never saw RU memes, their preference is unobservable.

## 3. "Send To A Friend" CTA Under Memes

Goal: add a large share CTA under the current like/skip row to make sharing an intentional action.

Current state:

- `meme_reaction_keyboard()` currently returns two buttons: heart-like and skip.
- The commented referral URL row says Telegram removes that link, so this needs a different approach.
- Existing deep-link tracking already understands `s_{user_id}_{meme_id}` and updates `meme_stats.invited_count`.
- Existing inline search uses `InlineQueryResultCachedPhoto`, `create_inline_search_log`, and `create_inline_chosen_result_log`.

Telegram API constraints:

- Bot API inline keyboard buttons can open URLs, send callbacks, copy text, or switch the user into inline mode. They cannot force a native forward of the current bot message.
- `t.me/share/url` can share a URL/text into a chosen chat's input field. It cannot directly attach Telegram media.
- A bot deep link can open the bot with `/start <parameter>`, up to 64 base64url characters. This can point to `s_{user_id}_{meme_id}`.
- `switch_inline_query` / `switch_inline_query_chosen_chat` can prompt the user to choose a chat and prefill an inline query.
- Inline mode can return cached Telegram photos by `photo_file_id`, which matches how memes are stored.
- Mini Apps can use `switchInlineQuery`, and newer clients can use `shareMessage` with `savePreparedInlineMessage` to share prepared media messages.

Mechanics matrix:

| Mechanic | Shares actual meme media into friend chat? | Can open exact meme in bot? | Main friction | Instrumentation |
|----------|--------------------------------------------|-----------------------------|---------------|-----------------|
| Native forward | Yes | No custom Bot API action | User must use Telegram's native forward UI; no big custom CTA | Hard to attribute unless forwarded caption/deep link survives |
| `t.me/share/url` + `start=s_user_meme` | No, shares a link/text | Yes, if `/start s_...` sends that meme | Friend must click link and start/open bot | Deep-link clicks via `user_deep_link_log`; no send event |
| Inline share via `switch_inline_query_chosen_chat` | Yes | Can include bot deep link in caption | User chooses chat, then sends/selects inline result | `chosen_inline_result` logs actual inline sends |
| Copy link button | No | Yes | Manual paste | No reliable send event |
| Mini App web feed + inline/share APIs | Yes, depending on API path | Yes | Build and maintain web feed; client compatibility | Rich in-app analytics plus share callbacks where available |

Important current-code gap:

- `get_referral_link()` already creates `https://t.me/<bot>?start=s_{user_id}_{meme_id}`.
- `handle_invited_user()` and `handle_shared_meme_reward()` already parse this format for inviter/share rewards.
- `handle_start()` does not currently send the specific `meme_id` from `s_{user_id}_{meme_id}`. New users see language settings first; existing users receive the next feed meme. If we use magic links, this must change.

Option A: URL share deep link to exact meme.

1. Button URL: `https://t.me/share/url?url=<bot_start_s_user_meme>&text=<short_cta>`.
2. Update `/start s_{sharer_id}_{meme_id}` to send that exact meme to the recipient, then continue onboarding/feed.
3. For new users: show the shared meme first, then language choice or a short CTA to continue.
4. For existing users: send shared meme first even if it is outside their current language queue, then continue normal feed.

Pros:

- Simple implementation.
- Uses existing deep-link attribution.
- Lets the friend land on the exact meme inside the bot.

Cons:

- The friend chat receives a link, not the meme media.
- We measure clicks/starts, not how many shares were sent.
- Link previews may be inconsistent unless we build a public preview page for each meme.

Option B: inline share by meme id.

1. Add a third row to `meme_reaction_keyboard()`:
   - RU examples: `кинь другу`, `швырни в чат`, `поделись кринжем`.
   - EN examples: `send to a friend`, `drop in chat`, `share the damage`.
2. Use `switch_inline_query_chosen_chat` with query like `share_12345` or `m_12345`.
3. Update `search_inline()` so exact share queries return one result: the current meme as `InlineQueryResultCachedPhoto`.
4. Caption the inline result with a deep link like `https://t.me/<bot>?start=s_<user_id>_<meme_id>` so current invite/share attribution keeps working.
5. Track button exposure/clicks separately from chosen inline results if the CTA needs an experiment readout. `chosen_inline_result` tells us a result was sent; it does not measure every button tap.

Pros:

- Best match for "send this meme to a friend".
- Uses existing Telegram `telegram_file_id`; no public media hosting needed.
- Existing inline logs already track actual sends.

Cons:

- More Telegram UX steps than a URL button.
- Button tap itself is not observable because `switch_inline_query_chosen_chat` is not a callback button. We can measure impressions and chosen results, not taps.
- Requires exact-query support in `search_inline()` so `share_12345` returns only that meme.

Option C: Mini App feed.

Build a web TikTok-like feed in a Telegram Mini App and use it for richer sharing:

- Direct web feed: `https://t.me/<bot>?startapp=m_<meme_id>` can open a specific meme in the Mini App.
- Mini App can use `switchInlineQuery` to send the user back to inline mode with a specific meme query.
- For clients supporting prepared messages, backend can call `savePreparedInlineMessage`, then Mini App can call `Telegram.WebApp.shareMessage(prepared_message_id)` to open a native share dialog for that prepared media message.

Pros:

- Best long-term surface for feed UX, language correction, profiles, stats, upload review, and richer analytics.
- Can open exact meme experiences with web previews, not only bot messages.
- Gives us room for a real recommendation UI outside Telegram's message constraints.

Cons:

- Much larger product/engineering project.
- Needs web infra, auth validation, frontend, tracking, and media serving strategy.
- Still cannot silently send to a friend; Telegram keeps manual user confirmation.

Option D: copy link button.

- Bot API supports copy-text buttons.
- This is useful as fallback, but it adds manual paste friction and should not be the primary CTA.

Measurement:

- Randomize CTA text per message or per user and log the chosen variant.
- Primary metrics: inline chosen result rate per impression, deep-link starts from `s_%`, invited users, and downstream activation of invited users.
- Guardrails: like/skip rate, next-meme latency, and first-session depth. The share CTA must not distract from the core feed.

Experiment sketch:

- Treatment A: URL share deep link that opens the exact meme in the bot.
- Treatment B: inline share that sends the actual meme media.
- Control: current two-button keyboard.
- Rollout: 10-20% of users per treatment after exact-meme `/start s_...` handling is implemented.
- Primary success: treatment B increases `chosen_inline_result / meme_impressions`; treatment A increases `s_%` deep-link starts. Both must avoid drops in `nmemes_sent` or like/skip completion.
- Run by language segment, because CTA copy and sharing behavior likely differ between RU and EN users.

## Priority

1. Run text-density analysis first. It is low effort, uses existing OCR, and may improve cold start quickly.
2. Run language audience sizing next. This informs product focus and whether language recovery is worth building.
3. Prototype share CTA behind an experiment flag after choosing inline-share instrumentation. Sharing is likely high leverage, but the UX has more Telegram-specific edge cases than the data analyses.

## References

- Telegram Bot API: `InlineKeyboardButton`, `SwitchInlineQueryChosenChat`, `CopyTextButton`, inline mode, and cached photo results: https://core.telegram.org/bots/api
- Telegram inline bots guide: https://core.telegram.org/bots/inline
- Telegram share links: https://core.telegram.org/api/links#share-links
- Telegram Mini Apps: https://core.telegram.org/bots/webapps
- Telegram button behavior reference: https://core.telegram.org/api/bots/buttons
