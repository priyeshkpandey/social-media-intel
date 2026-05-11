"""Cluster stage — UMAP → HDBSCAN with cross-run centroid persistence.

Outputs `list[Cluster]` and an updated `ClusterState`. State persists as
parquet at `./.cache/cluster_state.parquet` so cluster IDs are stable
week-over-week: each HDBSCAN-discovered cluster is matched to a prior
centroid (cosine ≥ CENTROID_REASSIGN_THRESHOLD) and reuses its ID/label
when found. HDBSCAN noise points are attached to the closest matching
centroid (if any) and otherwise dropped.

Heavy deps (umap-learn, hdbscan, scikit-learn, pandas) are imported lazily
so test collection doesn't require them.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from pipeline.config import (
    CACHE_DIR,
    CENTROID_REASSIGN_THRESHOLD,
    HDBSCAN_MIN_CLUSTER_SIZE,
    HDBSCAN_MIN_SAMPLES,
    UMAP_MIN_DIST,
    UMAP_N_COMPONENTS,
    UMAP_N_NEIGHBORS,
)
from pipeline.models import Cluster, NormalizedPost

log = logging.getLogger(__name__)

STATE_PATH = Path(CACHE_DIR) / "cluster_state.parquet"
_LABEL_TOP_N = 3
_LABEL_MAX_FEATURES = 5000


@dataclass(slots=True)
class ClusterState:
    """Persisted snapshot of every cluster the pipeline has ever produced."""

    centroids: dict[str, np.ndarray] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    first_seen: dict[str, datetime] = field(default_factory=dict)
    last_seen: dict[str, datetime] = field(default_factory=dict)


def cluster_posts(
    posts: list[NormalizedPost],
    embeddings: np.ndarray,
    prior_state: ClusterState | None = None,
) -> tuple[list[Cluster], ClusterState]:
    """Cluster `posts` (with parallel `embeddings`) and return clusters + new state."""
    if len(posts) != len(embeddings):
        raise ValueError(
            f"posts/embeddings length mismatch: {len(posts)} vs {len(embeddings)}"
        )
    if prior_state is None:
        prior_state = ClusterState()

    if not posts:
        return [], prior_state

    reduced = _reduce(embeddings)
    raw_labels = _hdbscan(reduced)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx, lbl in enumerate(raw_labels):
        groups[int(lbl)].append(idx)

    new_centroids = dict(prior_state.centroids)
    new_labels = dict(prior_state.labels)
    new_first_seen = dict(prior_state.first_seen)
    new_last_seen = dict(prior_state.last_seen)

    # First pass: real (non-noise) clusters get a centroid and an ID.
    real_groups = {hid: ix for hid, ix in groups.items() if hid != -1}
    cluster_centroids = {
        hid: embeddings[ix].mean(axis=0) for hid, ix in real_groups.items()
    }
    cluster_texts = {
        hid: [posts[i].text for i in ix] for hid, ix in real_groups.items()
    }
    fresh_labels = _ctfidf_labels(cluster_texts) if cluster_texts else {}

    assigned_id: dict[int, str] = {}
    used_ids: set[str] = set()
    for hid, centroid in cluster_centroids.items():
        match = _best_match(
            centroid, prior_state.centroids, CENTROID_REASSIGN_THRESHOLD, used_ids
        )
        if match is not None:
            cid = match
        else:
            cid = _new_cluster_id()
        assigned_id[hid] = cid
        used_ids.add(cid)

    # Second pass: build Cluster objects, update state.
    clusters: list[Cluster] = []
    by_id: dict[str, Cluster] = {}
    for hid, indices in real_groups.items():
        cid = assigned_id[hid]
        centroid = cluster_centroids[hid]
        members = [posts[i] for i in indices]

        label = new_labels.get(cid) or fresh_labels.get(hid, "unlabeled")
        first_seen = min(
            (new_first_seen.get(cid) or datetime.max.replace(tzinfo=members[0].posted_at.tzinfo)),
            min(p.posted_at for p in members),
        )
        last_seen = max(
            (new_last_seen.get(cid) or datetime.min.replace(tzinfo=members[0].posted_at.tzinfo)),
            max(p.posted_at for p in members),
        )

        cluster = Cluster(
            id=cid,
            label=label,
            centroid=centroid.astype(np.float32).tolist(),
            posts=members,
            first_seen=first_seen,
            last_seen=last_seen,
        )
        clusters.append(cluster)
        by_id[cid] = cluster

        new_centroids[cid] = centroid.astype(np.float32)
        new_labels[cid] = label
        new_first_seen[cid] = first_seen
        new_last_seen[cid] = last_seen

    # Third pass: try to attach HDBSCAN noise points to *any* existing centroid.
    for idx in groups.get(-1, []):
        cid = _best_match(
            embeddings[idx], new_centroids, CENTROID_REASSIGN_THRESHOLD, exclude=set()
        )
        if cid is None or cid not in by_id:
            continue
        cluster = by_id[cid]
        cluster.posts.append(posts[idx])
        cluster.last_seen = max(cluster.last_seen, posts[idx].posted_at)
        new_last_seen[cid] = cluster.last_seen

    new_state = ClusterState(
        centroids=new_centroids,
        labels=new_labels,
        first_seen=new_first_seen,
        last_seen=new_last_seen,
    )
    log.info(
        "cluster: produced %d clusters (state now has %d known)",
        len(clusters),
        len(new_centroids),
    )
    return clusters, new_state


def _reduce(embeddings: np.ndarray) -> np.ndarray:
    """UMAP to UMAP_N_COMPONENTS dims when we have enough points; else passthrough."""
    n = len(embeddings)
    if n < UMAP_N_NEIGHBORS + 1 or n <= UMAP_N_COMPONENTS:
        log.info("cluster: skipping UMAP (n=%d too small)", n)
        return embeddings
    import umap  # noqa: PLC0415

    reducer = umap.UMAP(
        n_components=UMAP_N_COMPONENTS,
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        metric="cosine",
        random_state=42,
    )
    return reducer.fit_transform(embeddings)


def _hdbscan(reduced: np.ndarray) -> np.ndarray:
    import hdbscan  # noqa: PLC0415

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric="euclidean",
    )
    return clusterer.fit_predict(reduced)


def _best_match(
    vector: np.ndarray,
    candidates: dict[str, np.ndarray],
    threshold: float,
    exclude: set[str] | None,
) -> str | None:
    """Return the candidate ID with highest cosine similarity to `vector`, if ≥ threshold."""
    if not candidates:
        return None
    exclude = exclude or set()
    v = vector / (np.linalg.norm(vector) or 1.0)
    best_id: str | None = None
    best_sim = threshold
    for cid, c in candidates.items():
        if cid in exclude:
            continue
        cn = c / (np.linalg.norm(c) or 1.0)
        sim = float(np.dot(v, cn))
        if sim > best_sim:
            best_sim = sim
            best_id = cid
    return best_id


def _ctfidf_labels(cluster_texts: dict[int, list[str]]) -> dict[int, str]:
    """c-TF-IDF: treat each cluster as a single doc; pick top distinguishing terms."""
    from sklearn.feature_extraction.text import CountVectorizer  # noqa: PLC0415

    keys = list(cluster_texts.keys())
    docs = [" ".join(cluster_texts[k]) for k in keys]
    if not any(d.strip() for d in docs):
        return {k: "unlabeled" for k in keys}

    try:
        cv = CountVectorizer(
            max_features=_LABEL_MAX_FEATURES,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
        )
        counts = cv.fit_transform(docs).toarray()
    except ValueError:
        return {k: "unlabeled" for k in keys}

    terms = cv.get_feature_names_out()
    words_per_cluster = counts.sum(axis=1)
    avg_words = float(words_per_cluster.mean()) if words_per_cluster.size else 1.0
    cf = counts.sum(axis=0)
    cidf = np.log(1.0 + avg_words / np.maximum(cf, 1))
    ctfidf = counts * cidf

    out: dict[int, str] = {}
    for i, key in enumerate(keys):
        top_idx = ctfidf[i].argsort()[::-1][:_LABEL_TOP_N]
        out[key] = " / ".join(terms[j] for j in top_idx if ctfidf[i, j] > 0) or "unlabeled"
    return out


def _new_cluster_id() -> str:
    return f"c-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


def save_state(state: ClusterState, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not state.centroids:
        # Write an empty marker file so the cache key changes meaningfully.
        path.write_bytes(b"")
        return
    import pandas as pd  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    for cid, centroid in state.centroids.items():
        rows.append(
            {
                "cluster_id": cid,
                "centroid": centroid.astype(np.float32).tolist(),
                "label": state.labels.get(cid, ""),
                "first_seen": state.first_seen.get(cid),
                "last_seen": state.last_seen.get(cid),
            }
        )
    pd.DataFrame(rows).to_parquet(path)


def load_state(path: Path = STATE_PATH) -> ClusterState:
    if not path.exists() or path.stat().st_size == 0:
        return ClusterState()
    import pandas as pd  # noqa: PLC0415

    df = pd.read_parquet(path)
    centroids: dict[str, np.ndarray] = {}
    labels: dict[str, str] = {}
    first_seen: dict[str, datetime] = {}
    last_seen: dict[str, datetime] = {}
    for _, row in df.iterrows():
        cid = str(row["cluster_id"])
        centroids[cid] = np.asarray(row["centroid"], dtype=np.float32)
        labels[cid] = str(row.get("label") or "")
        first_seen[cid] = row.get("first_seen")
        last_seen[cid] = row.get("last_seen")
    return ClusterState(centroids, labels, first_seen, last_seen)
