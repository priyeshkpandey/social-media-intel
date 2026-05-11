"""Unit tests for pipeline.stages.filter."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from pipeline.models import NormalizedPost
from pipeline.stages import filter as flt


def _post(text: str, post_id: str = "x") -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle=None,
        role="engineer",
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
        sentiment=0.0,
    )


# ---------- cheap_pass ----------


def test_cheap_pass_keeps_allow_keyword() -> None:
    assert flt.cheap_pass("Our CI pipeline takes forever.")  # 'ci/cd' is in allow
    assert flt.cheap_pass("Burnout is real on the devops team.")
    assert flt.cheap_pass("As a product manager I'm tired.")


def test_cheap_pass_drops_block_keyword_even_if_allow_present() -> None:
    # 'we're hiring' is a block phrase; 'devops' is allow
    assert not flt.cheap_pass("We're hiring devops engineers, apply now!")


def test_cheap_pass_drops_block_only() -> None:
    assert not flt.cheap_pass("Crypto pump and dump, NFT airdrop incoming.")


def test_cheap_pass_drops_neutral() -> None:
    assert not flt.cheap_pass("Have a great Monday everyone!")


# ---------- SemanticFilter ----------


class _FakeEmbedder:
    """Deterministic embedder: 'pain'-flavored texts get vector [1, 0],
    others get [0, 1]. The anchors are 'pain' texts → keep iff vec[0] == 1.
    """

    def __init__(self, pain_marker: str = "pain") -> None:
        self.pain_marker = pain_marker

    def __call__(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), 2), dtype=np.float32)
        for i, t in enumerate(texts):
            if self.pain_marker in t.lower():
                out[i, 0] = 1.0
            else:
                out[i, 1] = 1.0
        return out


def test_semantic_filter_keeps_similar() -> None:
    sf = flt.SemanticFilter(
        embed_fn=_FakeEmbedder(),
        anchors=("on-call pain",),
        threshold=0.5,
    )
    decisions = sf.keep_many(["I have CI pain", "great weather today"])
    assert decisions == [True, False]


def test_semantic_filter_threshold_respected() -> None:
    embedder = _FakeEmbedder()
    # Threshold 1.1 — nothing can clear it.
    sf = flt.SemanticFilter(embed_fn=embedder, anchors=("pain",), threshold=1.1)
    assert sf.keep_many(["pain pain pain"]) == [False]


def test_semantic_filter_empty_input() -> None:
    sf = flt.SemanticFilter(embed_fn=_FakeEmbedder(), anchors=("pain",), threshold=0.5)
    assert sf.keep_many([]) == []


def test_semantic_filter_rejects_empty_anchors() -> None:
    with pytest.raises(ValueError):
        flt.SemanticFilter(embed_fn=_FakeEmbedder(), anchors=(), threshold=0.5)


# ---------- filter_posts orchestration ----------


def test_filter_posts_cheap_only() -> None:
    posts = [
        _post("Our CI pipeline is broken.", "p1"),
        _post("Crypto NFT moon!", "p2"),
        _post("As a product manager I'm tired.", "p3"),
    ]
    out = list(flt.filter_posts(posts))
    ids = [p.id for p in out]
    assert ids == ["p1", "p3"]


def test_filter_posts_with_semantic() -> None:
    sf = flt.SemanticFilter(embed_fn=_FakeEmbedder(), anchors=("on-call pain",), threshold=0.5)
    posts = [
        _post("Our CI pain is real on devops team.", "p1"),  # cheap keep + semantic keep
        _post("Generic devops blog post.", "p2"),  # cheap keep + semantic drop
        _post("Have a great Monday!", "p3"),  # cheap drop
        _post("We're hiring devops engineers.", "p4"),  # blocked
    ]
    out = list(flt.filter_posts(posts, semantic_filter=sf))
    assert [p.id for p in out] == ["p1"]
