"""Unit tests for pipeline.sources.lobsters."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import lobsters


class FakeEntry(dict):
    """dict subclass that also supports attribute access, like feedparser entries."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e


def _entry(**overrides: Any) -> FakeEntry:
    base: dict[str, Any] = {
        "id": "https://lobste.rs/s/abc123/flaky_tests",
        "link": "https://lobste.rs/s/abc123/flaky_tests",
        "title": "Flaky tests, one more time",
        "summary": "Yet another postmortem on test reliability.",
        "published_parsed": time.struct_time((2026, 5, 10, 14, 23, 0, 0, 0, 0)),
        "author": "carla",
        "tags": [{"term": "testing"}, {"term": "qa"}],
    }
    base.update(overrides)
    return FakeEntry(base)


def test_to_raw_post_basic() -> None:
    p = lobsters._to_raw_post(_entry())
    assert isinstance(p, RawPost)
    assert p.id == "lobsters:abc123"
    assert p.source == "lobsters"
    assert p.author_handle == "carla"
    assert "Flaky tests" in p.text
    assert p.posted_at.tzinfo is UTC
    assert p.url == "https://lobste.rs/s/abc123/flaky_tests"


def test_to_raw_post_uses_author_detail_when_author_missing() -> None:
    e = _entry()
    del e["author"]
    e["author_detail"] = {"name": "dora"}
    p = lobsters._to_raw_post(e)
    assert p is not None
    assert p.author_handle == "dora"


def test_to_raw_post_skips_without_link() -> None:
    e = _entry()
    del e["link"]
    del e["id"]
    assert lobsters._to_raw_post(e) is None


def test_to_raw_post_skips_empty_text() -> None:
    e = _entry(title="", summary="")
    assert lobsters._to_raw_post(e) is None


def test_to_raw_post_skips_bad_date() -> None:
    e = _entry()
    e["published_parsed"] = None
    e["updated_parsed"] = None
    assert lobsters._to_raw_post(e) is None


def test_fetch_filters_by_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    new_entry = _entry()
    old_entry = _entry(
        id="https://lobste.rs/s/old111/old",
        link="https://lobste.rs/s/old111/old",
        published_parsed=time.struct_time((2020, 1, 1, 0, 0, 0, 0, 0, 0)),
    )
    fake_feed = type(
        "F",
        (),
        {"entries": [new_entry, old_entry], "bozo": False, "bozo_exception": None},
    )()
    monkeypatch.setattr(lobsters.feedparser, "parse", lambda _: fake_feed)
    out = list(lobsters.fetch(datetime(2024, 1, 1, tzinfo=UTC)))
    ids = [p.id for p in out]
    assert "lobsters:abc123" in ids
    assert "lobsters:old111" not in ids
