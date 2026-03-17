"""
Single entry point for all Prefect scheduled flows.

Uses Prefect's .serve() pattern — no work pools, no workers, no deployment registration.
This script IS the scheduler and executor. Run it as a long-lived process.

Usage:
    python scripts/serve_flows.py
"""

from prefect import serve

# Broadcasts
from src.flows.broadcasts.meme import (
    broadcast_next_meme_to_active_1w_ago,
    broadcast_next_meme_to_active_2w_ago,
    broadcast_next_meme_to_active_4w_ago,
    broadcast_next_meme_to_active_15m_ago,
    broadcast_next_meme_to_active_24h_ago,
    broadcast_next_meme_to_active_48h_ago,
)

# Crossposting
from src.flows.crossposting.meme import (
    post_meme_to_tgchannelen,
    post_meme_to_tgchannelru,
)
from src.flows.parsers.ig import parse_ig_sources

# Parsers
from src.flows.parsers.tg import parse_telegram_sources
from src.flows.parsers.vk import parse_vk_sources

# Rewards
from src.flows.rewards.uploaded_memes import (
    reward_en_users_for_weekly_top_uploaded_memes,
    reward_ru_users_for_weekly_top_uploaded_memes,
)
from src.flows.stats.meme import calculate_meme_stats
from src.flows.stats.meme_source import calculate_meme_source_stats

# Stats
from src.flows.stats.user import calculate_user_stats
from src.flows.stats.user_meme_source import calculate_user_meme_source_stats

# Storage
from src.flows.storage.describe_memes import describe_memes_flow

# Watchdog
from src.flows.watchdog import watchdog

if __name__ == "__main__":
    serve(
        # ── Stats (every 15 min, staggered) ──
        calculate_user_stats.to_deployment(
            name="Calculate user_stats",
            cron="0,15,30,45 * * * *",
            timezone="Europe/London",
        ),
        calculate_meme_stats.to_deployment(
            name="Calculate meme_stats",
            cron="3,18,33,48 * * * *",
            timezone="Europe/London",
        ),
        calculate_meme_source_stats.to_deployment(
            name="Calculate meme_source_stats",
            cron="5,20,35,50 * * * *",
            timezone="Europe/London",
        ),
        calculate_user_meme_source_stats.to_deployment(
            name="Calculate user_meme_source_stats",
            cron="3,8,13,18,23,28,33,38,43,48,53,58 * * * *",
            timezone="Europe/London",
        ),
        # ── Parsers (hourly) ──
        parse_telegram_sources.to_deployment(
            name="Parse Telegram Sources",
            cron="40 * * * *",
            timezone="Europe/London",
        ),
        parse_vk_sources.to_deployment(
            name="Parse VK Sources",
            cron="20 * * * *",
            timezone="Europe/London",
        ),
        parse_ig_sources.to_deployment(
            name="Parse Instagram Sources",
            cron="30 0 * * *",
            timezone="Europe/London",
        ),
        # ── Broadcasts ──
        broadcast_next_meme_to_active_15m_ago.to_deployment(
            name="Broadcast 15m",
            cron="*/15 * * * *",
            timezone="Europe/London",
        ),
        broadcast_next_meme_to_active_24h_ago.to_deployment(
            name="Broadcast 24h",
            cron="5 * * * *",
            timezone="Europe/London",
        ),
        broadcast_next_meme_to_active_48h_ago.to_deployment(
            name="Broadcast 48h",
            cron="5 * * * *",
            timezone="Europe/London",
        ),
        broadcast_next_meme_to_active_1w_ago.to_deployment(
            name="Broadcast 1w",
            cron="7 * * * *",
            timezone="Europe/London",
        ),
        broadcast_next_meme_to_active_2w_ago.to_deployment(
            name="Broadcast 2w",
            cron="8 * * * *",
            timezone="Europe/London",
        ),
        broadcast_next_meme_to_active_4w_ago.to_deployment(
            name="Broadcast 4w",
            cron="9 * * * *",
            timezone="Europe/London",
        ),
        # ── Crossposting (Moscow timezone) ──
        post_meme_to_tgchannelru.to_deployment(
            name="Post to TG Channel RU",
            cron="20 8,10,12,14,16,18 * * *",
            timezone="Europe/Moscow",
        ),
        post_meme_to_tgchannelen.to_deployment(
            name="Post to TG Channel EN",
            cron="40 8,10,14,18,20 * * *",
            timezone="Europe/Moscow",
        ),
        # ── Rewards (weekly) ──
        reward_ru_users_for_weekly_top_uploaded_memes.to_deployment(
            name="Reward RU weekly",
            cron="0 19 * * 5",
            timezone="Europe/London",
        ),
        reward_en_users_for_weekly_top_uploaded_memes.to_deployment(
            name="Reward EN weekly",
            cron="0 18 * * 3",
            timezone="Europe/London",
        ),
        # ── Storage ──
        describe_memes_flow.to_deployment(
            name="Describe Memes (OpenRouter)",
            cron="*/30 * * * *",
            timezone="Europe/London",
        ),
        # ── Monitoring ──
        watchdog.to_deployment(
            name="Watchdog",
            cron="*/5 * * * *",
            timezone="Europe/London",
        ),
    )
