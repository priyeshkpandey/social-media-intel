"""Unit tests for pipeline.sources.lemmy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import lemmy


def _entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "post": {
            "id": 12345,
            "name": "Our CI pipeline is melting",
            "body": "We've been chasing flaky tests for 3 weeks. Engineer-days lost.",
            "published": "2026-05-10T14:23:00.000Z",
            "ap_id": "https://programming.dev/post/12345",
        },
        "creator": {"name": "alice", "actor_id": "https://programming.dev/u/alice"},
        "community": {"name": "programming", "title": "Programming"},
        "counts": {"score": 42, "comments": 7, "upvotes": 50, "downvotes": 8},
    }
    # Allow per-field overrides on the nested `post` dict
    if "post" in overrides:
        base["post"].update(overrides.pop("post"))
    base.update(overrides)
    return base


def _list_resp(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"posts": entries}


def test_to_raw_post_basic() -> None:
    p = lemmy._to_raw_post(_entry(), "programming.dev", "programming", "engineer")
    assert isinstance(p, RawPost)
    assert p.id == "lemmy:programming.dev:12345"
    assert p.source == "lemmy"
    assert p.author_handle == "alice"
    assert p.author_role_hint == "engineer"
    assert "CI pipeline" in p.text
    assert "flaky tests" in p.text
    assert p.score == 42
    assert p.replies_count == 7
    assert p.url == "https://programming.dev/post/12345"
    assert p.raw == {"instance": "programming.dev", "community": "programming"}


def test_to_raw_post_falls_back_to_instance_url_when_ap_id_missing() -> None:
    e = _entry()
    e["post"].pop("ap_id")
    p = lemmy._to_raw_post(e, "lemmy.ml", "programming", "engineer")
    assert p is not None
    assert p.url == "https://lemmy.ml/post/12345"


def test_to_raw_post_skips_without_id() -> None:
    e = _entry()
    e["post"].pop("id")
    assert lemmy._to_raw_post(e, "x", "y", "engineer") is None


def test_to_raw_post_skips_empty_text() -> None:
    e = _entry(post={"name": "", "body": ""})
    assert lemmy._to_raw_post(e, "x", "y", "engineer") is None


def test_to_raw_post_skips_bad_date() -> None:
    e = _entry(post={"published": "not-a-date"})
    assert lemmy._to_raw_post(e, "x", "y", "engineer") is None


def test_to_raw_post_skips_missing_date() -> None:
    e = _entry()
    e["post"].pop("published")
    assert lemmy._to_raw_post(e, "x", "y", "engineer") is None


def test_to_raw_post_handles_missing_creator_and_counts() -> None:
    e = _entry()
    e.pop("creator")
    e.pop("counts")
    p = lemmy._to_raw_post(e, "x", "y", "engineer")
    assert p is not None
    assert p.author_handle is None
    assert p.score == 0
    assert p.replies_count == 0


# ---------- _fetch_community ----------


def test_fetch_community_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = _list_resp(
        [_entry(post={"id": i, "published": "2026-05-10T00:00:00.000Z"}) for i in range(50)]
    )
    page2 = _list_resp(
        [_entry(post={"id": 100, "published": "2026-05-09T00:00:00.000Z"})]
    )
    pages = [page1, page2]
    monkeypatch.setattr(lemmy, "get_json", lambda url, params=None: pages.pop(0))

    cutoff = datetime(2020, 1, 1, tzinfo=UTC)
    out = list(lemmy._fetch_community("programming.dev", "programming", "engineer", cutoff))
    assert len(out) == 51
    assert pages == []  # both pages consumed


def test_fetch_community_stops_when_old_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    # 50 items: first is new, second is old, rest don't matter (we stop after this page).
    page = _list_resp(
        [_entry(post={"id": 1, "published": "2026-05-10T00:00:00.000Z"})]
        + [_entry(post={"id": 2, "published": "2020-01-01T00:00:00.000Z"})]
        + [_entry(post={"id": i + 3, "published": "2026-05-10T00:00:00.000Z"}) for i in range(48)]
    )
    pages = [page]
    monkeypatch.setattr(lemmy, "get_json", lambda url, params=None: pages.pop(0))
    cutoff = datetime(2024, 1, 1, tzinfo=UTC)
    out = list(lemmy._fetch_community("programming.dev", "programming", "engineer", cutoff))
    # The old item should be dropped; all newer items on the same page yielded;
    # then pagination halts.
    assert all(p.id != "lemmy:programming.dev:2" for p in out)
    assert pages == []  # didn't fetch a second page


def test_fetch_community_handles_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: Any = None) -> Any:
        raise RuntimeError("instance down")

    monkeypatch.setattr(lemmy, "get_json", boom)
    out = list(
        lemmy._fetch_community(
            "programming.dev", "programming", "engineer", datetime(2024, 1, 1, tzinfo=UTC)
        )
    )
    assert out == []


def test_fetch_community_empty_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lemmy, "get_json", lambda url, params=None: {"posts": []})
    out = list(
        lemmy._fetch_community(
            "programming.dev", "programming", "engineer", datetime(2024, 1, 1, tzinfo=UTC)
        )
    )
    assert out == []


def test_fetch_community_passes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_get(url: str, params: Any = None) -> dict[str, Any]:
        captured.append({"url": url, "params": params or {}})
        return {"posts": []}

    monkeypatch.setattr(lemmy, "get_json", fake_get)
    list(
        lemmy._fetch_community(
            "programming.dev", "programming", "engineer", datetime(2024, 1, 1, tzinfo=UTC)
        )
    )
    assert captured
    call = captured[0]
    assert call["url"] == "https://programming.dev/api/v3/post/list"
    assert call["params"]["community_name"] == "programming"
    assert call["params"]["sort"] == "New"
    assert call["params"]["limit"] == 50
    assert call["params"]["page"] == 1
