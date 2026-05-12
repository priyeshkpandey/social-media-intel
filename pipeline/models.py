"""Domain dataclasses for the pipeline.

Stable types passed between stages. Every stage consumes and produces one of these.
Serialization to JSON / parquet happens in `pipeline/stages/export.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Source = Literal["reddit", "hackernews", "devto", "lobsters", "stackexchange", "lemmy"]
Feasibility = Literal["low", "medium", "high"]
ImplCostBand = Literal["<$10k", "$10-100k", "$100k-1M", ">$1M"]
CostKind = Literal["money", "time", "team"]


@dataclass(frozen=True, slots=True)
class RawPost:
    """As ingested from a source, before normalization."""

    id: str
    source: Source
    author_handle: str | None
    author_role_hint: str | None
    posted_at: datetime
    url: str
    text: str
    score: int
    replies_count: int
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class CostMention:
    """A money/time/team-size mention extracted from post text."""

    kind: CostKind
    raw: str
    value: float | None
    unit: str | None


@dataclass(slots=True)
class NormalizedPost:
    """Post after cleaning, role assignment, sentiment, and cost-mention extraction."""

    id: str
    source: Source
    author_handle: str | None
    role: str | None
    posted_at: datetime
    url: str
    text: str
    score: int
    replies_count: int
    sentiment: float
    cost_mentions: list[CostMention] = field(default_factory=list)


@dataclass(slots=True)
class Cluster:
    """A group of related posts.

    `centroid` is the mean of member embeddings (kept as plain list so the
    dataclass stays import-free of numpy and trivially JSON-serializable).
    `id` is stable across runs — assigned by the cluster stage based on
    centroid similarity to the prior week's clusters.
    """

    id: str
    label: str
    centroid: list[float]
    posts: list[NormalizedPost]
    first_seen: datetime
    last_seen: datetime


@dataclass(slots=True)
class ClusterSynthesis:
    """Optional refined output from Claude (Step 8). Absent in heuristic-only runs."""

    title: str
    one_line_pain: str
    role_demographics: str
    perceived_cost_summary: str
    feasibility: Feasibility
    implementation_cost_band: ImplCostBand
    opportunity_pitch: str
    confidence: float


@dataclass(slots=True)
class CostSummary:
    """Aggregated cost evidence for a cluster.

    Medians are over `CostMention`s of the matching kind across the cluster's
    posts. Time mentions are normalized to days at extraction time. `summary`
    is the human-readable rendering for the dashboard tooltip.
    """

    money_median_usd: float | None = None
    time_median_days: float | None = None
    team_median_people: float | None = None
    sample_count: int = 0
    summary: str = "no cost data"


@dataclass(slots=True)
class ScoredCluster:
    """A Cluster plus the six dashboard dimensions.

    All numeric scores are 0–100 where applicable. See METHODOLOGY.md for rubrics.
    """

    cluster: Cluster
    frequency_per_week: float
    frequency_zscore: float
    cost: CostSummary
    role_top: list[tuple[str, float]]
    opportunity: float
    feasibility: Feasibility
    impl_cost_band: ImplCostBand
    synthesis: ClusterSynthesis | None = None
