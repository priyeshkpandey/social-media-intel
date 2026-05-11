"""Unit tests for pipeline.stages.cluster.

We bypass UMAP and HDBSCAN by monkeypatching `_reduce` (identity) and
`_hdbscan` (returns a hand-crafted label vector). That lets the tests
exercise centroid matching, noise-point reattachment, c-TF-IDF labeling,
and state round-trip without pulling heavy ML deps.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from pipeline.models import NormalizedPost
from pipeline.stages import cluster as clu


def _post(post_id: str, text: str, day: int = 1) -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle=None,
        role=None,
        posted_at=datetime(2026, 5, day, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
        sentiment=0.0,
    )


def _vec(i: int, n: int = 4) -> np.ndarray:
    v = np.zeros(n, dtype=np.float32)
    v[i % n] = 1.0
    return v


def _force_clusters(monkeypatch: pytest.MonkeyPatch, labels: list[int]) -> None:
    monkeypatch.setattr(clu, "_reduce", lambda emb: emb)
    monkeypatch.setattr(clu, "_hdbscan", lambda red: np.array(labels))


# ---------- happy path: discover fresh clusters ----------


def test_fresh_clusters_get_new_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = [
        _post("a", "flaky tests are killing us"),
        _post("b", "ci pipeline is slow flaky tests"),
        _post("c", "kubernetes complexity"),
        _post("d", "k8s tax devops"),
    ]
    embs = np.stack([_vec(0), _vec(0), _vec(1), _vec(1)])
    _force_clusters(monkeypatch, labels=[0, 0, 1, 1])

    clusters, state = clu.cluster_posts(posts, embs)
    assert len(clusters) == 2
    ids = {c.id for c in clusters}
    assert all(cid.startswith("c-") for cid in ids)
    assert len(ids) == 2
    assert set(state.centroids) == ids

    # Labels are c-TF-IDF strings.
    labels = {c.label for c in clusters}
    assert all(isinstance(label, str) and label for label in labels)


# ---------- ID stability across runs via centroid matching ----------


def test_cluster_id_reused_when_centroid_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Run 1: one cluster anchored at axis 0.
    posts_a = [_post(f"a{i}", "ci pain") for i in range(3)]
    embs_a = np.stack([_vec(0)] * 3)
    _force_clusters(monkeypatch, labels=[0, 0, 0])
    clusters_a, state_a = clu.cluster_posts(posts_a, embs_a)
    assert len(clusters_a) == 1
    stable_id = clusters_a[0].id

    # Run 2: new posts, embeddings near axis 0 → should match prior centroid.
    posts_b = [_post(f"b{i}", "ci pain again") for i in range(3)]
    embs_b = np.stack([_vec(0) * 0.95 + _vec(2) * 0.05] * 3)
    _force_clusters(monkeypatch, labels=[0, 0, 0])
    clusters_b, state_b = clu.cluster_posts(posts_b, embs_b, prior_state=state_a)
    assert len(clusters_b) == 1
    assert clusters_b[0].id == stable_id
    assert state_b.first_seen[stable_id] == state_a.first_seen[stable_id]
    assert state_b.last_seen[stable_id] >= state_a.last_seen[stable_id]


def test_cluster_id_changes_when_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    posts_a = [_post(f"a{i}", "ci pain") for i in range(3)]
    embs_a = np.stack([_vec(0)] * 3)
    _force_clusters(monkeypatch, labels=[0, 0, 0])
    _, state_a = clu.cluster_posts(posts_a, embs_a)

    # Run 2: completely different axis — no prior centroid is close.
    posts_b = [_post(f"b{i}", "qa burnout") for i in range(3)]
    embs_b = np.stack([_vec(2)] * 3)  # orthogonal to prior centroid
    _force_clusters(monkeypatch, labels=[0, 0, 0])
    clusters_b, state_b = clu.cluster_posts(posts_b, embs_b, prior_state=state_a)
    assert len(clusters_b) == 1
    # New cluster ID, prior cluster still present in state.
    new_id = clusters_b[0].id
    assert new_id != list(state_a.centroids.keys())[0]
    assert new_id in state_b.centroids
    assert set(state_a.centroids).issubset(state_b.centroids)


# ---------- noise re-attachment ----------


def test_noise_post_attaches_to_nearby_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = [
        _post("a", "ci pain", day=1),
        _post("b", "ci pain", day=2),
        _post("c", "ci pain", day=3),
        _post("noise", "loose related ci stuff", day=4),
    ]
    embs = np.stack([_vec(0), _vec(0), _vec(0), _vec(0) * 0.9 + _vec(1) * 0.1])
    _force_clusters(monkeypatch, labels=[0, 0, 0, -1])

    clusters, _ = clu.cluster_posts(posts, embs)
    assert len(clusters) == 1
    member_ids = {p.id for p in clusters[0].posts}
    assert member_ids == {"a", "b", "c", "noise"}


def test_noise_post_dropped_when_far(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = [
        _post("a", "ci pain"),
        _post("b", "ci pain"),
        _post("c", "ci pain"),
        _post("noise", "totally unrelated"),
    ]
    embs = np.stack([_vec(0), _vec(0), _vec(0), _vec(2)])  # orthogonal noise
    _force_clusters(monkeypatch, labels=[0, 0, 0, -1])

    clusters, _ = clu.cluster_posts(posts, embs)
    assert len(clusters) == 1
    assert "noise" not in {p.id for p in clusters[0].posts}


# ---------- input validation + edge cases ----------


def test_empty_posts_returns_empty() -> None:
    clusters, state = clu.cluster_posts([], np.zeros((0, 4), dtype=np.float32))
    assert clusters == []
    assert state.centroids == {}


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        clu.cluster_posts([_post("x", "y")], np.zeros((2, 4)))


# ---------- c-TF-IDF labeling ----------


def test_ctfidf_labels_pick_distinguishing_terms() -> None:
    out = clu._ctfidf_labels(
        {
            0: ["flaky tests ci", "ci pipeline flaky", "flaky tests slow"],
            1: ["kubernetes complexity", "k8s networking", "kubernetes cluster"],
        }
    )
    assert "flaky" in out[0] or "tests" in out[0]
    assert "kubernetes" in out[1] or "k8s" in out[1] or "complexity" in out[1]


def test_ctfidf_labels_handles_empty_docs() -> None:
    out = clu._ctfidf_labels({0: [""], 1: [""]})
    assert out[0] == "unlabeled"
    assert out[1] == "unlabeled"


# ---------- state round-trip ----------


def test_state_save_and_load_roundtrip(tmp_path: Path) -> None:
    state = clu.ClusterState(
        centroids={
            "c-aaa": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "c-bbb": np.array([0.0, 1.0, 0.0], dtype=np.float32),
        },
        labels={"c-aaa": "ci pain", "c-bbb": "k8s"},
        first_seen={
            "c-aaa": datetime(2026, 1, 1, tzinfo=UTC),
            "c-bbb": datetime(2026, 2, 1, tzinfo=UTC),
        },
        last_seen={
            "c-aaa": datetime(2026, 5, 1, tzinfo=UTC),
            "c-bbb": datetime(2026, 5, 8, tzinfo=UTC),
        },
    )
    p = tmp_path / "state.parquet"
    clu.save_state(state, p)
    loaded = clu.load_state(p)
    assert set(loaded.centroids) == {"c-aaa", "c-bbb"}
    np.testing.assert_allclose(loaded.centroids["c-aaa"], state.centroids["c-aaa"])
    assert loaded.labels["c-bbb"] == "k8s"
    assert loaded.first_seen["c-aaa"] == datetime(2026, 1, 1, tzinfo=UTC)


def test_state_load_missing_file_returns_empty(tmp_path: Path) -> None:
    loaded = clu.load_state(tmp_path / "nope.parquet")
    assert loaded.centroids == {}


def test_state_save_empty_writes_marker(tmp_path: Path) -> None:
    p = tmp_path / "empty.parquet"
    clu.save_state(clu.ClusterState(), p)
    assert p.exists()
    assert p.stat().st_size == 0


# ---------- best_match ----------


def test_best_match_returns_none_below_threshold() -> None:
    out = clu._best_match(
        np.array([1.0, 0.0]),
        {"c-x": np.array([0.0, 1.0])},
        threshold=0.6,
        exclude=set(),
    )
    assert out is None


def test_best_match_skips_excluded() -> None:
    cands = {
        "c-x": np.array([1.0, 0.0]),
        "c-y": np.array([0.99, 0.05]),
    }
    out = clu._best_match(
        np.array([1.0, 0.0]),
        cands,
        threshold=0.6,
        exclude={"c-x"},
    )
    assert out == "c-y"
