"""Unit tests for the performance report formatter.

The DB-backed helpers are covered by integration; these tests cover the
deterministic formatting layer.
"""

from datetime import datetime, timedelta

from src.comms.performance import (
    EditorialRow,
    format_channel_stats_report,
)


def _row(
    rid: int,
    days_ago: int,
    views: int,
    category: str = "C",
    entity: str | None = None,
    reactions: int = 0,
    reactions_detail: dict[str, int] | None = None,
    forwards: int = 0,
    text: str = "sample",
) -> EditorialRow:
    now = datetime(2026, 4, 24, 6, 0, 0)
    return EditorialRow(
        id=rid,
        channel="ru",
        created_at=now - timedelta(days=days_ago),
        category=category,
        entity_id=entity or f"ent_{rid}",
        topic_slug=f"slug-{rid}",
        text=text,
        views=views,
        forwards=forwards,
        reactions=reactions,
        reactions_detail=reactions_detail,
        telegram_message_id=1000 + rid,
    )


def test_format_empty_rows():
    out = format_channel_stats_report([], channel="ru", days=30, as_of=datetime(2026, 4, 24))
    assert "No editorial posts" in out
    assert "2026-04-24" in out


def test_format_reports_median_and_counts():
    rows = [_row(i, days_ago=i, views=100 + i * 10) for i in range(5)]
    out = format_channel_stats_report(rows, channel="ru", days=30, as_of=datetime(2026, 4, 24, 10))
    assert "Posts: 5" in out
    assert "Median views: 120" in out


def test_format_top_views_sorted_desc():
    rows = [_row(1, 1, 50), _row(2, 2, 500), _row(3, 3, 200)]
    out = format_channel_stats_report(rows, channel="ru", days=30, as_of=datetime(2026, 4, 24, 10))
    top_section = out.split("## Top 5 by views")[1].split("##")[0]
    lines = [line for line in top_section.splitlines() if line.startswith("-")]
    # First bullet should be the 500-view row.
    assert "500" in lines[0]
    assert "200" in lines[1]
    assert "50" in lines[2]


def test_format_weakest_excludes_fresh():
    # Fresh (<24h old) post with 0 views should NOT show in weakest — we can't
    # judge yet.
    fresh = _row(1, days_ago=0, views=0, text="fresh post")
    mature_low = _row(2, days_ago=5, views=20, text="mature low")
    mature_high = _row(3, days_ago=4, views=500, text="mature high")
    out = format_channel_stats_report(
        [fresh, mature_low, mature_high],
        channel="ru",
        days=30,
        as_of=datetime(2026, 4, 24, 10),
    )
    weakest = out.split("## Weakest 3")[1].split("##")[0]
    assert "mature low" in weakest
    assert "fresh post" not in weakest


def test_format_reaction_mix_top5():
    rows = [
        _row(1, 1, 100, reactions_detail={"🔥": 10, "❤": 5}),
        _row(2, 2, 100, reactions_detail={"🔥": 4, "👍": 3, "😁": 2}),
        _row(3, 3, 100, reactions_detail={"💩": 1}),
    ]
    out = format_channel_stats_report(rows, channel="ru", days=30, as_of=datetime(2026, 4, 24, 10))
    section = out.split("## Reaction mix")[1].split("##")[0]
    assert "🔥 × 14" in section
    assert "❤ × 5" in section


def test_format_rotation_keys_last_7():
    rows = [_row(i, days_ago=i, views=50, category="C", entity=f"e{i}") for i in range(10)]
    out = format_channel_stats_report(rows, channel="ru", days=30, as_of=datetime(2026, 4, 24, 10))
    section = out.split("## Last 7")[1].split("##")[0]
    # First 7 entities should appear.
    for i in range(7):
        assert f"e{i}" in section
    # 8th should not.
    assert "e8" not in section


def test_format_strips_html_from_preview():
    rows = [_row(1, 1, 100, text="<b>жир</b> и <i>курсив</i>")]
    out = format_channel_stats_report(rows, channel="ru", days=30, as_of=datetime(2026, 4, 24, 10))
    assert "<b>" not in out
    assert "жир и курсив" in out
