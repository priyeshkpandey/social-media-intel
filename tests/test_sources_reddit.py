"""Unit tests for pipeline.sources.reddit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import reddit


def _post_data(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "abc",
        "title": "Flaky tests are killing me",
        "selftext": "It's been months of red CI",
        "author": "alice",
        "created_utc": 1747008000.0,
        "score": 42,
        "num_comments": 7,
        "permalink": "/r/ExperiencedDevs/comments/abc",
        "stickied": False,
        "is_video": False,
    }
    base.update(overrides)
    return base


def _listing(children_data: list[dict[str, Any]], after: str | None = None) -> dict[str, Any]:
    return {
        "data": {
            "children": [{"data": d} for d in children_data],
            "after": after,
        }
    }


def test_to_raw_post_basic() -> None:
    p = reddit._to_raw_post(_post_data(), "ExperiencedDevs", "engineer")
    assert isinstance(p, RawPost)
    assert p.id == "reddit:abc"
    assert p.source == "reddit"
    assert p.author_handle == "alice"
    assert p.author_role_hint == "engineer"
    assert "Flaky tests" in p.text
    assert "red CI" in p.text
    assert p.score == 42
    assert p.replies_count == 7
    assert p.url == "https://www.reddit.com/r/ExperiencedDevs/comments/abc"


def test_to_raw_post_skips_stickied() -> None:
    assert reddit._to_raw_post(_post_data(stickied=True), "x", "engineer") is None


def test_to_raw_post_skips_videos() -> None:
    assert reddit._to_raw_post(_post_data(is_video=True), "x", "engineer") is None


def test_to_raw_post_skips_empty_text() -> None:
    assert reddit._to_raw_post(_post_data(title="", selftext=""), "x", "engineer") is None


def test_to_raw_post_missing_id() -> None:
    data = _post_data()
    data.pop("id")
    assert reddit._to_raw_post(data, "x", "engineer") is None


def test_fetch_subreddit_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = _listing(
        [
            _post_data(id="p1", created_utc=1747008000.0),
            _post_data(id="p2", created_utc=1746908000.0),
        ],
        after="t3_p2",
    )
    page2 = _listing([_post_data(id="p3", created_utc=1746808000.0)], after=None)
    pages = [page1, page2]
    monkeypatch.setattr(reddit, "get_json", lambda url, params=None: pages.pop(0))

    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    out = list(reddit._fetch_subreddit("ExperiencedDevs", "engineer", cutoff))
    assert [p.id for p in out] == ["reddit:p1", "reddit:p2", "reddit:p3"]
    assert pages == []  # both pages consumed


def test_fetch_subreddit_stops_at_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # `new` is reverse-chronological — p_new newer than p_old.
    page = _listing(
        [
            _post_data(id="p_new", created_utc=1747008000.0),  # 2025-05-12
            _post_data(id="p_old", created_utc=1577836800.0),  # 2020-01-01
        ],
    )
    monkeypatch.setattr(reddit, "get_json", lambda url, params=None: page)
    cutoff = datetime(2024, 1, 1, tzinfo=UTC)
    out = list(reddit._fetch_subreddit("ExperiencedDevs", "engineer", cutoff))
    ids = [p.id for p in out]
    assert ids == ["reddit:p_new"]


def test_fetch_subreddit_handles_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: Any = None) -> dict[str, Any]:
        raise RuntimeError("simulated network failure")

    monkeypatch.setattr(reddit, "get_json", boom)
    out = list(
        reddit._fetch_subreddit("ExperiencedDevs", "engineer", datetime(2024, 1, 1, tzinfo=UTC))
    )
    assert out == []
