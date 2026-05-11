"""Unit tests for pipeline.sources.stackexchange."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.sources import stackexchange


def _item(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "question_id": 7777,
        "title": "How do you keep CI fast for a 100-engineer monorepo?",
        "body": "<p>Our pipeline takes 45 minutes. What strategies actually scale?</p>",
        "creation_date": 1747008000,
        "score": 12,
        "answer_count": 4,
        "view_count": 230,
        "tags": ["ci-cd", "monorepo"],
        "owner": {"display_name": "alex", "user_id": 42},
        "link": "https://stackoverflow.com/questions/7777/how-do-you",
    }
    base.update(overrides)
    return base


def test_to_raw_post_basic() -> None:
    p = stackexchange._to_raw_post(_item(), "ci-cd")
    assert isinstance(p, RawPost)
    assert p.id == "stackexchange:7777"
    assert p.source == "stackexchange"
    assert p.author_handle == "alex"
    assert "monorepo" in p.text
    assert "45 minutes" in p.text  # body retained (HTML still present; normalize cleans later)
    assert p.score == 12
    assert p.replies_count == 4
    assert p.raw["tags"] == ["ci-cd", "monorepo"]


def test_to_raw_post_skips_without_qid() -> None:
    item = _item()
    item.pop("question_id")
    assert stackexchange._to_raw_post(item, "x") is None


def test_to_raw_post_skips_empty_text() -> None:
    assert stackexchange._to_raw_post(_item(title="", body=""), "x") is None


def test_to_raw_post_handles_missing_owner() -> None:
    item = _item()
    item.pop("owner")
    p = stackexchange._to_raw_post(item, "x")
    assert p is not None
    assert p.author_handle is None


def test_fetch_tag_paginates_until_has_more_false(monkeypatch: pytest.MonkeyPatch) -> None:
    page1 = {"items": [_item(question_id=1)], "has_more": True}
    page2 = {"items": [_item(question_id=2)], "has_more": False}
    pages = [page1, page2]
    monkeypatch.setattr(stackexchange, "get_json", lambda url, params=None: pages.pop(0))
    out = list(stackexchange._fetch_tag("ci-cd", fromdate=0))
    assert [p.id for p in out] == ["stackexchange:1", "stackexchange:2"]
    assert pages == []


def test_fetch_tag_threads_fromdate_into_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    def fake_get(url: str, params: Any = None) -> dict[str, Any]:
        captured.append(params or {})
        return {"items": [], "has_more": False}

    monkeypatch.setattr(stackexchange, "get_json", fake_get)
    since_ts = int(datetime(2026, 5, 1, tzinfo=UTC).timestamp())
    list(stackexchange._fetch_tag("ci-cd", fromdate=since_ts))
    assert captured
    assert captured[0]["fromdate"] == since_ts
    assert captured[0]["sort"] == "creation"
    assert captured[0]["order"] == "desc"


def test_fetch_tag_handles_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(url: str, params: Any = None) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(stackexchange, "get_json", boom)
    out = list(stackexchange._fetch_tag("ci-cd", fromdate=0))
    assert out == []
