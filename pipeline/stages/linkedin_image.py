"""Generate a 1200×628 px infographic card for the LinkedIn post.

Uses Matplotlib's Agg backend — no display server, no X11, no system fonts
required. Safe for GitHub Actions ubuntu-latest containers. Matplotlib bundles
DejaVu Sans so rendering is fully self-contained.

LinkedIn optimal feed image: 1200×628 px, < 5 MB, PNG or JPG.
"""

from __future__ import annotations

import logging
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.models import ScoredCluster

log = logging.getLogger(__name__)

# ── Brand palette (matches DevSignal logo) ────────────────────────────────
_BG     = "#0F172A"   # dark navy — background
_PANEL  = "#1E293B"   # dark slate — header/footer/cards
_TEAL   = "#38BDF8"   # sky blue   — primary accent, rank 1
_VIOLET = "#818CF8"   # indigo     — secondary accent, ranks 2-3
_WHITE  = "#F8FAFC"   # near-white — primary text
_MUTED  = "#94A3B8"   # slate grey — secondary text
_TRACK  = "#2D3F55"   # dark blue  — empty bar track / dividers

_FIG_W  = 12.0    # inches
_FIG_H  =  6.28   # inches  →  1200 × 628 px at 100 DPI
_DPI    = 100

# Layout constants in axes-data coords (0-1 origin bottom-left)
_HEADER_Y = 0.875   # y where content starts (below header)
_FOOTER_Y = 0.115   # y where footer starts  (above footer)
_DIVX     = 0.435   # x where right panel begins


def generate_image(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    *,
    out_path: Path,
    run_id: str = "",
    dashboard_url: str = "",
) -> Path | None:
    """Render the infographic. Returns out_path on success, None on failure."""
    if not scored:
        log.warning("linkedin_image: no scored clusters — skipping")
        return None

    try:
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")  # must be set before pyplot is imported
        import matplotlib.patches as mpatches  # noqa: PLC0415
        import matplotlib.pyplot as plt  # noqa: PLC0415
    except ImportError:
        log.warning("linkedin_image: matplotlib not installed — skipping")
        return None

    try:
        _render(scored, narrative, plt=plt, mpatches=mpatches,
                out_path=out_path, run_id=run_id, dashboard_url=dashboard_url)
        size_kb = out_path.stat().st_size // 1024
        log.info("linkedin_image: wrote %s (%d KB)", out_path, size_kb)
        return out_path
    except Exception:
        log.exception("linkedin_image: render failed")
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    *,
    plt: Any,
    mpatches: Any,
    out_path: Path,
    run_id: str,
    dashboard_url: str,
) -> None:
    fig = plt.figure(figsize=(_FIG_W, _FIG_H), dpi=_DPI, facecolor=_BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_facecolor(_BG)

    _draw_header(ax, mpatches, run_id)
    _draw_footer(ax, mpatches, dashboard_url)
    _draw_left_panel(ax, scored, narrative)
    _draw_right_panel(ax, mpatches, scored, narrative)

    fig.savefig(out_path, dpi=_DPI, facecolor=_BG,
                bbox_inches=None, pad_inches=0, format="png")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _draw_header(ax: Any, mpatches: Any, run_id: str) -> None:
    ax.add_patch(mpatches.FancyBboxPatch(
        (0, _HEADER_Y), 1, 1 - _HEADER_Y,
        boxstyle="square,pad=0", fc=_PANEL, ec="none", zorder=1,
    ))
    # Brand name
    ax.text(0.020, (_HEADER_Y + 1) / 2, "DevSignal",
            color=_TEAL, fontsize=17, fontweight="bold",
            va="center", ha="left", zorder=2)
    # Subtitle
    ax.text(0.148, (_HEADER_Y + 1) / 2, "Intelligence Briefing",
            color=_MUTED, fontsize=10.5, va="center", ha="left", zorder=2)
    # Separator dot
    ax.text(0.370, (_HEADER_Y + 1) / 2, "·",
            color=_TRACK, fontsize=14, va="center", ha="center", zorder=2)
    # Week label
    week = run_id if run_id else datetime.now(UTC).strftime("Week %V · %Y")
    ax.text(0.978, (_HEADER_Y + 1) / 2, week,
            color=_MUTED, fontsize=10, va="center", ha="right", zorder=2)
    # Accent rule
    ax.plot([0, 1], [_HEADER_Y, _HEADER_Y], color=_TEAL, lw=1.5, alpha=0.45, zorder=2)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------


def _draw_footer(ax: Any, mpatches: Any, dashboard_url: str) -> None:
    ax.add_patch(mpatches.FancyBboxPatch(
        (0, 0), 1, _FOOTER_Y,
        boxstyle="square,pad=0", fc=_PANEL, ec="none", zorder=1,
    ))
    ax.plot([0, 1], [_FOOTER_Y, _FOOTER_Y], color=_TEAL, lw=1.0, alpha=0.30, zorder=2)
    mid = _FOOTER_Y / 2
    if dashboard_url:
        ax.text(0.020, mid, f"Full breakdown  →  {dashboard_url}",
                color=_TEAL, fontsize=8.5, va="center", ha="left", zorder=2)
    ax.text(0.978, mid, "#devtools   #buildinpublic   #softwareengineering",
            color=_MUTED, fontsize=8, va="center", ha="right", zorder=2)


# ---------------------------------------------------------------------------
# Left panel: headline + KPI tiles
# ---------------------------------------------------------------------------


def _draw_left_panel(
    ax: Any,
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
) -> None:
    headline = (
        (narrative.get("headline") or "")
        if narrative
        else ""
    ) or f"{len(scored)} pain clusters active in software teams this week"

    wrapped = textwrap.fill(headline, width=26)
    ax.text(0.020, _HEADER_Y - 0.055, wrapped,
            color=_WHITE, fontsize=14, fontweight="bold",
            va="top", ha="left", linespacing=1.40, zorder=2)

    # KPI tiles — bottom of left panel
    n_posts    = sum(len(sc.cluster.posts) for sc in scored)
    n_clusters = len(scored)
    kpi_y      = _FOOTER_Y + 0.048

    for col, (val, lbl) in enumerate([
        (str(n_posts),    "signals tracked"),
        (str(n_clusters), "active clusters"),
    ]):
        kx = 0.020 + col * 0.195
        ax.text(kx, kpi_y + 0.058, val,
                color=_TEAL, fontsize=22, fontweight="bold",
                va="bottom", ha="left", zorder=2)
        ax.text(kx, kpi_y + 0.053, lbl,
                color=_MUTED, fontsize=8.5, va="top", ha="left", zorder=2)

    # Vertical divider between panels
    ax.plot([_DIVX, _DIVX],
            [_FOOTER_Y + 0.025, _HEADER_Y - 0.025],
            color=_TRACK, lw=1.0, alpha=0.7, zorder=2)


# ---------------------------------------------------------------------------
# Right panel: top-3 opportunity cards
# ---------------------------------------------------------------------------


def _draw_right_panel(
    ax: Any,
    mpatches: Any,
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
) -> None:
    rx0 = _DIVX + 0.018
    rw  = 1 - rx0 - 0.018
    n   = 3

    items = _top_items(scored, narrative, n)

    # Section label
    ax.text(rx0, _HEADER_Y - 0.048, "TOP OPPORTUNITIES THIS WEEK",
            color=_TEAL, fontsize=7.5, fontweight="bold",
            va="top", ha="left", alpha=0.90, zorder=2)

    slot_h = (_HEADER_Y - _FOOTER_Y - 0.105) / n

    for idx, item in enumerate(items):
        top    = _HEADER_Y - 0.095 - idx * slot_h
        bottom = top - slot_h + 0.012
        ch     = top - bottom
        accent = _TEAL if idx == 0 else _VIOLET

        # Card background
        ax.add_patch(mpatches.FancyBboxPatch(
            (rx0, bottom), rw, ch,
            boxstyle="round,pad=0.008",
            fc=_PANEL, ec=_TRACK, lw=0.75, zorder=2,
        ))

        # Rank badge (filled circle)
        bx = rx0 + 0.022
        by = bottom + ch / 2
        ax.add_patch(mpatches.Circle(
            (bx, by), radius=0.017, color=accent, zorder=3,
        ))
        ax.text(bx, by, str(item["rank"]),
                color=_BG, fontsize=8.5, fontweight="bold",
                va="center", ha="center", zorder=4)

        # Title
        title = textwrap.shorten(item["title"], width=48, placeholder="…")
        ax.text(rx0 + 0.052, top - 0.022, title,
                color=_WHITE, fontsize=9.5, fontweight="bold",
                va="top", ha="left", zorder=3)

        # Score bar
        score = item.get("score")
        if score is not None:
            frac = min(1.0, max(0.0, score / 100))
            bx0  = rx0 + 0.052
            by0  = bottom + 0.032
            bw   = rw - 0.080
            bh   = 0.015
            ax.add_patch(mpatches.FancyBboxPatch(
                (bx0, by0), bw, bh,
                boxstyle="round,pad=0.002", fc=_TRACK, ec="none", zorder=3,
            ))
            if frac > 0.01:
                ax.add_patch(mpatches.FancyBboxPatch(
                    (bx0, by0), max(bw * frac, bh),  # min width = height (looks clean at low scores)
                    bh, boxstyle="round,pad=0.002",
                    fc=accent, ec="none", zorder=4,
                ))
            ax.text(bx0 + bw + 0.008, by0 + bh / 2,
                    f"{score:.0f}",
                    color=_MUTED, fontsize=8, va="center", ha="left", zorder=4)

        # Target role
        role = item.get("role", "")
        if role:
            role_str = role.replace("_", " ").title()
            ax.text(rx0 + 0.052, bottom + 0.016, f"→ {role_str}s",
                    color=_MUTED, fontsize=8, va="bottom", ha="left", zorder=3)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _top_items(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    n: int,
) -> list[dict[str, Any]]:
    """Build ranked item list, resolving scores from clusters when available."""
    # Index clusters by title for score lookup
    by_title: dict[str, ScoredCluster] = {}
    for sc in scored:
        title = sc.synthesis.title if sc.synthesis else sc.cluster.label
        by_title[title] = sc

    if narrative and narrative.get("top_10"):
        items = []
        for item in narrative["top_10"][:n]:
            title = item.get("title", "")
            sc    = by_title.get(title)
            items.append({
                "rank":  item.get("rank", len(items) + 1),
                "title": title,
                "role":  item.get("target_role", ""),
                "score": sc.opportunity if sc else None,
            })
        return items

    # Heuristic fallback
    return [
        {
            "rank":  i,
            "title": sc.synthesis.title if sc.synthesis else sc.cluster.label,
            "role":  sc.role_top[0][0] if sc.role_top else "",
            "score": sc.opportunity,
        }
        for i, sc in enumerate(
            sorted(scored, key=lambda s: -s.opportunity)[:n], 1
        )
    ]
