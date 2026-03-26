# Autoresearch Research

By Andrej Karpathy. Released March 6, 2026. MIT license. 44K GitHub stars.
Repo: github.com/karpathy/autoresearch

## What It Is
Minimal setup (3 files) for letting an AI agent autonomously run experiments.
Original: small GPT training on GPU. But the pattern generalizes to any domain.

## The 3 Files
1. `train.py` — the file agent can edit (model, optimizer, hyperparams)
2. `prepare.py` — READ-ONLY (data loading, eval function). Agent can't cheat.
3. `program.md` — the "skill"/prompt that tells agent what to do

## The Loop (runs forever)
1. Review current git state + history
2. Make ONE focused change
3. `git commit`
4. Run experiment (fixed time budget, e.g. 5 minutes)
5. Read metric from output
6. If improved: keep commit. If worse: `git reset`
7. Log to `results.tsv`
8. Repeat — never stop, never ask human

~12 experiments/hour → ~100 experiments per 8-hour sleep

## Generalized Version (Claude Code Skill)
Community: github.com/uditgoenka/autoresearch (1.5K stars)
Installs as `.claude/commands/autoresearch.md`

Skills provided:
- `/autoresearch` — core loop (unlimited or bounded by iterations)
- `/autoresearch:plan` — wizard to define Goal, Scope, Metric, Verify command
- `/autoresearch:debug` — autonomous bug hunting
- `/autoresearch:fix` — autonomous error fixing
- `/autoresearch:security` — STRIDE/OWASP audit
- `/autoresearch:ship` — shipping workflow

## Applying to ff-backend Meme Bot

### What We Need
- **Mechanical metric**: fast offline evaluation (not real user feedback)
- **Verify command**: `python evaluate_offline.py` → outputs single number
- **Scope constraint**: which files agent can modify
- **Time budget**: how long each eval takes

### Realistic Applications
1. **Ranking optimization** — iterate scoring functions using held-out reaction data
   - Metric: precision@10 on test set of user reactions
2. **Engine weight tuning** — autoresearch blender weights
   - Metric: simulated session length on historical data
3. **Content quality scoring** — iterate quality heuristics
   - Metric: correlation with actual like rate
4. **Test coverage** — keep adding tests
   - Metric: number of passing tests

### Prerequisite
Need to build an offline eval harness first:
- Hold out recent user reactions as test set
- Score candidate memes with current algorithm
- Measure hit rate (were liked memes ranked higher than disliked?)
- Must run fast (< 5 minutes)

## Honest Assessment
- NOT "autonomous research" — it's brute-force iteration with AI as code editor
- DOES work: 100 small experiments overnight > 5-10 manual experiments
- REQUIRES: fast eval loop + single clear metric
- WON'T: discover fundamentally new architectures
- WILL: find better hyperparameters, scoring weights, feature combinations
