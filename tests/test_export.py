"""Unit tests for pipeline.stages.export.

`build_dashboard` tests run without pandas. `export` integration tests use
`pytest.importorskip("pandas")` so they skip locally and run in CI.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pipeline.config import SCHEMA_VERSION
from pipeline.models import (
    Cluster,
    ClusterSynthesis,
    CostMention,
    CostSummary,
    NormalizedPost,
    ScoredCluster,
)
from pipeline.stages import export as exp


def _post(
    post_id: str,
    text: str = "post text",
    role: str = "engineer",
    score: int = 0,
    cost_mentions: list[CostMention] | None = None,
    day: int = 1,
) -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle="alice",
        role=role,
        posted_at=datetime(2026, 5, day, tzinfo=UTC),
        url=f"https://example.com/{post_id}",
        text=text,
        score=score,
        replies_count=0,
        sentiment=-0.2,
        cost_mentions=cost_mentions or [],
    )


def _scored(
    cluster_id: str,
    opportunity: float = 70.0,
    n_posts: int = 3,
    first_seen: datetime | None = None,
    synthesis: ClusterSynthesis | None = None,
) -> ScoredCluster:
    posts = [_post(f"{cluster_id}-p{i}", f"text {i}", score=i) for i in range(n_posts)]
    cluster = Cluster(
        id=cluster_id,
        label="raw label",
        centroid=[0.0],
        posts=posts,
        first_seen=first_seen or datetime(2026, 1, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 7, tzinfo=UTC),
    )
    return ScoredCluster(
        cluster=cluster,
        frequency_per_week=float(n_posts),
        frequency_zscore=1.1,
        cost=CostSummary(summary="no cost data"),
        role_top=[("engineer", 0.8), ("devops", 0.2)],
        opportunity=opportunity,
        feasibility="high",
        impl_cost_band="<$10k",
        synthesis=synthesis,
    )


def _synthesis() -> ClusterSynthesis:
    return ClusterSynthesis(
        title="Refined title",
        one_line_pain="concise pain",
        role_demographics="mostly senior ICs",
        perceived_cost_summary="~3 days/week",
        feasibility="high",
        implementation_cost_band="<$10k",
        opportunity_pitch="a focused tool",
        confidence=0.756,
    )


# ---------- iso_week_id ----------


def test_iso_week_id_zero_pads_week() -> None:
    assert exp.iso_week_id(datetime(2026, 1, 5, tzinfo=UTC)) == "v2026-02"
    assert exp.iso_week_id(datetime(2026, 5, 12, tzinfo=UTC)) == "v2026-20"


# ---------- build_dashboard envelope ----------


def test_empty_dashboard_is_valid() -> None:
    out = exp.build_dashboard([], None, run_date=datetime(2026, 5, 12, tzinfo=UTC))
    assert out["schema_version"] == SCHEMA_VERSION
    assert out["run_id"] == "v2026-20"
    assert out["clusters"] == []
    assert out["narrative"] is None
    assert out["heuristic_only"] is True
    assert out["kpi"] == {
        "total_posts_this_week": 0,
        "active_clusters": 0,
        "new_clusters_this_week": 0,
        "mean_opportunity": 0.0,
    }


def test_heuristic_only_defaults_to_true_when_no_synthesis() -> None:
    out = exp.build_dashboard([_scored("c-1")], None)
    assert out["heuristic_only"] is True


def test_heuristic_only_false_when_any_cluster_has_synthesis() -> None:
    out = exp.build_dashboard(
        [_scored("c-1"), _scored("c-2", synthesis=_synthesis())], None
    )
    assert out["heuristic_only"] is False


def test_heuristic_only_override_respected() -> None:
    out = exp.build_dashboard([_scored("c-1")], None, heuristic_only=False)
    assert out["heuristic_only"] is False


def test_dashboard_is_json_serializable() -> None:
    out = exp.build_dashboard(
        [_scored("c-1", synthesis=_synthesis())],
        narrative={"headline": "x", "top_10": [], "honorable_mentions": []},
    )
    serialized = json.dumps(out)
    assert "v2026-" in serialized
    assert "Refined title" in serialized


# ---------- KPI ----------


def test_kpi_counts_posts_and_clusters() -> None:
    out = exp.build_dashboard(
        [_scored("c-1", n_posts=5), _scored("c-2", n_posts=3)],
        None,
        run_date=datetime(2026, 5, 12, tzinfo=UTC),
    )
    kpi = out["kpi"]
    assert kpi["total_posts_this_week"] == 8
    assert kpi["active_clusters"] == 2


def test_kpi_new_clusters_uses_7_day_window() -> None:
    run_date = datetime(2026, 5, 12, tzinfo=UTC)
    fresh = _scored("c-new", first_seen=run_date - timedelta(days=3))
    stale = _scored("c-old", first_seen=run_date - timedelta(days=30))
    out = exp.build_dashboard([fresh, stale], None, run_date=run_date)
    assert out["kpi"]["new_clusters_this_week"] == 1


def test_kpi_mean_opportunity() -> None:
    out = exp.build_dashboard(
        [_scored("c-1", opportunity=80.0), _scored("c-2", opportunity=20.0)],
        None,
    )
    assert out["kpi"]["mean_opportunity"] == 50.0


# ---------- cluster_to_dict ----------


def test_cluster_dict_preserves_synthesis_title() -> None:
    sc = _scored("c-1", synthesis=_synthesis())
    out = exp.build_dashboard([sc], None)
    cluster = out["clusters"][0]
    assert cluster["title"] == "Refined title"
    assert cluster["label"] == "raw label"
    assert cluster["synthesis"]["confidence"] == 0.756


def test_cluster_dict_uses_label_as_title_without_synthesis() -> None:
    sc = _scored("c-1")
    out = exp.build_dashboard([sc], None)
    assert out["clusters"][0]["title"] == "raw label"
    assert out["clusters"][0]["synthesis"] is None


def test_representative_posts_capped_and_sorted_by_score() -> None:
    cluster = Cluster(
        id="c-1",
        label="x",
        centroid=[0.0],
        posts=[_post(f"p{i}", score=i) for i in range(20)],
        first_seen=datetime(2026, 5, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 7, tzinfo=UTC),
    )
    sc = ScoredCluster(
        cluster=cluster,
        frequency_per_week=10.0,
        frequency_zscore=0.0,
        cost=CostSummary(),
        role_top=[("engineer", 1.0)],
        opportunity=60.0,
        feasibility="medium",
        impl_cost_band="$10-100k",
    )
    out = exp.build_dashboard([sc], None)
    reps = out["clusters"][0]["representative_posts"]
    assert len(reps) == 10
    # Sorted by score desc.
    scores = [r["score"] for r in reps]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 19  # highest-scoring post first
    # post_count reflects ALL posts, not just the cap.
    assert out["clusters"][0]["post_count"] == 20


def test_representative_post_text_truncated() -> None:
    long_text = "x" * 800
    cluster = Cluster(
        id="c-1",
        label="x",
        centroid=[0.0],
        posts=[_post("p1", text=long_text)],
        first_seen=datetime(2026, 5, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 7, tzinfo=UTC),
    )
    sc = ScoredCluster(
        cluster=cluster,
        frequency_per_week=1.0,
        frequency_zscore=0.0,
        cost=CostSummary(),
        role_top=[("engineer", 1.0)],
        opportunity=50.0,
        feasibility="medium",
        impl_cost_band="$10-100k",
    )
    out = exp.build_dashboard([sc], None)
    text = out["clusters"][0]["representative_posts"][0]["text"]
    assert len(text) <= 501  # 500 chars + 1 ellipsis
    assert text.endswith("…")


def test_cluster_dict_serializes_dates_as_iso() -> None:
    sc = _scored("c-1")
    out = exp.build_dashboard([sc], None)
    cluster = out["clusters"][0]
    assert cluster["first_seen"].startswith("2026-01-01T")
    assert cluster["last_seen"].startswith("2026-05-07T")


# ---------- export (parquet integration) ----------


def test_export_writes_three_files(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")

    sc = _scored(
        "c-1",
        synthesis=_synthesis(),
        n_posts=2,
    )
    sc.cluster.posts[0] = _post(
        "c-1-p0",
        text="cost example",
        cost_mentions=[CostMention(kind="money", raw="$50k", value=50_000.0, unit=None)],
        score=10,
    )
    sc.cluster.posts[1] = _post("c-1-p1", text="another", score=5)
    raw_posts = list(sc.cluster.posts) + [_post("orphan", text="filtered out")]

    paths = exp.export(
        [sc],
        raw_posts,
        narrative={"headline": "h", "top_10": [], "honorable_mentions": []},
        out_dir=tmp_path,
        run_date=datetime(2026, 5, 12, tzinfo=UTC),
    )

    assert paths.dashboard_json.exists()
    assert paths.clusters_parquet.exists()
    assert paths.raw_parquet.exists()
    assert paths.run_id == "v2026-20"

    dashboard = json.loads(paths.dashboard_json.read_text())
    assert dashboard["schema_version"] == SCHEMA_VERSION
    assert len(dashboard["clusters"]) == 1
    assert dashboard["narrative"]["headline"] == "h"

    clusters_df = pd.read_parquet(paths.clusters_parquet)
    assert len(clusters_df) == 1
    assert clusters_df.iloc[0]["cluster_id"] == "c-1"
    assert clusters_df.iloc[0]["post_count"] == 2

    raw_df = pd.read_parquet(paths.raw_parquet)
    assert len(raw_df) == 3
    cluster_ids = set(raw_df["cluster_id"].dropna().unique())
    assert cluster_ids == {"c-1"}
    orphan_row = raw_df[raw_df["id"] == "orphan"]
    assert orphan_row["cluster_id"].isna().all()


def test_export_creates_out_dir_if_missing(tmp_path: Path) -> None:
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    sub = tmp_path / "nested" / "out"
    paths = exp.export([], [], out_dir=sub)
    assert sub.is_dir()
    assert paths.dashboard_json.exists()
