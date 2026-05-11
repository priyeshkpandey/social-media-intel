"""Score stage — six heuristic dimensions per cluster.

Public API: `score_clusters(clusters) -> list[ScoredCluster]`. Z-score is
computed across the batch, so all clusters share the same baseline. The
12-month rolling time series is reconstructed at export time by joining
prior dashboard.json releases (Step 9).

Every rubric value lives in `pipeline/config.py`. See METHODOLOGY.md for
the human-readable description of each dimension.
"""

from __future__ import annotations

import logging
from typing import Final

import numpy as np

from pipeline.config import (
    FEASIBILITY_HIGH_KEYWORDS,
    FEASIBILITY_LOW_KEYWORDS,
    IMPL_COST_SCOPE_KEYWORDS,
    PAY_INTENT_PHRASES,
)
from pipeline.models import (
    Cluster,
    CostSummary,
    Feasibility,
    ImplCostBand,
    ScoredCluster,
)

log = logging.getLogger(__name__)

# Opportunity composite weights. Documented in METHODOLOGY.
_W_FREQ: Final[float] = 40.0
_W_NEG: Final[float] = 30.0
_W_PAY: Final[float] = 30.0

# Scope priority for impl-cost-band lookup (largest wins on conflict).
_SCOPE_PRIORITY: Final[tuple[str, ...]] = ("huge", "large", "medium", "small")

# (feasibility, scope) → cost band. Documented in METHODOLOGY.
_BAND_MATRIX: Final[dict[tuple[Feasibility, str], ImplCostBand]] = {
    ("low", "small"): "$100k-1M",
    ("low", "medium"): "$100k-1M",
    ("low", "large"): ">$1M",
    ("low", "huge"): ">$1M",
    ("medium", "small"): "<$10k",
    ("medium", "medium"): "$10-100k",
    ("medium", "large"): "$100k-1M",
    ("medium", "huge"): ">$1M",
    ("high", "small"): "<$10k",
    ("high", "medium"): "$10-100k",
    ("high", "large"): "$100k-1M",
    ("high", "huge"): ">$1M",
}


def score_clusters(clusters: list[Cluster]) -> list[ScoredCluster]:
    if not clusters:
        return []

    freqs = [_frequency_per_week(c) for c in clusters]
    mean = float(np.mean(freqs))
    std = max(float(np.std(freqs)), 1e-6)
    zscores = [(f - mean) / std for f in freqs]

    out: list[ScoredCluster] = []
    for cluster, freq, z in zip(clusters, freqs, zscores, strict=True):
        cost = _cost_summary(cluster)
        roles = _demography(cluster)
        opp = _opportunity(
            z,
            _mean_neg_sentiment(cluster),
            _pay_intent_density(cluster),
        )
        feas = _feasibility(cluster)
        band = _impl_cost_band(feas, _text_blob(cluster))
        out.append(
            ScoredCluster(
                cluster=cluster,
                frequency_per_week=freq,
                frequency_zscore=z,
                cost=cost,
                role_top=roles,
                opportunity=opp,
                feasibility=feas,
                impl_cost_band=band,
            )
        )

    log.info("score: scored %d clusters", len(out))
    return out


# ---------------------------------------------------------------------------
# Per-dimension helpers (kept module-level so tests can hit them directly).
# ---------------------------------------------------------------------------


def _frequency_per_week(cluster: Cluster) -> float:
    """Posts per week over the cluster's observed span."""
    n = len(cluster.posts)
    if n == 0:
        return 0.0
    span_days = (cluster.last_seen - cluster.first_seen).total_seconds() / 86400.0
    span_days = max(span_days, 1.0)
    return n / (span_days / 7.0)


def _cost_summary(cluster: Cluster) -> CostSummary:
    monies: list[float] = []
    days: list[float] = []
    teams: list[float] = []

    for post in cluster.posts:
        for cm in post.cost_mentions:
            if cm.value is None:
                continue
            if cm.kind == "money":
                monies.append(cm.value)
            elif cm.kind == "time":
                d = _time_to_days(cm.value, cm.unit)
                if d is not None:
                    days.append(d)
            elif cm.kind == "team":
                teams.append(cm.value)

    median_money = float(np.median(monies)) if monies else None
    median_days = float(np.median(days)) if days else None
    median_team = float(np.median(teams)) if teams else None

    parts: list[str] = []
    if median_money is not None:
        parts.append(f"~${_human_money(median_money)}")
    if median_days is not None:
        parts.append(f"~{median_days:.0f} day(s)")
    if median_team is not None:
        parts.append(f"team of ~{median_team:.0f}")
    summary = ", ".join(parts) if parts else "no cost data"

    return CostSummary(
        money_median_usd=median_money,
        time_median_days=median_days,
        team_median_people=median_team,
        sample_count=len(monies) + len(days) + len(teams),
        summary=summary,
    )


def _time_to_days(value: float, unit: str | None) -> float | None:
    if unit is None:
        return None
    u = unit.lower()
    if u in ("hour", "hours"):
        return value / 24.0
    if u in ("day", "days"):
        return value
    if u in ("week", "weeks"):
        return value * 7
    if u in ("month", "months"):
        return value * 30
    if u in ("year", "years"):
        return value * 365
    return None


def _human_money(usd: float) -> str:
    if usd >= 1_000_000:
        return f"{usd / 1_000_000:.1f}M"
    if usd >= 1_000:
        return f"{usd / 1_000:.0f}k"
    return f"{usd:.0f}"


def _demography(cluster: Cluster) -> list[tuple[str, float]]:
    counts: dict[str, int] = {}
    for post in cluster.posts:
        role = post.role or "other"
        counts[role] = counts.get(role, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return []
    items = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
    return [(role, n / total) for role, n in items]


def _mean_neg_sentiment(cluster: Cluster) -> float:
    """Mean magnitude of negative sentiment (0..1). Posts with sentiment ≥ 0 ignored."""
    negs = [-p.sentiment for p in cluster.posts if p.sentiment < 0]
    if not negs:
        return 0.0
    return float(np.mean(negs))


def _pay_intent_density(cluster: Cluster) -> float:
    if not cluster.posts:
        return 0.0
    matches = sum(
        1
        for p in cluster.posts
        if any(phrase in p.text.lower() for phrase in PAY_INTENT_PHRASES)
    )
    return matches / len(cluster.posts)


def _opportunity(freq_z: float, neg_sent: float, pay_density: float) -> float:
    """Composite 0-100. Freq via sigmoid; sentiment + pay-intent linear (both 0..1)."""
    freq_factor = 1.0 / (1.0 + float(np.exp(-freq_z)))
    raw = _W_FREQ * freq_factor + _W_NEG * neg_sent + _W_PAY * pay_density
    return float(np.clip(raw, 0.0, 100.0))


def _feasibility(cluster: Cluster) -> Feasibility:
    text = _text_blob(cluster).lower()
    low = sum(1 for kw in FEASIBILITY_LOW_KEYWORDS if kw.lower() in text)
    high = sum(1 for kw in FEASIBILITY_HIGH_KEYWORDS if kw.lower() in text)
    if low > high:
        return "low"
    if high > low:
        return "high"
    return "medium"


def _impl_cost_band(feasibility: Feasibility, text: str) -> ImplCostBand:
    scope = _detect_scope(text)
    return _BAND_MATRIX.get((feasibility, scope), "$10-100k")


def _detect_scope(text: str) -> str:
    """Pick the largest scope bucket whose keywords appear in `text`."""
    lower = text.lower()
    for scope in _SCOPE_PRIORITY:
        if any(kw in lower for kw in IMPL_COST_SCOPE_KEYWORDS[scope]):
            return scope
    return "medium"


def _text_blob(cluster: Cluster) -> str:
    return " ".join(p.text for p in cluster.posts)
