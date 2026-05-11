"""Unit tests for pipeline.stages.normalize.

Pure helpers (clean_text, infer_role, extract_cost_mentions) are tested
directly without VADER. The end-to-end `normalize()` is tested with VADER
monkeypatched out so the test suite doesn't pull the lexicon at collection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.models import RawPost
from pipeline.stages import normalize as norm


def _raw(text: str = "hello", role_hint: str | None = "engineer") -> RawPost:
    return RawPost(
        id="x:1",
        source="reddit",
        author_handle="a",
        author_role_hint=role_hint,
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        url="https://example.com",
        text=text,
        score=0,
        replies_count=0,
    )


# ---------- clean_text ----------


def test_clean_text_strips_html_and_entities() -> None:
    out = norm.clean_text("<p>Hello&nbsp;<b>world</b> &amp; co.</p>")
    assert "<" not in out and ">" not in out
    assert "Hello" in out and "world" in out and "&" in out


def test_clean_text_collapses_whitespace() -> None:
    assert norm.clean_text("a\n\n\t  b\r\n c") == "a b c"


def test_clean_text_truncates_overlong() -> None:
    long = "x" * (norm._MAX_TEXT_LEN + 500)
    out = norm.clean_text(long)
    assert len(out) <= norm._MAX_TEXT_LEN + 5
    assert out.endswith("…")


# ---------- infer_role ----------


def test_infer_role_explicit_pm_overrides_hint() -> None:
    raw = _raw("I'm a product manager and our roadmap is chaos.", role_hint="engineer")
    assert norm.infer_role(raw, raw.text) == "product_manager"


def test_infer_role_falls_back_to_hint() -> None:
    raw = _raw("Generic complaining about CI.", role_hint="devops")
    assert norm.infer_role(raw, raw.text) == "devops"


def test_infer_role_returns_none_when_no_signal() -> None:
    raw = _raw("Nothing role-related here.", role_hint=None)
    assert norm.infer_role(raw, raw.text) is None


def test_infer_role_sre_specific() -> None:
    raw = _raw("I'm an SRE and on-call is brutal.", role_hint=None)
    assert norm.infer_role(raw, raw.text) == "sre"


# ---------- extract_cost_mentions ----------


def test_money_simple() -> None:
    m = norm.extract_cost_mentions("It cost us $1500 last quarter.")
    assert any(c.kind == "money" and c.value == 1500.0 and c.unit is None for c in m)


def test_money_k_multiplier() -> None:
    m = norm.extract_cost_mentions("We're paying $50k/year for this thing.")
    monies = [c for c in m if c.kind == "money"]
    assert monies and monies[0].value == 50_000.0


def test_money_million() -> None:
    m = norm.extract_cost_mentions("Cloud bill is $2 million per year.")
    monies = [c for c in m if c.kind == "money"]
    assert monies and monies[0].value == 2_000_000.0


def test_time_mention() -> None:
    m = norm.extract_cost_mentions("This eats 3 days of engineering time.")
    times = [c for c in m if c.kind == "time"]
    assert times and times[0].value == 3.0 and times[0].unit == "days"


def test_team_mention_first_form() -> None:
    m = norm.extract_cost_mentions("A team of 5 maintains this.")
    teams = [c for c in m if c.kind == "team"]
    assert teams and teams[0].value == 5.0


def test_team_mention_second_form() -> None:
    m = norm.extract_cost_mentions("It takes 10 engineers to keep it running.")
    teams = [c for c in m if c.kind == "team"]
    assert teams and teams[0].value == 10.0


def test_no_cost_mentions() -> None:
    assert norm.extract_cost_mentions("Just a generic complaint.") == []


# ---------- normalize end-to-end ----------


class _FakeVader:
    def polarity_scores(self, text: str) -> dict[str, float]:
        return {"compound": -0.5 if "burnout" in text.lower() else 0.0}


def test_normalize_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(norm, "_vader", lambda: _FakeVader())
    raw = RawPost(
        id="reddit:abc",
        source="reddit",
        author_handle="alice",
        author_role_hint="engineer",
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        url="https://example.com",
        text="<p>I'm a product manager. Burnout is real. Cost us $20k/month.</p>",
        score=10,
        replies_count=2,
    )
    out = norm.normalize(raw)
    assert out.id == "reddit:abc"
    assert out.role == "product_manager"  # text wins over hint
    assert out.sentiment == -0.5
    assert any(c.kind == "money" and c.value == 20_000.0 for c in out.cost_mentions)
    assert "<p>" not in out.text


def test_vader_lazy_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """_vader() caches the analyzer across calls."""
    calls: list[int] = []

    class _Mod:
        class SentimentIntensityAnalyzer:
            def __init__(self) -> None:
                calls.append(1)

            def polarity_scores(self, _: str) -> dict[str, float]:
                return {"compound": 0.0}

    import sys

    monkeypatch.setitem(sys.modules, "vaderSentiment.vaderSentiment", _Mod)
    monkeypatch.setattr(norm, "_SIA", None)

    a = norm._vader()
    b = norm._vader()
    assert a is b
    assert len(calls) == 1
