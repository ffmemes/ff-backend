"""
Single entry point for all Prefect scheduled flows.

Uses Prefect's .serve() pattern — no work pools, no workers, no deployment registration.
This script IS the scheduler and executor. Run it as a long-lived process.

Usage:
    python scripts/serve_flows.py
"""

from prefect import serve
from prefect.client.schemas.schedules import CronSchedule

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

LON = "Europe/London"
MSK = "Europe/Moscow"

if __name__ == "__main__":
    serve(
        # ── Stats (every 15 min, staggered) ──
        calculate_user_stats.to_deployment(
            name="Calculate user_stats",
            schedules=[CronSchedule(cron="0,15,30,45 * * * *", timezone=LON)],
        ),
        calculate_meme_stats.to_deployment(
            name="Calculate meme_stats",
            schedules=[CronSchedule(cron="3,18,33,48 * * * *", timezone=LON)],
        ),
        calculate_meme_source_stats.to_deployment(
            name="Calculate meme_source_stats",
            schedules=[CronSchedule(cron="5,20,35,50 * * * *", timezone=LON)],
        ),
        calculate_user_meme_source_stats.to_deployment(
            name="Calculate user_meme_source_stats",
            schedules=[
                CronSchedule(
                    cron="3,8,13,18,23,28,33,38,43,48,53,58 * * * *",
                    timezone=LON,
                )
            ],
        ),
        # ── Parsers (hourly) ──
        parse_telegram_sources.to_deployment(
            name="Parse Telegram Sources",
            schedules=[CronSchedule(cron="40 * * * *", timezone=LON)],
        ),
        parse_vk_sources.to_deployment(
            name="Parse VK Sources",
            schedules=[CronSchedule(cron="20 * * * *", timezone=LON)],
        ),
        parse_ig_sources.to_deployment(
            name="Parse Instagram Sources",
            schedules=[CronSchedule(cron="30 0 * * *", timezone=LON)],
        ),
        # ── Broadcasts ──
        broadcast_next_meme_to_active_15m_ago.to_deployment(
            name="Broadcast 15m",
            schedules=[CronSchedule(cron="*/15 * * * *", timezone=LON)],
        ),
        broadcast_next_meme_to_active_24h_ago.to_deployment(
            name="Broadcast 24h",
            schedules=[CronSchedule(cron="5 * * * *", timezone=LON)],
        ),
        broadcast_next_meme_to_active_48h_ago.to_deployment(
            name="Broadcast 48h",
            schedules=[CronSchedule(cron="5 * * * *", timezone=LON)],
        ),
        broadcast_next_meme_to_active_1w_ago.to_deployment(
            name="Broadcast 1w",
            schedules=[CronSchedule(cron="7 * * * *", timezone=LON)],
        ),
        broadcast_next_meme_to_active_2w_ago.to_deployment(
            name="Broadcast 2w",
            schedules=[CronSchedule(cron="8 * * * *", timezone=LON)],
        ),
        broadcast_next_meme_to_active_4w_ago.to_deployment(
            name="Broadcast 4w",
            schedules=[CronSchedule(cron="9 * * * *", timezone=LON)],
        ),
        # ── Crossposting (Moscow timezone) ──
        post_meme_to_tgchannelru.to_deployment(
            name="Post to TG Channel RU",
            schedules=[
                CronSchedule(cron="20 8,10,12,14,16,18 * * *", timezone=MSK)
            ],
        ),
        post_meme_to_tgchannelen.to_deployment(
            name="Post to TG Channel EN",
            schedules=[
                CronSchedule(cron="40 8,10,14,18,20 * * *", timezone=MSK)
            ],
        ),
        # ── Rewards (weekly) ──
        reward_ru_users_for_weekly_top_uploaded_memes.to_deployment(
            name="Reward RU weekly",
            schedules=[CronSchedule(cron="0 19 * * 5", timezone=LON)],
        ),
        reward_en_users_for_weekly_top_uploaded_memes.to_deployment(
            name="Reward EN weekly",
            schedules=[CronSchedule(cron="0 18 * * 3", timezone=LON)],
        ),
        # ── Storage ──
        describe_memes_flow.to_deployment(
            name="Describe Memes (OpenRouter)",
            schedules=[CronSchedule(cron="*/30 * * * *", timezone=LON)],
        ),
        # ── Monitoring ──
        watchdog.to_deployment(
            name="Watchdog",
            schedules=[CronSchedule(cron="*/5 * * * *", timezone=LON)],
        ),
    )
