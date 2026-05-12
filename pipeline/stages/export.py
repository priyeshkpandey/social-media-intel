"""Export stage — emit dashboard.json, clusters.parquet, raw.parquet.

`build_dashboard()` is a pure function: it takes scored clusters + the
optional weekly narrative and returns the dict the dashboard renders. It
has no I/O and no heavy deps, so it can be unit-tested without pandas.

`export()` writes all three artifacts to disk. The parquet writers
lazy-import pandas; if you only need dashboard.json, `build_dashboard()`
is enough.

Artifact contract (BUILD_PROMPT.md §6.6):
  * dashboard.json — ≤2MB. Schema-versioned (`schema_version: 1`). Per-cluster
    text fields are truncated; the full text lives in raw.parquet.
  * clusters.parquet — one row per cluster, with nested fields serialized
    to JSON strings (cost summary, role_top, synthesis) for compact storage.
  * raw.parquet — one row per normalized post, with `cluster_id` linking to
    clusters.parquet (nullable for filtered-out posts).

The 12-month rolling time series the dashboard needs is reconstructed
client-side by stitching prior GitHub Releases — see METHODOLOGY.md.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.config import OUT_DIR, SCHEMA_VERSION
from pipeline.models import NormalizedPost, ScoredCluster

log = logging.getLogger(__name__)

_REPRESENTATIVE_POSTS_PER_CLUSTER = 10
_REPRESENTATIVE_POST_TEXT_LEN = 500
_NEW_CLUSTER_WINDOW_DAYS = 7


@dataclass(slots=True)
class ExportPaths:
    """File paths of the artifacts written by `export()`."""

    dashboard_json: Path
    clusters_parquet: Path
    raw_parquet: Path
    run_id: str


# ---------------------------------------------------------------------------
# Pure dashboard-shape builder
# ---------------------------------------------------------------------------


def build_dashboard(
    scored_clusters: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    *,
    run_date: datetime | None = None,
    heuristic_only: bool | None = None,
) -> dict[str, Any]:
    """Construct the dashboard.json dict the static site renders.

    `heuristic_only` defaults to True when no cluster has a `synthesis`
    attached (e.g., the synthesize stage ran without ANTHROPIC_API_KEY).
    Pass it explicitly to override.
    """
    run_date = run_date or datetime.now(UTC)
    if heuristic_only is None:
        heuristic_only = all(sc.synthesis is None for sc in scored_clusters)

    cluster_dicts = [_cluster_to_dict(sc) for sc in scored_clusters]
    kpi = _kpi(scored_clusters, run_date)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": run_date.isoformat(),
        "run_id": iso_week_id(run_date),
        "heuristic_only": heuristic_only,
        "kpi": kpi,
        "narrative": narrative,
        "clusters": cluster_dicts,
    }


def iso_week_id(dt: datetime) -> str:
    """Tag the run by ISO year + week (matches the GitHub Release tag scheme)."""
    year, week, _ = dt.isocalendar()
    return f"v{year}-{week:02d}"


def _kpi(scored: list[ScoredCluster], run_date: datetime) -> dict[str, Any]:
    total_posts = sum(len(sc.cluster.posts) for sc in scored)
    cutoff = run_date - timedelta(days=_NEW_CLUSTER_WINDOW_DAYS)
    new_clusters = sum(1 for sc in scored if sc.cluster.first_seen >= cutoff)
    opportunities = [sc.opportunity for sc in scored]
    mean_opp = sum(opportunities) / len(opportunities) if opportunities else 0.0
    return {
        "total_posts_this_week": total_posts,
        "active_clusters": len(scored),
        "new_clusters_this_week": new_clusters,
        "mean_opportunity": round(mean_opp, 2),
    }


def _cluster_to_dict(sc: ScoredCluster) -> dict[str, Any]:
    posts = sorted(sc.cluster.posts, key=lambda p: (-p.score, -p.replies_count))[
        :_REPRESENTATIVE_POSTS_PER_CLUSTER
    ]
    return {
        "id": sc.cluster.id,
        "label": sc.cluster.label,
        "title": sc.synthesis.title if sc.synthesis else sc.cluster.label,
        "frequency_per_week": round(sc.frequency_per_week, 2),
        "frequency_zscore": round(sc.frequency_zscore, 3),
        "opportunity": round(sc.opportunity, 2),
        "feasibility": sc.feasibility,
        "impl_cost_band": sc.impl_cost_band,
        "cost": asdict(sc.cost),
        "role_top": [{"role": r, "share": round(s, 3)} for r, s in sc.role_top],
        "first_seen": sc.cluster.first_seen.isoformat(),
        "last_seen": sc.cluster.last_seen.isoformat(),
        "post_count": len(sc.cluster.posts),
        "synthesis": _synthesis_dict(sc),
        "representative_posts": [_post_to_dict(p) for p in posts],
    }


def _synthesis_dict(sc: ScoredCluster) -> dict[str, Any] | None:
    if sc.synthesis is None:
        return None
    d = asdict(sc.synthesis)
    d["confidence"] = round(d["confidence"], 3)
    return d


def _post_to_dict(p: NormalizedPost) -> dict[str, Any]:
    text = p.text
    if len(text) > _REPRESENTATIVE_POST_TEXT_LEN:
        text = text[:_REPRESENTATIVE_POST_TEXT_LEN].rstrip() + "…"
    return {
        "id": p.id,
        "source": p.source,
        "role": p.role,
        "url": p.url,
        "score": p.score,
        "replies_count": p.replies_count,
        "text": text,
        "posted_at": p.posted_at.isoformat(),
        "sentiment": round(p.sentiment, 3),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def export(
    scored_clusters: list[ScoredCluster],
    normalized_posts: Iterable[NormalizedPost],
    *,
    narrative: dict[str, Any] | None = None,
    out_dir: str | Path = OUT_DIR,
    run_date: datetime | None = None,
    heuristic_only: bool | None = None,
) -> ExportPaths:
    """Write all three artifacts to `out_dir` and return their paths."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    run_date = run_date or datetime.now(UTC)

    dashboard = build_dashboard(
        scored_clusters,
        narrative,
        run_date=run_date,
        heuristic_only=heuristic_only,
    )
    dashboard_path = out_path / "dashboard.json"
    dashboard_path.write_text(json.dumps(dashboard, indent=2), encoding="utf-8")

    cluster_index = {p.id: sc.cluster.id for sc in scored_clusters for p in sc.cluster.posts}

    clusters_path = out_path / "clusters.parquet"
    _write_clusters_parquet(scored_clusters, clusters_path)

    raw_path = out_path / "raw.parquet"
    _write_raw_parquet(normalized_posts, cluster_index, raw_path)

    run_id = iso_week_id(run_date)
    log.info("export: wrote %s, %s, %s for run %s", dashboard_path, clusters_path, raw_path, run_id)
    return ExportPaths(dashboard_path, clusters_path, raw_path, run_id)


# ---------------------------------------------------------------------------
# Parquet writers (pandas lazy-imported)
# ---------------------------------------------------------------------------


def _write_clusters_parquet(scored: list[ScoredCluster], path: Path) -> None:
    import pandas as pd  # noqa: PLC0415

    rows = [
        {
            "cluster_id": sc.cluster.id,
            "label": sc.cluster.label,
            "title": sc.synthesis.title if sc.synthesis else sc.cluster.label,
            "opportunity": sc.opportunity,
            "feasibility": sc.feasibility,
            "impl_cost_band": sc.impl_cost_band,
            "frequency_per_week": sc.frequency_per_week,
            "frequency_zscore": sc.frequency_zscore,
            "first_seen": sc.cluster.first_seen,
            "last_seen": sc.cluster.last_seen,
            "post_count": len(sc.cluster.posts),
            "cost_json": json.dumps(asdict(sc.cost)),
            "role_top_json": json.dumps(
                [{"role": r, "share": s} for r, s in sc.role_top]
            ),
            "synthesis_json": (
                json.dumps(asdict(sc.synthesis)) if sc.synthesis else None
            ),
        }
        for sc in scored
    ]
    pd.DataFrame(rows).to_parquet(path)


def _write_raw_parquet(
    posts: Iterable[NormalizedPost],
    cluster_index: dict[str, str],
    path: Path,
) -> None:
    import pandas as pd  # noqa: PLC0415

    rows = [
        {
            "id": p.id,
            "source": p.source,
            "author_handle": p.author_handle,
            "role": p.role,
            "posted_at": p.posted_at,
            "url": p.url,
            "text": p.text,
            "score": p.score,
            "replies_count": p.replies_count,
            "sentiment": p.sentiment,
            "cluster_id": cluster_index.get(p.id),
            "cost_mentions_json": json.dumps(
                [asdict(cm) for cm in p.cost_mentions]
            ),
        }
        for p in posts
    ]
    pd.DataFrame(rows).to_parquet(path)
