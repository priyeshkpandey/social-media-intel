"""Unit tests for pipeline.sources.hackernews."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import hackernews


def _hit(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "objectID": "12345",
        "title": "Ask HN: How do you keep CI fast?",
        "story_text": "Our pipeline takes 45 minutes per commit.",
        "author": "bob",
        "created_at_i": 1747008000,
        "points": 28,
        "num_comments": 12,
        "_tags": ["ask_hn", "story", "author_bob"],
    }
    base.update(overrides)
    return base


def test_to_raw_post_basic() -> None:
    p = hackernews._to_raw_post(_hit())
    assert isinstance(p, RawPost)
    assert p.id == "hn:12345"
    assert p.source == "hackernews"
    assert p.author_handle == "bob"
    assert p.author_role_hint is None
    assert "Ask HN" in p.text
    assert "45 minutes" in p.text
    assert p.url == "https://news.ycombinator.com/item?id=12345"
    assert p.score == 28
    assert p.replies_count == 12


def test_to_raw_post_uses_comment_text_when_no_story_text() -> None:
    hit = _hit(story_text=None, comment_text="Comment body")
    p = hackernews._to_raw_post(hit)
    assert p is not None
    assert "Comment body" in p.text


def test_to_raw_post_skips_without_id() -> None:
    hit = _hit()
    hit.pop("objectID")
    assert hackernews._to_raw_post(hit) is None


def test_to_raw_post_skips_empty_text() -> None:
    assert hackernews._to_raw_post(_hit(title="", story_text="", comment_text=None)) is None


def test_to_raw_post_handles_missing_points() -> None:
    p = hackernews._to_raw_post(_hit(points=None, num_comments=None))
    assert p is not None
    assert p.score == 0
    assert p.replies_count == 0


def test_fetch_query_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    page0 = {
        "hits": [_hit(objectID="1", created_at_i=1747000000)],
        "nbPages": 2,
    }
    page1 = {
        "hits": [_hit(objectID="2", created_at_i=1747000001)],
        "nbPages": 2,
    }
    pages = [page0, page1]
    monkeypatch.setattr(hackernews, "get_json", lambda url, params=None: pages.pop(0))

    out = list(hackernews._fetch_query("ci pipeline", "story", since_ts=1700000000))
    assert [p.id for p in out] == ["hn:1", "hn:2"]
    assert pages == []


def test_fetch_query_stops_at_nb_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    page0 = {"hits": [_hit(objectID="1", created_at_i=1747000000)], "nbPages": 1}
    calls = {"n": 0}

    def fake_get(url: str, params: Any = None) -> dict[str, Any]:
        calls["n"] += 1
        return page0

    monkeypatch.setattr(hackernews, "get_json", fake_get)
    out = list(hackernews._fetch_query("q", "story", since_ts=0))
    assert [p.id for p in out] == ["hn:1"]
    assert calls["n"] == 1


def test_fetch_query_handles_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: Any = None) -> dict[str, Any]:
        raise RuntimeError("network down")

    monkeypatch.setattr(hackernews, "get_json", boom)
    out = list(hackernews._fetch_query("q", "story", since_ts=0))
    assert out == []


def test_fetch_passes_since_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_get(url: str, params: Any = None) -> dict[str, Any]:
        captured.append(params or {})
        return {"hits": [], "nbPages": 0}

    monkeypatch.setattr(hackernews, "get_json", fake_get)
    since = datetime(2026, 5, 1, tzinfo=UTC)
    list(hackernews.fetch(since))
    assert captured  # at least one call was made
    expected = f"created_at_i>{int(since.timestamp())}"
    assert all(p.get("numericFilters") == expected for p in captured)
