"""
Brand-styled matplotlib primitives for Comms Agent posts.

Agent composes on-the-fly by calling these primitives instead of writing raw
matplotlib. This enforces the brand constraints uniformly: palette, typography,
no chart junk. See docs/comms/brand-guide.md for the design rules.
"""

from __future__ import annotations

import io
from typing import Sequence

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

matplotlib.use("Agg")

BRAND = {
    "primary": "#FF6B35",
    "dark": "#1A1A2E",
    "positive": "#4CAF50",
    "negative": "#E74C3C",
    "neutral": "#95A5A6",
    "light": "#F5F5F5",
}

CANVAS_LIGHT = BRAND["light"]
CANVAS_DARK = BRAND["dark"]

DEFAULT_DPI = 160
DEFAULT_SIZE_IN = (6.25, 4.25)  # 1000x680 @ 160dpi
STAT_SIZE_IN = (6.25, 4.25)

FONT_CANDIDATES = ["Work Sans", "Helvetica Neue", "Arial", "DejaVu Sans"]


def _pick_font() -> str:
    """Pick the first available font from the candidate list."""
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_CANDIDATES:
        if name in available:
            return name
    return "DejaVu Sans"


def apply_brand_style(fig: Figure, ax, dark: bool = False) -> None:
    """
    Apply FFmemes brand styling to an existing figure/axes.

    Removes chart junk, sets palette, sets fonts. Call once per figure after
    plotting.
    """
    font = _pick_font()
    bg = CANVAS_DARK if dark else CANVAS_LIGHT
    fg = CANVAS_LIGHT if dark else CANVAS_DARK
    muted = BRAND["neutral"]

    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)

    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(muted)
        ax.spines[spine].set_linewidth(0.8)

    ax.tick_params(colors=fg, which="both", labelsize=10, length=0)
    ax.grid(False)

    for label in (ax.title, ax.xaxis.label, ax.yaxis.label):
        label.set_color(fg)
        label.set_fontname(font)
    for tl in ax.get_xticklabels() + ax.get_yticklabels():
        tl.set_fontname(font)
        tl.set_color(fg)

    if ax.title.get_text():
        ax.title.set_fontsize(16)
        ax.title.set_fontweight("semibold")
        ax.title.set_y(1.04)


def _figure_to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DEFAULT_DPI, bbox_inches="tight", pad_inches=0.35)
    plt.close(fig)
    return buf.getvalue()


def stat_slide(
    title: str,
    value: str,
    subtitle: str = "",
    *,
    dark: bool = True,
    accent: str | None = None,
) -> bytes:
    """
    Slide-deck-style single-number image.

    Use when the post is about ONE number. Title on top, big number in the
    middle, optional subtitle underneath.
    """
    if not title or not value:
        raise ValueError("stat_slide requires non-empty title and value")

    accent = accent or BRAND["primary"]
    bg = CANVAS_DARK if dark else CANVAS_LIGHT
    fg = CANVAS_LIGHT if dark else CANVAS_DARK
    font = _pick_font()

    fig, ax = plt.subplots(figsize=STAT_SIZE_IN)
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.axis("off")

    ax.text(
        0.5,
        0.82,
        title,
        ha="center",
        va="center",
        fontsize=18,
        color=fg,
        fontname=font,
        fontweight="medium",
        transform=ax.transAxes,
    )
    ax.text(
        0.5,
        0.48,
        value,
        ha="center",
        va="center",
        fontsize=96,
        color=accent,
        fontname=font,
        fontweight="bold",
        transform=ax.transAxes,
    )
    if subtitle:
        ax.text(
            0.5,
            0.18,
            subtitle,
            ha="center",
            va="center",
            fontsize=14,
            color=BRAND["neutral"],
            fontname=font,
            transform=ax.transAxes,
            wrap=True,
        )

    return _figure_to_png(fig)


def line_chart(
    x: Sequence,
    y: Sequence[float],
    title: str,
    *,
    accent_x=None,
    xlabel: str = "",
    ylabel: str = "",
    dark: bool = False,
) -> bytes:
    """
    Clean line chart. Use for time series (2-20 points).

    If accent_x is provided and is in x, that point is highlighted in brand
    primary with a value annotation.
    """
    if len(x) != len(y):
        raise ValueError(f"x/y length mismatch: {len(x)} vs {len(y)}")
    if not x:
        raise ValueError("line_chart requires at least one data point")
    if len(x) > 20:
        raise ValueError(
            f"line_chart received {len(x)} points; bucket or sample to <= 20 "
            "per brand-guide (too many points = chart junk)"
        )

    fg = CANVAS_LIGHT if dark else CANVAS_DARK
    fig, ax = plt.subplots(figsize=DEFAULT_SIZE_IN)
    ax.plot(
        list(x),
        list(y),
        color=BRAND["neutral"],
        linewidth=2.2,
        marker="o",
        markersize=4,
        markerfacecolor=BRAND["neutral"],
        markeredgecolor="none",
    )
    ax.set_title(title)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)

    if accent_x is not None and accent_x in list(x):
        idx = list(x).index(accent_x)
        ax.plot(
            accent_x,
            y[idx],
            "o",
            color=BRAND["primary"],
            markersize=12,
            markeredgecolor="none",
            zorder=5,
        )
        ax.annotate(
            f"{y[idx]}",
            xy=(accent_x, y[idx]),
            xytext=(8, 10),
            textcoords="offset points",
            fontsize=13,
            color=BRAND["primary"],
            fontweight="bold",
        )

    apply_brand_style(fig, ax, dark=dark)
    return _figure_to_png(fig)


def bar_chart(
    labels: Sequence[str],
    values: Sequence[float],
    title: str,
    *,
    highlight_idx: int | None = None,
    dark: bool = False,
    horizontal: bool = False,
) -> bytes:
    """
    Clean bar chart. Use for categorical comparison (2-10 bars).

    highlight_idx colors that bar in brand primary, rest in neutral grey —
    a clean way to direct attention to ONE point without palette soup.
    """
    if len(labels) != len(values):
        raise ValueError(f"labels/values length mismatch: {len(labels)} vs {len(values)}")
    if not labels:
        raise ValueError("bar_chart requires at least one bar")
    if len(labels) > 10:
        raise ValueError(f"bar_chart received {len(labels)} bars; keep to <= 10 per brand-guide")

    colors = [BRAND["neutral"]] * len(labels)
    if highlight_idx is not None and 0 <= highlight_idx < len(labels):
        colors[highlight_idx] = BRAND["primary"]

    fig, ax = plt.subplots(figsize=DEFAULT_SIZE_IN)
    if horizontal:
        ax.barh(list(labels), list(values), color=colors, edgecolor="none")
        ax.invert_yaxis()
    else:
        ax.bar(list(labels), list(values), color=colors, edgecolor="none", width=0.65)
    ax.set_title(title)
    apply_brand_style(fig, ax, dark=dark)
    return _figure_to_png(fig)
