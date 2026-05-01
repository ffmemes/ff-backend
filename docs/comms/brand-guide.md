# Brand Guide — FFmemes

Minimal visual identity. Iterate after 10+ posts.

## Name

- Full: **Fast Food Memes**
- Short: **FFmemes**
- Bot: **@ffmemesbot**
- Channel (RU build-in-public): **@ffmemes** (t.me/ffmemes)
- Channel (RU main meme channel): **@fastfoodmemes** (t.me/fastfoodmemes)
- Channel (EN): **@fast_food_memes** (t.me/fast_food_memes)

## Logo

Hamburger avatar. Used on:
- @ffmemesbot Telegram bot
- @ffmemes Telegram channel
- @fastfoodmemes Telegram channel
- Paperclip company profile

No SVG/PNG file exists yet. Source: Telegram avatar.

## Typography

- **Primary**: Work Sans Medium (used in watermarks, `src/storage/watermark.py`)
- **Posts**: System fonts (Telegram renders text natively)
- **Charts**: Work Sans or system sans-serif

## Color Palette

Derived from the hamburger. Use these for charts, diagrams, infographics.

| Name | Hex | Usage |
|------|-----|-------|
| Bun (primary) | `#FF6B35` | Primary accent, chart highlights, headers |
| Dark | `#1A1A2E` | Chart backgrounds, text on light |
| Positive | `#4CAF50` | Likes, growth, success |
| Negative | `#E74C3C` | Dislikes, drops, alerts |
| Neutral | `#95A5A6` | Muted elements, axes, borders |
| Light | `#F5F5F5` | Chart backgrounds (light mode) |

### Chart palette (for matplotlib/PIL)

```python
BRAND_COLORS = {
    "primary": "#FF6B35",
    "dark": "#1A1A2E",
    "positive": "#4CAF50",
    "negative": "#E74C3C",
    "neutral": "#95A5A6",
    "light": "#F5F5F5",
}

# For multi-series charts
CHART_SERIES = ["#FF6B35", "#4CAF50", "#3498DB", "#9B59B6", "#E74C3C"]
```

## Tone of Voice

Full reference: https://github.com/ohld/dania-zip

Key rules:
- Russian language (always)
- No greetings ("Привет, друзья!" is forbidden)
- Hook first — first 1-2 lines grab attention
- Emoji bullets only (structural, not decorative). Max 1-3 per post
- One thought per line. Short sentences.
- Max 15-25 lines. Cut aggressively.
- First person: "Я сделал", "Вот что узнал"
- Shows process, not just result
- Casual, like talking to a friend who codes
- Never corporate, never dry
- RU-EN tech term mixing: "навайбкодить", "рисерчить"

Anti-patterns (NEVER):
- "Привет, друзья!" or any greeting
- "В рамках данной статьи", "мы рады сообщить" (corporate)
- Numbered lists (1. 2. 3.) — use emoji bullets
- Humble-bragging
- Hedging: ИМХО, наверное, мне кажется
- "Давайте разберёмся"

Signature patterns:
- "И ХОБА" — surprise twist
- `~ @danokhlopkov ~` — post signature
- Casual: мб, кмк, хз, кайф, жиза, го, чел

## Visual Post Formats

Every post must include an image. Types:

### 1. Bot Screenshots
For feature spotlights. Take via browse skill or manually.
- Crop to relevant area
- No personal data visible

### 2. Memes from DB
For "meme of the day/week". Already watermarked with @ffmemesbot.
- Pick memes that metaphorically relate to the post topic
- Use the meme's telegram_file_id to send directly

### 3. Charts
For data posts. **Use the `src/comms/visuals.py` primitives — do NOT write raw matplotlib.**

The primitives enforce the brand constraints below automatically:

```python
from src.comms.visuals import stat_slide, line_chart, bar_chart

# One number → slide-deck style
png = stat_slide("Сессия сегодня", "24.7 мем", subtitle="медиана за 7 дней")

# Time series (2-20 points)
png = line_chart(dates, values, title="DAU 7d", accent_x=today)

# Categorical (2-10 bars, highlight one)
png = bar_chart(labels, values, title="Top sources", highlight_idx=0, horizontal=True)
```

**Design constraints (hard rules, violated = reject the image):**

- **Max 3 numbers per image.** If you can't fit the story in 3 numbers, the story is too complicated for one post.
- **One accent color per image.** Brand primary `#FF6B35` points to ONE thing (today's value, winner bar, anomaly). Rest in neutral grey `#95A5A6`.
- **WorkSans font only.** Never Arial Black, Comic Sans, or matplotlib's default.
- **No chart junk.** No top/right spines, no gridlines (unless strictly needed for trend reading), no legend unless series ≥ 3.
- **Decision tree for visual type:**
  - 1 number → `stat_slide()`
  - 2-20 time-series points → `line_chart()` (bucket or sample if > 20)
  - 2-10 categorical bars → `bar_chart()` (collapse to top-10 if > 10)
  - Never: pie charts, 3D, stacked-everything, dual-axis. Banned.
- **Text density.** Titles ≤ 6 words. Axis labels only when the unit isn't obvious.
- **Background.** Dark (`#1A1A2E`) for stat_slide; light (`#F5F5F5`) for charts. Don't mix.

If an idea needs something beyond these primitives, flag it to CTO — don't improvise raw matplotlib.

### 4. Diagrams
For engineering/architecture posts.
- Simple, clean lines
- Brand colors
- Max 5-7 elements (don't overwhelm)

### 5. Stat Cards
For daily pulse posts (C6).
- Single big number + context
- Brand primary color accent
- Clean, minimal design

## Watermark

Existing implementation in `src/storage/watermark.py`:
- Text: "@ffmemesbot"
- Font: Work Sans Medium, 5% of image width
- Placement: least-detailed corner (smart algorithm)
- Opacity: 35%
- Auto contrast: white on dark, black on light
