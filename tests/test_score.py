"""Unit tests for pipeline.stages.score."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pipeline.models import Cluster, CostMention, NormalizedPost
from pipeline.stages import score


def _post(
    post_id: str,
    text: str,
    role: str | None = "engineer",
    sentiment: float = 0.0,
    day: int = 1,
    cost_mentions: list[CostMention] | None = None,
) -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle=None,
        role=role,
        posted_at=datetime(2026, 5, day, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
        sentiment=sentiment,
        cost_mentions=cost_mentions or [],
    )


def _cluster(
    cid: str,
    posts: list[NormalizedPost],
    label: str = "test cluster",
) -> Cluster:
    if not posts:
        first = last = datetime(2026, 5, 1, tzinfo=UTC)
    else:
        first = min(p.posted_at for p in posts)
        last = max(p.posted_at for p in posts)
    return Cluster(
        id=cid,
        label=label,
        centroid=[0.0] * 4,
        posts=posts,
        first_seen=first,
        last_seen=last,
    )


# ---------- frequency ----------


def test_frequency_per_week_same_day_clamps_to_minimum_span() -> None:
    c = _cluster("c1", [_post(f"p{i}", "x", day=5) for i in range(7)])
    # 7 posts in <1 day → clamped to 1-day span → 7 posts/day = 49/week.
    assert score._frequency_per_week(c) == pytest.approx(49.0)


def test_frequency_per_week_full_week() -> None:
    c = _cluster(
        "c1",
        [_post("p1", "x", day=1), _post("p2", "x", day=8)],
    )
    # Span = 7 days = 1 week, 2 posts → 2/week.
    assert score._frequency_per_week(c) == pytest.approx(2.0)


def test_frequency_per_week_empty_cluster() -> None:
    c = _cluster("c1", [])
    assert score._frequency_per_week(c) == 0.0


# ---------- cost summary ----------


def test_cost_summary_money_time_team() -> None:
    posts = [
        _post(
            "p1",
            "We pay $50k/year",
            cost_mentions=[
                CostMention(kind="money", raw="$50k", value=50_000.0, unit=None),
                CostMention(kind="time", raw="3 days", value=3.0, unit="days"),
            ],
        ),
        _post(
            "p2",
            "Took 5 days and team of 4",
            cost_mentions=[
                CostMention(kind="time", raw="5 days", value=5.0, unit="days"),
                CostMention(kind="team", raw="team of 4", value=4.0, unit="people"),
            ],
        ),
    ]
    out = score._cost_summary(_cluster("c", posts))
    assert out.money_median_usd == 50_000.0
    assert out.time_median_days == 4.0  # median of 3, 5
    assert out.team_median_people == 4.0
    assert out.sample_count == 4
    assert "50k" in out.summary
    assert "4 day" in out.summary
    assert "team of ~4" in out.summary


def test_cost_summary_no_evidence() -> None:
    out = score._cost_summary(_cluster("c", [_post("p1", "no numbers here")]))
    assert out.money_median_usd is None
    assert out.summary == "no cost data"
    assert out.sample_count == 0


def test_time_to_days_units() -> None:
    assert score._time_to_days(48, "hours") == 2.0
    assert score._time_to_days(2, "weeks") == 14
    assert score._time_to_days(1, "months") == 30
    assert score._time_to_days(1, "years") == 365
    assert score._time_to_days(1, "fortnight") is None
    assert score._time_to_days(1, None) is None


def test_human_money_brackets() -> None:
    assert score._human_money(150) == "150"
    assert score._human_money(2_500) == "2k"
    assert score._human_money(50_000) == "50k"
    assert score._human_money(2_500_000) == "2.5M"


# ---------- demography ----------


def test_demography_top_three_with_shares() -> None:
    posts = (
        [_post(f"e{i}", "x", role="engineer") for i in range(7)]
        + [_post(f"d{i}", "x", role="devops") for i in range(2)]
        + [_post("q1", "x", role="qa")]
    )
    out = score._demography(_cluster("c", posts))
    assert out[0] == ("engineer", 0.7)
    assert out[1] == ("devops", 0.2)
    assert out[2] == ("qa", pytest.approx(0.1))


def test_demography_treats_none_role_as_other() -> None:
    posts = [_post(f"x{i}", "x", role=None) for i in range(3)]
    out = score._demography(_cluster("c", posts))
    assert out == [("other", 1.0)]


def test_demography_empty() -> None:
    assert score._demography(_cluster("c", [])) == []


# ---------- sentiment / pay intent ----------


def test_mean_neg_sentiment_only_counts_negative_posts() -> None:
    posts = [
        _post("p1", "x", sentiment=-0.6),
        _post("p2", "x", sentiment=-0.4),
        _post("p3", "x", sentiment=0.5),  # ignored
        _post("p4", "x", sentiment=0.0),  # ignored
    ]
    assert score._mean_neg_sentiment(_cluster("c", posts)) == pytest.approx(0.5)


def test_mean_neg_sentiment_no_negatives() -> None:
    posts = [_post("p1", "x", sentiment=0.3)]
    assert score._mean_neg_sentiment(_cluster("c", posts)) == 0.0


def test_pay_intent_density() -> None:
    posts = [
        _post("p1", "I would pay good money for this"),
        _post("p2", "happy to pay if it actually works"),
        _post("p3", "just a generic complaint"),
        _post("p4", "no signal here"),
    ]
    assert score._pay_intent_density(_cluster("c", posts)) == 0.5


def test_pay_intent_density_empty_cluster() -> None:
    assert score._pay_intent_density(_cluster("c", [])) == 0.0


# ---------- opportunity composite ----------


def test_opportunity_bounded_0_100() -> None:
    assert 0.0 <= score._opportunity(-10, 0.0, 0.0) <= 100.0
    assert 0.0 <= score._opportunity(10, 1.0, 1.0) <= 100.0


def test_opportunity_increases_with_each_signal() -> None:
    low = score._opportunity(-2, 0.0, 0.0)
    mid = score._opportunity(0.0, 0.3, 0.2)
    high = score._opportunity(2, 0.8, 0.7)
    assert low < mid < high


# ---------- feasibility ----------


def test_feasibility_low_when_low_keywords_dominate() -> None:
    c = _cluster("c", [_post("p1", "AGI is required and FDA regulatory approval too")])
    assert score._feasibility(c) == "low"


def test_feasibility_high_when_high_keywords_dominate() -> None:
    c = _cluster("c", [_post("p1", "Build a CLI tool or LLM plugin as a SaaS")])
    assert score._feasibility(c) == "high"


def test_feasibility_medium_default() -> None:
    c = _cluster("c", [_post("p1", "Generic talk with no scope signals")])
    assert score._feasibility(c) == "medium"


# ---------- impl cost band ----------


def test_impl_cost_band_small_high() -> None:
    c = _cluster("c", [_post("p1", "Just a vscode extension or chrome plugin")])
    assert score._impl_cost_band("high", score._text_blob(c)) == "<$10k"


def test_impl_cost_band_large_medium() -> None:
    c = _cluster("c", [_post("p1", "A multi-region kubernetes platform")])
    assert score._impl_cost_band("medium", score._text_blob(c)) == "$100k-1M"


def test_impl_cost_band_huge_overrides_small() -> None:
    """When a post mentions both 'script' (small) and 'compiler' (huge), huge wins."""
    c = _cluster("c", [_post("p1", "Tiny script that wraps a real compiler")])
    assert score._impl_cost_band("high", score._text_blob(c)) == ">$1M"


def test_impl_cost_band_low_feasibility_floor() -> None:
    c = _cluster("c", [_post("p1", "We need a tiny script for an impossible problem")])
    assert score._impl_cost_band("low", score._text_blob(c)) == "$100k-1M"


# ---------- score_clusters orchestration ----------


def test_score_clusters_empty_returns_empty() -> None:
    assert score.score_clusters([]) == []


def test_score_clusters_zscore_normalizes_across_batch() -> None:
    low = _cluster("c1", [_post(f"a{i}", "x", day=1) for i in range(3)])
    high = _cluster("c2", [_post(f"b{i}", "x", day=1) for i in range(30)])
    out = score.score_clusters([low, high])
    assert out[0].frequency_zscore < out[1].frequency_zscore
    # Z-scores around a batch of two centered values must sum to ~0.
    assert abs(out[0].frequency_zscore + out[1].frequency_zscore) < 1e-3


def test_score_clusters_attaches_all_fields() -> None:
    posts = [
        _post("p1", "I would pay for this script", sentiment=-0.5),
        _post("p2", "ci pipeline is hell", sentiment=-0.4),
        _post("p3", "we need a saas tool", sentiment=-0.6),
    ]
    out = score.score_clusters([_cluster("c", posts)])
    assert len(out) == 1
    sc = out[0]
    assert 0.0 <= sc.opportunity <= 100.0
    assert sc.feasibility in {"low", "medium", "high"}
    assert sc.impl_cost_band in {"<$10k", "$10-100k", "$100k-1M", ">$1M"}
    assert sc.role_top
    assert isinstance(sc.cost.summary, str)
