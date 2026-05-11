"""Smoke tests for pipeline.models — every dataclass constructs and round-trips."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

import pytest

from pipeline.models import (
    Cluster,
    ClusterSynthesis,
    CostMention,
    NormalizedPost,
    RawPost,
    ScoredCluster,
)


def _raw_post(**overrides: object) -> RawPost:
    defaults: dict[str, object] = {
        "id": "reddit:abc123",
        "source": "reddit",
        "author_handle": "someone",
        "author_role_hint": "engineer",
        "posted_at": datetime(2026, 5, 1, tzinfo=UTC),
        "url": "https://reddit.com/r/programming/comments/abc123",
        "text": "Title\n\nBody",
        "score": 42,
        "replies_count": 7,
    }
    defaults.update(overrides)
    return RawPost(**defaults)  # type: ignore[arg-type]


def test_raw_post_defaults() -> None:
    p = _raw_post()
    assert p.source == "reddit"
    assert p.raw == {}
    assert p.score == 42


def test_raw_post_is_frozen() -> None:
    p = _raw_post()
    with pytest.raises(Exception):
        p.score = 99  # type: ignore[misc]


def test_normalized_post_with_cost_mentions() -> None:
    p = NormalizedPost(
        id="abc",
        source="reddit",
        author_handle="x",
        role="engineer",
        posted_at=datetime.now(UTC),
        url="https://example.com",
        text="cleaned text",
        score=10,
        replies_count=2,
        sentiment=-0.3,
        cost_mentions=[
            CostMention(kind="time", raw="3 days", value=3.0, unit="days"),
            CostMention(kind="money", raw="$200", value=200.0, unit=None),
        ],
    )
    assert len(p.cost_mentions) == 2
    assert p.cost_mentions[0].kind == "time"


def test_cluster_and_scored_cluster() -> None:
    cluster = Cluster(
        id="c-001",
        label="flaky-tests",
        centroid=[0.0] * 384,
        posts=[],
        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 1, tzinfo=UTC),
    )
    scored = ScoredCluster(
        cluster=cluster,
        frequency_per_week=4.2,
        frequency_zscore=1.1,
        cost_summary="median 2 days of engineering time per occurrence",
        role_top=[("engineer", 0.8), ("devops", 0.2)],
        opportunity=72.5,
        feasibility="high",
        impl_cost_band="$10-100k",
    )
    assert scored.feasibility == "high"
    assert scored.synthesis is None
    assert scored.cluster.label == "flaky-tests"


def test_scored_cluster_with_synthesis_round_trips() -> None:
    cluster = Cluster(
        id="c-002",
        label="oncall-burnout",
        centroid=[0.1, 0.2],
        posts=[],
        first_seen=datetime(2026, 1, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 1, tzinfo=UTC),
    )
    synth = ClusterSynthesis(
        title="On-call burnout",
        one_line_pain="SREs are getting paged constantly and leaving.",
        role_demographics="Predominantly SRE / DevOps (80%)",
        perceived_cost_summary="2-4 lost engineering days per incident",
        feasibility="medium",
        implementation_cost_band="$100k-1M",
        opportunity_pitch="Automated on-call triage agent with incident correlation",
        confidence=0.78,
    )
    scored = ScoredCluster(
        cluster=cluster,
        frequency_per_week=8.0,
        frequency_zscore=2.4,
        cost_summary="...",
        role_top=[("sre", 0.6), ("devops", 0.3)],
        opportunity=88.0,
        feasibility="medium",
        impl_cost_band="$100k-1M",
        synthesis=synth,
    )
    blob = asdict(scored)
    assert blob["synthesis"]["title"] == "On-call burnout"
    assert blob["cluster"]["label"] == "oncall-burnout"
