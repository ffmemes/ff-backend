# Experiment: Viral shares blender v1

Created: 2026-08-09  
Status: active  
Owner: engineer / analyst  
Deployed: pending merge  
Measure after: +7 days and sample_gate_per_variant ≥ 1000

## Hypothesis

Injecting a dedicated `viral_shares` engine (memes ranked by share-click conversion)
into the mature blend at weight 0.2 (stolen from `lr_smoothed`) increases unique
share clickers and new-user invites per 1k memes sent without reducing session depth.

## Changes Made

- Engine: `src/recommendations/candidates.py::viral_shares`
- Experiment: `viral_shares_blender_v1` in `src/recommendations/blender_experiments.py`
- Wiring: mature path uses `get_mature_blend_weights_with_experiments` (recently_liked v2 base + viral overlay)
- Delivery prep seam: `src/tgbot/senders/delivery.py` (shared by `next_message` + `send_meme_to_user`)
- Crosspost fix: share-click CTEs accept both `m_` and `s_` deep links

## Assignment

- Eligible: mature users via existing mature blend path (`nmemes_sent ≥ 100`)
- Strategy: `sha256(experiment_id:user_id) % 2`
- Control: base mature weights (after recently_liked v2 assignment)
- Treatment: base + `viral_shares: 0.2`, `lr_smoothed` reduced by 0.2
- Sample gate: 1000 users/variant before day-7 read

## Primary metrics

1. Unique non-self share clickers (`user_deep_link_log` m_/s_) per 1k memes sent
2. New-user invites (`user.inviter_id` attributed in window) per 1k memes sent

## Guardrails

- Median / p50 session length (memes with reaction gap < 30 min)
- Like rate (7d)
- Block rate

## Engine slice

Where `recommended_by = 'viral_shares'`: continuation rate vs `lr_smoothed`.

## Readout SQL

See `docs/analyst/viral-shares-blender-v1.sql`.
