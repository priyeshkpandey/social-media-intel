"""Claude synthesis stage — env-gated.

Two passes:

1. **Per-cluster (Haiku 4.5):** for the top-N clusters by heuristic
   `opportunity`, post a JSON payload of representative posts + scores and
   receive a refined `ClusterSynthesis` back. System prompt is reused with
   `cache_control={"type": "ephemeral"}` so 25 calls share one prefix.

2. **Weekly synthesis (Sonnet 4.6):** one call against all 25 Haiku outputs
   produces the "Top 10 Opportunities This Week" narrative the dashboard
   hero renders.

Both passes use Anthropic structured outputs (`output_config.format` with a
JSON schema) so the response is guaranteed-parseable JSON — no markdown-
fence stripping required. Sonnet 4.6 additionally uses adaptive thinking
+ `effort: "high"`; Haiku 4.5 does not support `effort`.

The stage is no-op when `ANTHROPIC_API_KEY` is absent — the dashboard falls
back to heuristic-only output. A `$1.00/run` budget cap protects against
runaway costs; per-call pricing comes from `pipeline.config`.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from pipeline.config import (
    HAIKU_CACHE_READ_PRICE_PER_M,
    HAIKU_CACHE_WRITE_PRICE_PER_M,
    HAIKU_INPUT_PRICE_PER_M,
    HAIKU_MODEL,
    HAIKU_OUTPUT_PRICE_PER_M,
    SONNET_INPUT_PRICE_PER_M,
    SONNET_MODEL,
    SONNET_OUTPUT_PRICE_PER_M,
    SYNTHESIS_BUDGET_USD,
    TOP_N_FOR_SYNTHESIS,
)
from pipeline.models import ClusterSynthesis, ScoredCluster

log = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
HAIKU_PROMPT_PATH = _PROMPTS_DIR / "cluster_tag.haiku.md"
SONNET_PROMPT_PATH = _PROMPTS_DIR / "weekly_synthesis.sonnet.md"

_MAX_POSTS_PER_CLUSTER = 10
_MAX_POST_TEXT = 800

_FEASIBILITY_VALUES = ["low", "medium", "high"]
_IMPL_BAND_VALUES = ["<$10k", "$10-100k", "$100k-1M", ">$1M"]

_CLUSTER_TAG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "one_line_pain": {"type": "string"},
        "role_demographics": {"type": "string"},
        "perceived_cost_summary": {"type": "string"},
        "feasibility": {"type": "string", "enum": _FEASIBILITY_VALUES},
        "implementation_cost_band": {"type": "string", "enum": _IMPL_BAND_VALUES},
        "opportunity_pitch": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": [
        "title",
        "one_line_pain",
        "role_demographics",
        "perceived_cost_summary",
        "feasibility",
        "implementation_cost_band",
        "opportunity_pitch",
        "confidence",
    ],
    "additionalProperties": False,
}

_WEEKLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "top_10": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rank": {"type": "integer"},
                    "title": {"type": "string"},
                    "pain": {"type": "string"},
                    "pitch": {"type": "string"},
                    "why_now": {"type": "string"},
                    "target_role": {"type": "string"},
                    "evidence_cluster_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "estimated_band": {"type": "string", "enum": _IMPL_BAND_VALUES},
                },
                "required": [
                    "rank",
                    "title",
                    "pain",
                    "pitch",
                    "why_now",
                    "target_role",
                    "evidence_cluster_ids",
                    "estimated_band",
                ],
                "additionalProperties": False,
            },
        },
        "honorable_mentions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "top_10", "honorable_mentions"],
    "additionalProperties": False,
}


def synthesize(
    scored_clusters: list[ScoredCluster],
    *,
    api_key: str | None = None,
    top_n: int = TOP_N_FOR_SYNTHESIS,
    budget_usd: float = SYNTHESIS_BUDGET_USD,
    client: Any = None,
) -> tuple[list[ScoredCluster], dict[str, Any] | None]:
    """Refine top-N clusters via Claude and produce the weekly narrative.

    Returns (clusters_with_synthesis, weekly_narrative). When
    ANTHROPIC_API_KEY is absent and no `client` is injected, returns the
    input unchanged and a `None` narrative — the dashboard handles the
    heuristic-only banner.
    """
    if client is None:
        if api_key is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.info("synthesize: no ANTHROPIC_API_KEY → heuristic-only mode")
            return scored_clusters, None
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=api_key)

    ranked = sorted(scored_clusters, key=lambda s: -s.opportunity)
    top = ranked[:top_n]
    rest = ranked[top_n:]
    if not top:
        return scored_clusters, None

    haiku_system = HAIKU_PROMPT_PATH.read_text(encoding="utf-8")
    spent_usd = 0.0
    refined_top: list[ScoredCluster] = []
    for sc in top:
        if spent_usd >= budget_usd:
            log.warning(
                "synthesize: budget exhausted ($%.4f / $%.2f); %d clusters skipped",
                spent_usd,
                budget_usd,
                len(top) - len(refined_top),
            )
            refined_top.append(sc)
            continue
        synth, cost = _refine_cluster(client, haiku_system, sc)
        spent_usd += cost
        refined_top.append(replace(sc, synthesis=synth) if synth is not None else sc)

    narrative: dict[str, Any] | None = None
    has_any_synthesis = any(s.synthesis is not None for s in refined_top)
    if has_any_synthesis and spent_usd < budget_usd:
        sonnet_system = SONNET_PROMPT_PATH.read_text(encoding="utf-8")
        narrative, sonnet_cost = _weekly_narrative(client, sonnet_system, refined_top)
        spent_usd += sonnet_cost

    log.info("synthesize: spent $%.4f of $%.2f budget", spent_usd, budget_usd)
    return refined_top + rest, narrative


# ---------------------------------------------------------------------------
# Per-cluster Haiku call
# ---------------------------------------------------------------------------


def _refine_cluster(
    client: Any,
    system_prompt: str,
    sc: ScoredCluster,
) -> tuple[ClusterSynthesis | None, float]:
    payload = _cluster_payload(sc)
    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": json.dumps(payload)}],
            output_config={
                "format": {"type": "json_schema", "schema": _CLUSTER_TAG_SCHEMA}
            },
        )
    except Exception:
        log.exception("synthesize: Haiku call failed for %s", sc.cluster.id)
        return None, 0.0

    cost = _haiku_cost(resp.usage)
    text = _first_text(resp)
    if not text:
        return None, cost
    try:
        data = json.loads(text)
        synth = ClusterSynthesis(
            title=str(data["title"]),
            one_line_pain=str(data["one_line_pain"]),
            role_demographics=str(data["role_demographics"]),
            perceived_cost_summary=str(data["perceived_cost_summary"]),
            feasibility=data["feasibility"],
            implementation_cost_band=data["implementation_cost_band"],
            opportunity_pitch=str(data["opportunity_pitch"]),
            confidence=float(data["confidence"]),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.exception("synthesize: malformed Haiku output for %s", sc.cluster.id)
        return None, cost
    return synth, cost


def _cluster_payload(sc: ScoredCluster) -> dict[str, Any]:
    posts = sc.cluster.posts[:_MAX_POSTS_PER_CLUSTER]
    return {
        "cluster_id": sc.cluster.id,
        "heuristic_label": sc.cluster.label,
        "heuristic_scores": {
            "frequency_per_week": round(sc.frequency_per_week, 2),
            "opportunity": round(sc.opportunity, 1),
            "feasibility": sc.feasibility,
            "impl_cost_band": sc.impl_cost_band,
            "cost_summary": sc.cost.summary,
            "top_roles": [
                {"role": role, "share": round(share, 2)}
                for role, share in sc.role_top
            ],
        },
        "representative_posts": [
            {
                "text": p.text[:_MAX_POST_TEXT],
                "role": p.role,
                "source": p.source,
                "url": p.url,
            }
            for p in posts
        ],
    }


# ---------------------------------------------------------------------------
# Weekly Sonnet narrative
# ---------------------------------------------------------------------------


def _weekly_narrative(
    client: Any,
    system_prompt: str,
    refined: list[ScoredCluster],
) -> tuple[dict[str, Any] | None, float]:
    payload = {
        "clusters": [
            {
                "cluster_id": sc.cluster.id,
                "label": sc.cluster.label,
                "scores": {
                    "frequency_per_week": round(sc.frequency_per_week, 2),
                    "opportunity": round(sc.opportunity, 1),
                    "feasibility": sc.feasibility,
                    "impl_cost_band": sc.impl_cost_band,
                },
                "synthesis": _serialize_synthesis(sc),
            }
            for sc in refined
        ],
    }
    try:
        resp = client.messages.create(
            model=SONNET_MODEL,
            # 16K leaves plenty of headroom for adaptive thinking + the JSON
            # output. 4K was too tight: a previous run had a 95-second Sonnet
            # call return a 200 with no text block (thinking ate the budget).
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": json.dumps(payload)}],
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": _WEEKLY_SCHEMA},
            },
        )
    except Exception:
        log.exception("synthesize: Sonnet weekly narrative call failed")
        return None, 0.0

    cost = _sonnet_cost(resp.usage)
    text = _first_text(resp)
    if not text:
        block_types = [getattr(b, "type", "?") for b in getattr(resp, "content", [])]
        log.warning(
            "synthesize: Sonnet returned no text block. "
            "stop_reason=%s, block_types=%s, output_tokens=%s",
            getattr(resp, "stop_reason", None),
            block_types,
            getattr(resp.usage, "output_tokens", None),
        )
        return None, cost
    try:
        return json.loads(text), cost
    except json.JSONDecodeError:
        log.exception(
            "synthesize: malformed Sonnet narrative (first 200 chars: %r)",
            text[:200],
        )
        return None, cost


def _serialize_synthesis(sc: ScoredCluster) -> dict[str, Any] | None:
    if sc.synthesis is None:
        return None
    return {
        "title": sc.synthesis.title,
        "one_line_pain": sc.synthesis.one_line_pain,
        "opportunity_pitch": sc.synthesis.opportunity_pitch,
        "role_demographics": sc.synthesis.role_demographics,
        "perceived_cost_summary": sc.synthesis.perceived_cost_summary,
        "feasibility": sc.synthesis.feasibility,
        "implementation_cost_band": sc.synthesis.implementation_cost_band,
        "confidence": round(sc.synthesis.confidence, 2),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_text(resp: Any) -> str | None:
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", None)
    return None


def _haiku_cost(usage: Any) -> float:
    return _cost(
        usage,
        HAIKU_INPUT_PRICE_PER_M,
        HAIKU_OUTPUT_PRICE_PER_M,
        HAIKU_CACHE_WRITE_PRICE_PER_M,
        HAIKU_CACHE_READ_PRICE_PER_M,
    )


def _sonnet_cost(usage: Any) -> float:
    return _cost(usage, SONNET_INPUT_PRICE_PER_M, SONNET_OUTPUT_PRICE_PER_M)


def _cost(
    usage: Any,
    input_per_m: float,
    output_per_m: float,
    cache_write_per_m: float = 0.0,
    cache_read_per_m: float = 0.0,
) -> float:
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return (
        input_tokens * input_per_m
        + output_tokens * output_per_m
        + cache_write * cache_write_per_m
        + cache_read * cache_read_per_m
    ) / 1_000_000
