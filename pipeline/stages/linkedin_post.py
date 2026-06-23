"""LinkedIn post generation stage — env-gated.

Generates a ~1,200-character LinkedIn post from the week's narrative and
top clusters. Uses Claude Haiku 4.5 when ANTHROPIC_API_KEY is set (same
key as the synthesis stage); falls back to a heuristic template otherwise.

Output: plain-text string ready to post, or None on hard failure.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pipeline.config import HAIKU_INPUT_PRICE_PER_M, HAIKU_MODEL, HAIKU_OUTPUT_PRICE_PER_M
from pipeline.models import ScoredCluster

log = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "linkedin_post.md"
_MAX_POST_CHARS = 1300
_BUDGET_USD = 0.10


def generate(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    *,
    dashboard_url: str = "",
    api_key: str | None = None,
    client: Any = None,
) -> str | None:
    """Generate a LinkedIn post from this week's intelligence.

    Returns post text (≤1,300 chars) or None if no data is available.
    Falls back to a heuristic template when the Anthropic API is not configured.
    """
    if not scored:
        log.warning("linkedin_post: no scored clusters — skipping")
        return None

    if client is None:
        if api_key is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            log.info("linkedin_post: no ANTHROPIC_API_KEY → heuristic mode")
            return _heuristic_post(scored, narrative, dashboard_url)

        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic(api_key=api_key)

    return _llm_post(client, scored, narrative, dashboard_url)


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def _llm_post(
    client: Any,
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    dashboard_url: str,
) -> str | None:
    system = _PROMPT_PATH.read_text(encoding="utf-8")
    # Inject the URL directly into the system prompt so the model cannot miss it.
    # Passing it only as JSON data is unreliable — the model treats {dashboard_url}
    # in the prompt as a literal placeholder rather than reading from the payload.
    if dashboard_url:
        system += f"\n\nDashboard URL for this week's post: {dashboard_url}\nYou MUST include this URL in the link line (step 11 of the structure)."
    payload = _build_payload(scored, narrative, dashboard_url)

    try:
        resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=600,
            system=system,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
    except Exception:
        log.exception("linkedin_post: Haiku call failed — falling back to heuristic")
        return _heuristic_post(scored, narrative, dashboard_url)

    text = _first_text(resp)
    if not text:
        log.warning("linkedin_post: empty Haiku response — falling back to heuristic")
        return _heuristic_post(scored, narrative, dashboard_url)

    text = text.strip()
    text = _inject_url(text, dashboard_url)
    if len(text) > _MAX_POST_CHARS:
        log.warning(
            "linkedin_post: LLM output %d chars > limit %d — truncating at last newline",
            len(text),
            _MAX_POST_CHARS,
        )
        text = text[: _MAX_POST_CHARS].rsplit("\n", 1)[0].strip()

    cost = _estimate_cost(resp.usage)
    log.info("linkedin_post: generated %d-char post (cost ~$%.4f)", len(text), cost)
    return text


def _build_payload(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    dashboard_url: str,
) -> dict[str, Any]:
    top = sorted(scored, key=lambda s: -s.opportunity)[:5]

    top_items = []
    if narrative and narrative.get("top_10"):
        for item in narrative["top_10"][:3]:
            top_items.append(
                {
                    "rank": item.get("rank"),
                    "title": item.get("title"),
                    "pain": item.get("pain"),
                    "pitch": item.get("pitch"),
                    "why_now": item.get("why_now"),
                    "target_role": item.get("target_role"),
                }
            )
    else:
        for i, sc in enumerate(top[:3], 1):
            title = sc.synthesis.title if sc.synthesis else sc.cluster.label
            pain = sc.synthesis.one_line_pain if sc.synthesis else sc.cost.summary
            pitch = sc.synthesis.opportunity_pitch if sc.synthesis else ""
            top_items.append(
                {
                    "rank": i,
                    "title": title,
                    "pain": pain,
                    "pitch": pitch,
                    "why_now": "",
                    "target_role": sc.role_top[0][0] if sc.role_top else "engineer",
                }
            )

    return {
        "week_headline": (
            narrative["headline"] if narrative and narrative.get("headline") else None
        ),
        "total_clusters": len(scored),
        "top_3_opportunities": top_items,
        "honorable_mentions": (
            narrative.get("honorable_mentions", [])[:3]
            if narrative
            else []
        ),
        "dashboard_url": dashboard_url,
    }


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


def _heuristic_post(
    scored: list[ScoredCluster],
    narrative: dict[str, Any] | None,
    dashboard_url: str,
) -> str:
    top = sorted(scored, key=lambda s: -s.opportunity)[:3]

    headline = (
        narrative["headline"]
        if narrative and narrative.get("headline")
        else f"Software teams are hitting walls — {len(scored)} distinct pain clusters active this week."
    )

    lines = [headline, ""]

    top_items_from_narrative = (
        narrative["top_10"][:3] if narrative and narrative.get("top_10") else []
    )

    lines.append(
        f"This week's scan across dev communities surfaced {len(scored)} active pain clusters — "
        "here are the top 3 worth watching:"
    )
    lines.append("")

    for i, sc in enumerate(top, 1):
        if top_items_from_narrative and i <= len(top_items_from_narrative):
            item = top_items_from_narrative[i - 1]
            title = item.get("title", sc.cluster.label)
            pain = item.get("pain", sc.cost.summary)
            pitch = item.get("pitch", "")
        else:
            title = sc.synthesis.title if sc.synthesis else sc.cluster.label
            pain = sc.synthesis.one_line_pain if sc.synthesis else sc.cost.summary
            pitch = sc.synthesis.opportunity_pitch if sc.synthesis else ""

        entry = f"{i}. {title} — {pain}"
        if pitch:
            entry += f" Builder angle: {pitch}"
        lines.append(entry)

    lines.append("")
    lines.append("Which of these is your team actively dealing with right now?")

    if dashboard_url:
        lines.append("")
        lines.append(f"Full intelligence briefing → {dashboard_url}")

    lines.append("")
    lines.append("#buildinpublic #softwareengineering #devtools #indiehackers #techleadership")

    post = "\n".join(lines)
    if len(post) > _MAX_POST_CHARS:
        post = post[: _MAX_POST_CHARS].rsplit("\n", 1)[0].strip()
    return post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _inject_url(text: str, dashboard_url: str) -> str:
    """Guarantee the dashboard URL appears in the post text.

    If the URL is already present (LLM included it), return unchanged.
    Otherwise insert it before the hashtag line so it's always visible.
    """
    if not dashboard_url or dashboard_url in text:
        return text

    link_line = f"Full breakdown → {dashboard_url}"
    lines = text.split("\n")

    # Find the last hashtag line and insert the URL + blank line before it.
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("#"):
            lines.insert(i, "")
            lines.insert(i, link_line)
            log.info("linkedin_post: injected dashboard URL before hashtags")
            return "\n".join(lines)

    # No hashtag line found — append at the end.
    lines += ["", link_line]
    log.info("linkedin_post: appended dashboard URL to post")
    return "\n".join(lines)


def _first_text(resp: Any) -> str | None:
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return getattr(block, "text", None)
    return None


def _estimate_cost(usage: Any) -> float:
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return (input_tokens * HAIKU_INPUT_PRICE_PER_M + output_tokens * HAIKU_OUTPUT_PRICE_PER_M) / 1_000_000
