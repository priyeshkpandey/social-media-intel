"""Unit tests for pipeline.stages.synthesize.

We mock the Anthropic SDK with a stub client object, so no real API calls
fire and the heavy `anthropic` import is avoided in the test path.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import pytest

from pipeline.config import HAIKU_MODEL, SONNET_MODEL
from pipeline.models import (
    Cluster,
    ClusterSynthesis,
    CostSummary,
    NormalizedPost,
    ScoredCluster,
)
from pipeline.stages import synthesize as syn


# ---------- fixtures ----------


def _post(post_id: str, text: str) -> NormalizedPost:
    return NormalizedPost(
        id=post_id,
        source="reddit",
        author_handle=None,
        role="engineer",
        posted_at=datetime(2026, 5, 1, tzinfo=UTC),
        url=f"https://example.com/{post_id}",
        text=text,
        score=0,
        replies_count=0,
        sentiment=0.0,
    )


def _scored(cluster_id: str, opportunity: float, n_posts: int = 3) -> ScoredCluster:
    posts = [_post(f"{cluster_id}-p{i}", f"some text {i}") for i in range(n_posts)]
    cluster = Cluster(
        id=cluster_id,
        label="test label",
        centroid=[0.0],
        posts=posts,
        first_seen=datetime(2026, 5, 1, tzinfo=UTC),
        last_seen=datetime(2026, 5, 7, tzinfo=UTC),
    )
    return ScoredCluster(
        cluster=cluster,
        frequency_per_week=float(n_posts),
        frequency_zscore=0.0,
        cost=CostSummary(summary="no cost data"),
        role_top=[("engineer", 1.0)],
        opportunity=opportunity,
        feasibility="medium",
        impl_cost_band="$10-100k",
    )


# ---------- fake Anthropic client ----------


class _TextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Usage:
    def __init__(
        self,
        input_tokens: int = 500,
        output_tokens: int = 200,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _Response:
    def __init__(self, body: dict[str, Any], usage: _Usage | None = None) -> None:
        self.content = [_TextBlock(json.dumps(body))]
        self.usage = usage or _Usage()


class FakeClient:
    """Stand-in for `anthropic.Anthropic`. Tracks per-model calls and returns
    canned `_Response`s queued via `enqueue_haiku` / `enqueue_sonnet`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._haiku_queue: list[Any] = []
        self._sonnet_queue: list[Any] = []
        self.messages = self  # so synthesize calls `client.messages.create(...)`

    def enqueue_haiku(self, body: dict[str, Any] | Exception, usage: _Usage | None = None) -> None:
        self._haiku_queue.append((body, usage))

    def enqueue_sonnet(self, body: dict[str, Any] | Exception, usage: _Usage | None = None) -> None:
        self._sonnet_queue.append((body, usage))

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        model = kwargs["model"]
        queue = self._haiku_queue if model == HAIKU_MODEL else self._sonnet_queue
        if not queue:
            raise AssertionError(f"No queued response for model={model}")
        body, usage = queue.pop(0)
        if isinstance(body, Exception):
            raise body
        return _Response(body, usage)


def _valid_haiku_body(cluster_id: str = "c-1") -> dict[str, Any]:
    return {
        "title": f"Pain for {cluster_id}",
        "one_line_pain": "concise pain restatement",
        "role_demographics": "mostly engineers",
        "perceived_cost_summary": "a few engineer-days per week",
        "feasibility": "high",
        "implementation_cost_band": "<$10k",
        "opportunity_pitch": "a focused tool that does the thing",
        "confidence": 0.7,
    }


def _valid_sonnet_body() -> dict[str, Any]:
    return {
        "headline": "Test headline of the week",
        "top_10": [
            {
                "rank": 1,
                "title": "Top opportunity",
                "pain": "pain restatement",
                "pitch": "pitch text",
                "why_now": "why now",
                "target_role": "engineer",
                "evidence_cluster_ids": ["c-1"],
                "estimated_band": "<$10k",
            }
        ],
        "honorable_mentions": ["alt 1", "alt 2"],
    }


# ---------- API-key gating ----------


def test_synthesize_skips_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clusters = [_scored("c-1", 80.0)]
    out, narrative = syn.synthesize(clusters)
    assert out is clusters
    assert narrative is None


def test_synthesize_no_top_returns_input(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    out, narrative = syn.synthesize([], client=client, top_n=5)
    assert out == []
    assert narrative is None
    assert client.calls == []


# ---------- happy path ----------


def test_synthesize_refines_top_n_and_produces_narrative() -> None:
    client = FakeClient()
    for i in range(3):
        client.enqueue_haiku(_valid_haiku_body(f"c-{i}"))
    client.enqueue_sonnet(_valid_sonnet_body())

    clusters = [
        _scored("c-2", opportunity=50.0),
        _scored("c-0", opportunity=90.0),
        _scored("c-1", opportunity=70.0),
        _scored("c-3", opportunity=30.0),
    ]
    out, narrative = syn.synthesize(clusters, client=client, top_n=3)

    # Three Haiku + one Sonnet call.
    models_called = [c["model"] for c in client.calls]
    assert models_called.count(HAIKU_MODEL) == 3
    assert models_called.count(SONNET_MODEL) == 1

    # Sorted by opportunity descending — synthesis attached to top three only.
    assert [s.cluster.id for s in out] == ["c-0", "c-1", "c-2", "c-3"]
    assert out[0].synthesis is not None
    assert out[1].synthesis is not None
    assert out[2].synthesis is not None
    assert out[3].synthesis is None

    assert isinstance(out[0].synthesis, ClusterSynthesis)
    assert out[0].synthesis.feasibility == "high"
    assert out[0].synthesis.confidence == 0.7

    assert narrative is not None
    assert narrative["headline"]
    assert len(narrative["top_10"]) == 1


def test_synthesize_haiku_call_shape() -> None:
    """Verify the Haiku request structure — prompt caching, model, output_config."""
    client = FakeClient()
    client.enqueue_haiku(_valid_haiku_body())
    client.enqueue_sonnet(_valid_sonnet_body())

    syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)

    haiku_call = next(c for c in client.calls if c["model"] == HAIKU_MODEL)
    assert haiku_call["max_tokens"] == 1024

    # system is a list with cache_control on the text block.
    assert isinstance(haiku_call["system"], list)
    assert haiku_call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "senior product analyst" in haiku_call["system"][0]["text"].lower()

    # output_config carries the JSON schema; effort is NOT set (Haiku 4.5 doesn't support it).
    fmt = haiku_call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert "feasibility" in fmt["schema"]["properties"]
    assert "effort" not in haiku_call["output_config"]

    # user message is a JSON string carrying the cluster payload.
    msg = haiku_call["messages"][0]
    assert msg["role"] == "user"
    payload = json.loads(msg["content"])
    assert payload["cluster_id"] == "c-1"
    assert "representative_posts" in payload
    assert "heuristic_scores" in payload


def test_synthesize_sonnet_call_shape() -> None:
    """Verify the Sonnet request uses adaptive thinking + effort=high."""
    client = FakeClient()
    client.enqueue_haiku(_valid_haiku_body())
    client.enqueue_sonnet(_valid_sonnet_body())

    syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)

    sonnet_call = next(c for c in client.calls if c["model"] == SONNET_MODEL)
    assert sonnet_call["thinking"] == {"type": "adaptive"}
    assert sonnet_call["output_config"]["effort"] == "high"
    assert sonnet_call["output_config"]["format"]["type"] == "json_schema"


# ---------- error handling ----------


def test_synthesize_handles_malformed_haiku_json() -> None:
    """A bad JSON response leaves the cluster unrefined but doesn't crash."""
    client = FakeClient()
    # Send back valid JSON missing a required field.
    bad = _valid_haiku_body()
    del bad["feasibility"]
    client.enqueue_haiku(bad)
    client.enqueue_sonnet(_valid_sonnet_body())  # won't be reached if no synthesis

    out, narrative = syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)
    assert out[0].synthesis is None
    # No synthesis → no weekly narrative call.
    assert narrative is None


def test_synthesize_handles_haiku_api_error() -> None:
    client = FakeClient()
    client.enqueue_haiku(RuntimeError("simulated 500"))
    out, narrative = syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)
    assert out[0].synthesis is None
    assert narrative is None


def test_synthesize_skips_narrative_when_all_haikus_fail() -> None:
    client = FakeClient()
    client.enqueue_haiku(RuntimeError("boom"))
    client.enqueue_haiku(RuntimeError("boom"))
    out, narrative = syn.synthesize(
        [_scored("c-1", 80.0), _scored("c-2", 70.0)], client=client, top_n=2
    )
    assert all(s.synthesis is None for s in out)
    assert narrative is None
    # No Sonnet call was attempted.
    assert all(c["model"] == HAIKU_MODEL for c in client.calls)


# ---------- budget ----------


def test_synthesize_budget_cap_stops_haiku_calls() -> None:
    """Once spend ≥ budget, remaining clusters are passed through unrefined."""
    client = FakeClient()
    # Make each call $0.40 by inflating token counts.
    expensive_usage = _Usage(input_tokens=200_000, output_tokens=20_000)
    for _ in range(5):
        client.enqueue_haiku(_valid_haiku_body(), usage=expensive_usage)
    client.enqueue_sonnet(_valid_sonnet_body())

    clusters = [_scored(f"c-{i}", 90.0 - i) for i in range(5)]
    out, _ = syn.synthesize(clusters, client=client, top_n=5, budget_usd=0.50)

    # First call costs $0.30 → spent < $0.50 → call 2 fires.
    # After call 2: spent $0.60 ≥ $0.50 → calls 3,4,5 skipped.
    haiku_calls = [c for c in client.calls if c["model"] == HAIKU_MODEL]
    assert len(haiku_calls) == 2
    refined_count = sum(1 for s in out if s.synthesis is not None)
    assert refined_count == 2


# ---------- cost helper ----------


def test_haiku_cost_includes_cache_savings() -> None:
    """Cache reads cost ~0.1× input; cache writes ~1.25×."""
    u = _Usage(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1_000_000,
    )
    # 1M uncached @ $1 + 1M cached @ $0.10 = $1.10
    assert syn._haiku_cost(u) == pytest.approx(1.10)


def test_sonnet_cost_simple() -> None:
    u = _Usage(input_tokens=1_000_000, output_tokens=100_000)
    # $3 + 0.1 * $15 = $4.50
    assert syn._sonnet_cost(u) == pytest.approx(4.50)


def test_cost_handles_missing_attrs() -> None:
    class Empty: ...

    # No attributes at all → cost should be 0, not crash.
    assert syn._haiku_cost(Empty()) == 0.0
    assert syn._sonnet_cost(Empty()) == 0.0


def test_synthesize_uses_client_when_no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a client is injected, ANTHROPIC_API_KEY isn't required."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = FakeClient()
    client.enqueue_haiku(_valid_haiku_body())
    client.enqueue_sonnet(_valid_sonnet_body())

    out, narrative = syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)
    assert out[0].synthesis is not None
    assert narrative is not None


def test_synthesize_excludes_effort_for_haiku() -> None:
    """Regression guard: Haiku 4.5 doesn't support effort and would 400."""
    client = FakeClient()
    client.enqueue_haiku(_valid_haiku_body())
    client.enqueue_sonnet(_valid_sonnet_body())

    syn.synthesize([_scored("c-1", 80.0)], client=client, top_n=1)

    haiku_call = next(c for c in client.calls if c["model"] == HAIKU_MODEL)
    assert "effort" not in haiku_call.get("output_config", {})
