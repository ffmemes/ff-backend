"""Non-crash tests for comms visual primitives. Verifies edge cases don't explode."""

import pytest

from src.comms.visuals import BRAND, bar_chart, line_chart, stat_slide


def _is_png(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n"


def test_stat_slide_basic():
    png = stat_slide("Total users", "22,143", subtitle="За всё время")
    assert _is_png(png)
    assert len(png) > 1000


def test_stat_slide_unicode():
    png = stat_slide("Пользователи", "22K", subtitle="а также: эмодзи 🔥 и кавычки «ёлочки»")
    assert _is_png(png)


def test_stat_slide_empty_value_raises():
    with pytest.raises(ValueError):
        stat_slide("Title", "")


def test_stat_slide_empty_title_raises():
    with pytest.raises(ValueError):
        stat_slide("", "42")


def test_stat_slide_custom_accent():
    png = stat_slide("Drop", "-18%", subtitle="неделя к неделе", accent=BRAND["negative"])
    assert _is_png(png)


def test_line_chart_basic():
    png = line_chart(
        x=list(range(1, 8)),
        y=[12, 14, 13, 19, 22, 18, 25],
        title="DAU, последние 7 дней",
        xlabel="день",
        ylabel="пользователи",
    )
    assert _is_png(png)


def test_line_chart_accent_highlights_last_point():
    png = line_chart(
        x=[1, 2, 3, 4, 5],
        y=[10.0, 12.0, 11.0, 15.0, 18.0],
        title="Trend",
        accent_x=5,
    )
    assert _is_png(png)


def test_line_chart_single_point():
    png = line_chart(x=[1], y=[42.0], title="Solo")
    assert _is_png(png)


def test_line_chart_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        line_chart(x=[1, 2, 3], y=[1.0, 2.0], title="bad")


def test_line_chart_empty_raises():
    with pytest.raises(ValueError):
        line_chart(x=[], y=[], title="empty")


def test_line_chart_too_many_points_raises():
    x = list(range(25))
    y = [float(i) for i in x]
    with pytest.raises(ValueError, match="bucket or sample"):
        line_chart(x=x, y=y, title="too many")


def test_bar_chart_basic():
    png = bar_chart(
        labels=["A", "B", "C", "D"],
        values=[10, 25, 17, 8],
        title="Sources by like rate",
        highlight_idx=1,
    )
    assert _is_png(png)


def test_bar_chart_horizontal():
    png = bar_chart(
        labels=["Long source name 1", "Source 2", "Third"],
        values=[0.72, 0.61, 0.54],
        title="Top 3",
        horizontal=True,
    )
    assert _is_png(png)


def test_bar_chart_unicode_labels():
    png = bar_chart(
        labels=["русский", "english", "español"],
        values=[45, 35, 20],
        title="Языки",
        highlight_idx=0,
    )
    assert _is_png(png)


def test_bar_chart_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        bar_chart(labels=["a", "b"], values=[1], title="bad")


def test_bar_chart_too_many_bars_raises():
    with pytest.raises(ValueError):
        bar_chart(labels=[str(i) for i in range(15)], values=list(range(15)), title="too wide")


def test_bar_chart_empty_raises():
    with pytest.raises(ValueError):
        bar_chart(labels=[], values=[], title="empty")


def test_bar_chart_highlight_out_of_range_ignored():
    png = bar_chart(labels=["a", "b"], values=[1, 2], title="ok", highlight_idx=99)
    assert _is_png(png)
