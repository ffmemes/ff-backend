# Growth and recommendation practice at tiny scale (research note, 2026-10-30)

Question: what do primary sources say about (1) deciding experiments faster with
~430 weekly active reactors, (2) predicting which memes get shared/forwarded,
(3) Telegram-native growth loops and first-session practice, and (4) exploring
new sources without repeatedly serving bad ones?

Population assumed (public numbers only): ~430 weekly reactors, ~140k memes
sent/week, heavy users ~300 reactions/week, ~20–35 new users/week.

Applicability tags: **[strong]** works at our scale as-is · **[adapt]** works
with changes · **[weak]** mostly a big-platform result, use as direction only.

---

## 1. Experimentation at tiny scale

### 1.1 Why user-level A/B tests stall here

Rule of thumb (Kohavi et al.): `n per arm ≈ 16·σ²/δ²` at α=0.05, 80% power
([arXiv 2405.03579](https://arxiv.org/pdf/2405.03579) derives the constant;
Kohavi notes it becomes 24 at α=0.01). Rewritten with a relative effect `r`
and per-user coefficient of variation `CV`: `n ≈ 16·CV²/r²`.

Illustrative (CV values are assumptions; heavy-tailed engagement metrics are
typically CV ≥ 1):

| per-user CV | MDE with ~215 users/arm | with CUPED, ρ=0.7 |
|---|---|---|
| 1.0 | ~27% | ~20% |
| 1.5 | ~41% | ~29% |
| 2.0 | ~55% | ~39% |

So a 50/50 user-split test on memes-per-session or reactions/user can only see
effects of roughly +30–50%. New-user metrics (20–35/week) are worse: months
per decision. This matches the "undecided for weeks" symptom. **[strong]**

### 1.2 Change the unit: compare at the impression level, within user (interleaving)

- Netflix: team-draft interleaving reached 95% power with **>100× fewer users**
  than their most sensitive A/B metric, and its preference metric correlated
  strongly with A/B outcomes. Limitation: it gives only a relative preference
  between rankers, not retention; Netflix runs a confirmatory A/B after.
  ([Netflix Tech Blog](https://netflixtechblog.com/interleaving-in-online-experiments-at-netflix-a04ee392ec55))
- Chapelle, Joachims, Radlinski, Yue (TOIS 2012): interleaving agreed with
  A/B outcomes on Yahoo/Bing data and needed roughly 20–400× less data
  depending on effect size (figure as summarised secondary; see
  [DOI 10.1145/2094072.2094078](https://doi.org/10.1145/2094072.2094078)).

Fit for the feed blender: the blender already mixes engines per user and can
log which engine produced each meme. That is structurally an interleaved
(multileaved) design: every user sees both arms, so between-user variance
cancels. Compare arms on per-impression outcomes (like rate, share rate,
"session continued after this meme") within user.

Back-of-envelope (assumption: like rate ≈ 0.3, 70k impressions/arm/week):
naive MDE ≈ 0.7 pp (~2% relative). Impressions cluster by user; with ~300
impressions/user and intra-user correlation 0.05 the design effect is ~16, so
the honest MDE is ~2.7 pp (~9% relative) per week. That is 3–5× more sensitive
than the user-split test and decides in about a week. Use user-level bootstrap
or cluster-robust SEs, never naive per-impression SEs. **[strong]**

Caveat: per-item metrics miss session-level effects (fatigue, churn). Treat
interleaving as the fast filter and only run user-split tests for changes
that alter session structure (queue length, onboarding, push cadence).

### 1.3 Off-policy evaluation from logged randomisation

Li, Chu, Langford, Wang (WSDM 2011) "replay": if the serving policy picks
among candidates **at random with known probabilities**, logged data gives an
unbiased offline estimate of any other policy, validated against online bucket
tests on Yahoo! Front Page.
([arXiv 1003.5956](https://arxiv.org/abs/1003.5956))

Fit: log the blend probabilities per slot (engine weights at serve time) plus
the chosen engine. Then any new weight vector can be scored offline via
inverse-propensity weighting before shipping it. Requires the blender to
sample engines stochastically (not deterministic round-robin) and to keep a
small floor probability per engine. **[adapt]**

### 1.4 CUPED / variance reduction

Deng, Xu, Kohavi, Walker (WSDM 2013): using the same metric from the
pre-experiment period as a covariate cut variance ~50% on Bing, i.e. same
power with half the users or duration
([exp-platform.com/cuped](https://exp-platform.com/cuped/)). Statsig/others
note it gives nothing for users without history
([Statsig docs](https://docs.statsig.com/stats-engine/variance_reduction)).

Fit: cheap, always apply to existing-user tests (weekly reactions are highly
autocorrelated for heavy users). Useless for new-user/onboarding tests.
Gain ≈ 1/(1−ρ²); at ρ=0.7 that is ~2× sample efficiency. **[strong]**

### 1.5 Sequential testing

Spotify uses group sequential tests with Lan–DeMets alpha spending; their
comparison found GSTs have better power than always-valid inference when a
max sample size can be set
([Spotify Engineering, 2023](https://engineering.atspotify.com/2023/3/choosing-sequential-testing-framework-comparisons-and-discussions)).

Fit: sequential testing lets you **stop early on big effects** and stops
peeking from inflating false positives, but it does not create power you
don't have. Its main value here is discipline: set a max horizon (e.g. 4
weeks), and at the horizon declare "no detectable effect ≥ X%" and ship the
simpler variant instead of letting tests sit. **[strong as process, weak as power gain]**

### 1.6 Bandits for blender weights

- Chapelle & Li (NeurIPS 2011): Thompson sampling is simple and
  competitive on Yahoo ads and news recommendation; recommended as a baseline
  ([paper](https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html)).
- Russo et al. tutorial, Beta–Bernoulli TS
  ([arXiv 1707.02038](https://arxiv.org/abs/1707.02038)).
- Spotify BaRT: contextual bandit on home shelves, significant engagement
  gains in production ([RecSys 2018, DOI 10.1145/3240323.3240354](https://doi.org/10.1145/3240323.3240354)).
- Statsig: bandits suit maximising a single stable metric with many arms;
  A/B is better when you need a reusable learning
  ([Statsig Autotune](https://statsig.com/blog/introducing-autotune)).

Fit: blender engine weights are a textbook non-contextual bandit — the reward
(like per impression) is observed within seconds and there are ~140k pulls a
week. Beta–Bernoulli TS per engine (optionally per user segment such as
new/heavy) will converge in days. Requirements: (a) a floor weight per engine
so arms keep getting data, (b) discounting/sliding window because engine
quality drifts with content supply, (c) the reward must be the north-star
proxy, not just likes, or the bandit will learn to serve safe, unshareable
memes. Bandit outcomes are not clean causal estimates; keep interleaving logs
for learning. **[strong]**

### 1.7 Switchback

DoorDash uses region×time switchbacks for marketplace interference but notes
low power and carryover
([DoorDash engineering](https://careers.doordash.com/blog/author/davidkastelman)).

Fit: the feed has no cross-user interference, so switchbacks add nothing
there. For the **channel post picker** the unit is a post slot: alternating
pickers by slot is a switchback. With a few dozen posts per arm per month and
overdispersed forward counts, only ~2× effects are detectable. Better:
evaluate pickers offline on in-bot engagement of candidates (section 2) and
use the channel only as a slow confirmation. **[weak]**

### Decision guide

| change | method |
|---|---|
| engine weights / new engine | Thompson sampling with floor + logged propensities |
| ranking change inside an engine | interleave vs current, per-impression within-user metric |
| session structure, onboarding, pushes | user split + CUPED + group sequential with a hard max horizon |
| channel picker | offline score on in-bot engagement; slot alternation only to confirm large effects |

---

## 2. Predicting shares / forwards before publishing

- **Early engagement is the strongest predictor.** Szabo & Huberman: log of
  early popularity predicts log of later popularity linearly; Digg stories
  needed 2 hours of data to forecast 30-day popularity, YouTube 10 days
  ([arXiv 0811.0405](https://arxiv.org/abs/0811.0405)). Cheng et al. (WWW
  2014): on Facebook photo cascades, speed of early sharing was the best
  feature; predicting whether a cascade doubles ~80% accurate
  ([arXiv 1403.4608](https://arxiv.org/abs/1403.4608)). **[strong]** — the
  bot is a built-in pre-publication panel: in-bot like and share rates on a
  meme are the "early views" for the channel.
- **There is a hard ceiling.** Martin, Hofman, Sharma, Anderson, Watts (WWW
  2016): the best Twitter cascade models explain < 50% of variance, and
  simulations put the theoretical limit well below 1
  ([arXiv 1602.01013](https://arxiv.org/abs/1602.01013)). Salganik, Dodds,
  Watts (Science 2006): with social influence, the best items rarely fail and
  the worst rarely win, but anything in between is unpredictable
  ([PDF](https://pdodds.w3.uvm.edu/research/papers/years/2006/salganik2006a.pdf)).
  Implication: rank by a quality gate + early engagement, don't over-invest in
  content-only models. **[strong]**
- **Content features for image memes.** Ling et al. (CSCW 2021): close-up
  framing, presence of characters and clear emotion predict re-sharing;
  memes without a focal subject or with long text are shared less
  ([arXiv 2101.06535](https://arxiv.org/abs/2101.06535)). Small annotated set
  (100 memes, 4chan /pol/), so treat as hints. OCR text length is a cheap
  feature we already have. **[adapt]**
- **Emotion/arousal.** Berger & Milkman (JMR 2012): high-arousal content (awe,
  anger, anxiety, amusement-adjacent) is shared more; low-arousal (sadness)
  less ([PDF](https://faculty.wharton.upenn.edu/wp-content/uploads/2011/11/Virality.pdf)).
  **[weak]** for memes (news articles), but consistent with Ling et al.
- **Telegram forwards specifically.** No primary paper found that predicts
  Telegram channel-post forwards. Telegram's own channel stats expose views
  and new followers **by source** (forwards, links, search) via
  `stats.broadcastStats` ([Telegram API: channel statistics](https://core.telegram.org/api/stats)),
  which is the ground truth to calibrate any picker against. Telegram's view
  counts are approximate and include forwarded copies. Gap: evidence here is
  missing, not negative.

Practical picker: score = posterior lower bound of in-bot share (or like)
rate after ≥ N impressions, × recency, gated by source prior; tune N on
history by checking rank correlation of in-bot rates with channel
forwards/views.

---

## 3. Growth loops for Telegram bots and meme apps

Primary-source evidence on what *drives* acquisition for Telegram bots is thin;
most "growth loop" literature is practitioner blogs. What primary sources do
establish is the mechanics:

- **Deep links with payload**: `t.me/bot?start=<payload>`, payload `A-Za-z0-9_-`,
  up to 64 chars; `startgroup` prompts adding the bot to a group
  ([Bot features](https://core.telegram.org/bots/features#deep-linking)).
  Every shared meme can carry a referrer + meme id so the new user's first
  meme is the shared one (and the share is attributable). **[strong]**
- **Inline mode**: users type `@bot query` in any chat; sent messages show
  the bot's username next to the sender, and typing `@` suggests recently
  used inline bots — attribution is built in. `/setinlinefeedback` gives
  `ChosenInlineResult` updates (sampled 1/10–1/1000 if needed) to count shares
  ([Inline bots](https://core.telegram.org/bots/inline)). **[strong]**
- **Share buttons**: `switch_inline_query` / `switch_inline_query_chosen_chat`
  open a chat picker and pre-fill an inline query, so a "send to friend"
  button under a meme becomes an inline send with "via @bot" attribution and
  a trackable chosen result
  ([Bot API: InlineKeyboardButton](https://core.telegram.org/bots/api#inlinekeyboardbutton),
  [SwitchInlineQueryChosenChat](https://core.telegram.org/bots/api#switchinlinequerychosenchat)).
  Plain `t.me/share/url?url=…&text=…` also works but carries no media
  ([Share widget](https://core.telegram.org/widgets/share)). **[strong]**
- **Mini Apps**: `savePreparedInlineMessage` + `shareMessage` let a Mini App
  share a bot-prepared message
  ([Bot API: PreparedInlineMessage](https://core.telegram.org/bots/api#preparedinlinemessage)).
  Only relevant if a Mini App surface exists. **[weak]**
- **Channel reactions**: bots that admin a chat can receive
  `message_reaction_count` updates (grouped, delayed minutes) — usable as a
  channel-side early signal ([Bot API](https://core.telegram.org/bots/api)).
- **Telegram does not expose share counts** for plain forwards of bot
  messages; only the inline path and deep-link payloads are measurable.

First session / cold start:
- Pinterest Growth ran 20+ new-user signal experiments; *when* a signal is
  asked mattered — adding a gender step increased onboarding completion 11%
  ([Pinterest Engineering, 2018](https://medium.com/@Pinterest_Engineering/exploring-effective-user-signals-585507d8e926));
  personalising the new-user experience abroad lifted activation/retention
  5–10% ([Pinterest Engineering, 2016](https://medium.com/pinterest-engineering/personalizing-pinterests-new-user-experience-abroad-60f8f55177ac)).
  **[adapt]** — direction: get to a good meme instantly, ask nothing up front,
  and use the deep-link payload as the first signal.
- With 20–35 new users/week, onboarding changes cannot be A/B tested to
  significance in reasonable time (§1.1). Ship changes that are obviously
  better by inspection (fewer steps, best-known memes first) and monitor
  before/after; reserve tests for risky changes.

---

## 4. Exploration vs exploitation over sources

- Google/YouTube (Chen et al., RecSys 2021): exploration has measurable user
  value beyond long-term learning, improving corpus coverage/novelty and user
  experience in live experiments
  ([DOI 10.1145/3460231.3474236](https://doi.org/10.1145/3460231.3474236)).
  **[weak]** scale, but supports reserving traffic for exploration.
- YouTube "Fresh content needs more attention" (KDD 2023): a dedicated
  fresh-content funnel with uncertainty-aware ranking gives new items a
  bounded slot instead of competing with mature items
  ([arXiv 2306.01720](https://arxiv.org/abs/2306.01720)). **[adapt]** — a
  fixed exploration slot share (e.g. 5–10% of feed slots) for new sources.
- Thompson sampling at source level (Chapelle & Li; Russo et al. above):
  Beta(likes+α, skips+β) per source, prior from global/source-type average;
  sample to pick which source fills the exploration slot. Bad sources stop
  getting traffic after a few hundred impressions automatically; new sources
  start at the prior, not at zero. **[strong]**

Concrete pattern that matches all three:
1. Quality gate first (dedup, OCR/describe checks, moderator flags) — the
   Salganik result says the bottom tail is predictable, so cut it hard.
2. Exploration slot with a capped share; within it, source-level TS.
3. Per-source impression budget: after K impressions (K≈200–300 gives a
   ±~6pp 95% interval on a 0.3 like rate) a source graduates into normal
   engines or is snoozed. Use posterior probability "worse than median by
   >X" rather than raw rate to snooze.
4. Discount old evidence (sliding window) so a source that improved can
   return.
5. Serve exploration traffic preferentially to heavy users (more tolerant,
   more signal per user) and keep new users on proven content — this
   protects the first session.

---

## Gaps and confidence

- No primary source on Telegram-forward prediction or on measured Telegram bot
  acquisition loops; §3 growth claims are mechanics, not effect sizes.
- Chapelle et al. 20–400× figure is from a secondary summary of the paper.
- Sample-size table uses assumed CVs and ρ; recompute with real per-user
  variance before relying on it.
