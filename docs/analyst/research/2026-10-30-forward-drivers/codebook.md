# Meme labeling codebook (v1, 2026-10-30)

Label ONLY from the image. You do not know how the meme performed. Output one JSON object per line (JSONL), exactly these keys:

| key | values | meaning |
|---|---|---|
| meme_id | int | from the filename |
| format | `single_caption` \| `multi_panel` \| `tweet_screenshot` \| `chat_screenshot` \| `photo_no_text` \| `drawing_comic` \| `other` | dominant visual format |
| text_lang | `ru` \| `en` \| `mixed` \| `none` | language of text in the image (ignore the @ffmemesbot watermark) |
| text_len | `none` \| `short` (<10 words) \| `medium` (10–40) \| `long` (>40) | |
| topics | list, 1–3 of: `romance_couple`, `friendship`, `family_parents`, `work_office`, `school_study`, `it_programming`, `gaming`, `politics_news`, `animals`, `food`, `money_prices`, `russia_everyday`, `internet_culture`, `health_body`, `sex`, `holidays_seasonal`, `pop_culture_movies`, `other` | what it's about |
| humor | list, 1–2 of: `relatable`, `absurd`, `wordplay_pun`, `dark`, `vulgar`, `wholesome`, `irony_sarcasm`, `niche_reference`, `visual_gag` | humor mechanism |
| addressable | 0 \| 1 | 1 if a typical viewer would likely send it to a SPECIFIC person ("this is us", "you do this", tag-a-friend, couple/friend/family dynamics) |
| addressee | `partner` \| `friend` \| `family` \| `coworker` \| `group_chat` \| `none` | who they'd send it to (none if addressable=0) |
| needs_context | 0 \| 1 | 1 if it needs niche knowledge (specific game, programming, a news event, subculture) to get |
| timely | 0 \| 1 | tied to a current event/date (news, holiday, season) |
| vulgarity | 0 \| 1 \| 2 | 0 clean, 1 mild innuendo/swearing, 2 explicit/crude |
| valence | `positive` \| `negative` \| `neutral` | emotional tone |
| quality | `low` \| `ok` \| `high` | visual quality/readability |
| foreign_watermark | 0 \| 1 | another channel's watermark/username visible |
| forward_score | 1–5 | YOUR prediction: how likely a Russian-speaking 18–35 Telegram user would forward this to someone (5 = very likely) |
| desc | string ≤15 words, English | what's in it |

Rules: be consistent, decide quickly (~10s per image), don't skip images — if unreadable set quality=low and best guesses.
