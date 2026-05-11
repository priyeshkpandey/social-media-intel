"""Unit tests for pipeline.sources.devto."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import devto


def _article(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 998877,
        "title": "How I cut our CI from 45 to 7 minutes",
        "description": "Caching, parallelization, and ruthless deletion.",
        "published_at": "2026-05-10T14:23:00.000Z",
        "url": "https://dev.to/example/how-i-cut-ci-998877",
        "canonical_url": "https://dev.to/example/how-i-cut-ci-998877",
        "public_reactions_count": 142,
        "comments_count": 27,
        "tag_list": ["devops", "testing"],
        "user": {"username": "octocat", "name": "Octo Cat"},
    }
    base.update(overrides)
    return base


def test_to_raw_post_basic() -> None:
    p = devto._to_raw_post(_article(), "devops")
    assert isinstance(p, RawPost)
    assert p.id == "devto:998877"
    assert p.source == "devto"
    assert p.author_handle == "octocat"
    assert "Caching, parallelization" in p.text
    assert p.score == 142
    assert p.replies_count == 27
    assert p.url.startswith("https://dev.to/")
    assert p.posted_at.tzinfo is not None


def test_to_raw_post_skips_without_id() -> None:
    a = _article()
    a.pop("id")
    assert devto._to_raw_post(a, "x") is None


def test_to_raw_post_skips_empty_text() -> None:
    assert devto._to_raw_post(_article(title="", description=""), "x") is None


def test_to_raw_post_bad_date() -> None:
    assert devto._to_raw_post(_article(published_at="not-a-date"), "x") is None


def test_to_raw_post_handles_missing_user() -> None:
    a = _article()
    a.pop("user")
    p = devto._to_raw_post(a, "x")
    assert p is not None
    assert p.author_handle is None


def test_fetch_tag_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = [_article(id=1, published_at="2026-05-10T00:00:00.000Z")] * 100
    page2 = [_article(id=200, published_at="2026-05-09T00:00:00.000Z")]
    pages = [page1, page2]
    monkeypatch.setattr(devto, "get_json", lambda url, params=None: pages.pop(0))
    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    out = list(devto._fetch_tag("devops", cutoff))
    assert len(out) == 101
    assert pages == []


def test_fetch_tag_stops_when_old_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    page = [
        _article(id=1, published_at="2026-05-10T00:00:00.000Z"),
        _article(id=2, published_at="2020-01-01T00:00:00.000Z"),
    ] + [_article(id=i + 3, published_at="2026-05-10T00:00:00.000Z") for i in range(98)]
    pages = [page]
    monkeypatch.setattr(devto, "get_json", lambda url, params=None: pages.pop(0))
    cutoff = datetime(2024, 1, 1, tzinfo=UTC)
    out = list(devto._fetch_tag("devops", cutoff))
    # All non-old articles on this page are yielded; pagination then stops.
    assert all(p.id != "devto:2" for p in out)
    assert pages == []


def test_fetch_tag_handles_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: Any = None) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(devto, "get_json", boom)
    out = list(devto._fetch_tag("devops", datetime(2024, 1, 1, tzinfo=UTC)))
    assert out == []


def test_fetch_tag_handles_unexpected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devto, "get_json", lambda url, params=None: {"oops": "object instead of list"})
    out = list(devto._fetch_tag("devops", datetime(2024, 1, 1, tzinfo=UTC)))
    assert out == []
