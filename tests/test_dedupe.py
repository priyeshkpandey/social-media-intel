"""Unit tests for pipeline.stages.dedupe."""

from __future__ import annotations

from datetime import UTC, datetime

from pipeline.models import NormalizedPost
from pipeline.stages import dedupe as dd


def _post(post_id: str, text: str) -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle=None,
        role=None,
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
        sentiment=0.0,
    )


def test_dedupe_drops_duplicate_ids() -> None:
    a = _post("id1", "alpha")
    b = _post("id1", "beta")  # different text but same id → drop
    out = list(dd.dedupe([a, b]))
    assert [p.id for p in out] == ["id1"]
    assert out[0].text == "alpha"


def test_dedupe_drops_text_duplicates_across_sources() -> None:
    a = _post("hn:1", "Same article body about CI flakiness " * 5)
    b = _post("lobsters:abc", "Same article body about CI flakiness " * 5)
    out = list(dd.dedupe([a, b]))
    assert len(out) == 1
    assert out[0].id == "hn:1"


def test_dedupe_keeps_unique_posts() -> None:
    posts = [_post(f"id{i}", f"unique text {i}") for i in range(3)]
    out = list(dd.dedupe(posts))
    assert len(out) == 3
    assert [p.id for p in out] == ["id0", "id1", "id2"]


def test_text_fingerprint_ignores_case_and_whitespace() -> None:
    a = dd.text_fingerprint("Hello   World\n\nfoo")
    b = dd.text_fingerprint("hello world foo")
    assert a == b


def test_text_fingerprint_truncates_at_prefix_len() -> None:
    a = dd.text_fingerprint("x" * 800)
    b = dd.text_fingerprint("x" * 1000)
    # Both canonicalize to the same first-500 prefix.
    assert a == b
