"""Normalize stage — RawPost → NormalizedPost.

Strips markup, refines the role hint from the post text, extracts cost
mentions via the regexes in config, and computes VADER compound sentiment.
VADER is imported lazily so the rest of the module is testable without
the dependency installed.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any, Final

from pipeline.config import MONEY_REGEX, TEAM_REGEX, TIME_REGEX
from pipeline.models import CostMention, NormalizedPost, RawPost

log = logging.getLogger(__name__)

_HTML_TAG_RE: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
_WS_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_MAX_TEXT_LEN: Final[int] = 4000

# Post-text role detectors. Order matters — more-specific roles before generic.
_ROLE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("product_manager", re.compile(r"\bI'?m (?:a |an )?(?:product manager|PM)\b", re.IGNORECASE)),
    ("project_manager", re.compile(r"\bI'?m (?:a |an )?(?:project|program) manager\b", re.IGNORECASE)),
    ("sre", re.compile(r"\bI'?m (?:a |an )?SRE\b", re.IGNORECASE)),
    ("devops", re.compile(r"\bI'?m (?:a |an )?(?:devops|sysadmin|platform engineer)\b", re.IGNORECASE)),
    ("qa", re.compile(r"\bI'?m (?:a |an )?(?:QA|tester|quality engineer)\b", re.IGNORECASE)),
    ("manager", re.compile(r"\bI'?m (?:a |an )?(?:engineering )?manager\b", re.IGNORECASE)),
    ("founder", re.compile(r"\bI'?m (?:a |an )?(?:founder|CEO|CTO)\b", re.IGNORECASE)),
    ("data", re.compile(r"\bI'?m (?:a |an )?(?:data scientist|data engineer|ML engineer)\b", re.IGNORECASE)),
    ("security", re.compile(r"\bI'?m (?:a |an )?(?:security engineer|pentester)\b", re.IGNORECASE)),
    ("designer", re.compile(r"\bI'?m (?:a |an )?designer\b", re.IGNORECASE)),
    ("engineer", re.compile(r"\bI'?m (?:a |an )?(?:software )?(?:engineer|developer)\b", re.IGNORECASE)),
)

_SIA: Any = None


def normalize(raw: RawPost) -> NormalizedPost:
    text = clean_text(raw.text)
    return NormalizedPost(
        id=raw.id,
        source=raw.source,
        author_handle=raw.author_handle,
        role=infer_role(raw, text),
        posted_at=raw.posted_at,
        url=raw.url,
        text=text,
        score=raw.score,
        replies_count=raw.replies_count,
        sentiment=_sentiment(text),
        cost_mentions=extract_cost_mentions(text),
    )


def clean_text(text: str) -> str:
    """Strip tags, decode entities, collapse whitespace, truncate."""
    text = _HTML_TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN].rstrip() + " …"
    return text


def infer_role(raw: RawPost, cleaned_text: str) -> str | None:
    """Refine the role from explicit text mentions; fall back to the ingestion hint."""
    for role, pattern in _ROLE_PATTERNS:
        if pattern.search(cleaned_text):
            return role
    return raw.author_role_hint


def extract_cost_mentions(text: str) -> list[CostMention]:
    out: list[CostMention] = []

    for m in MONEY_REGEX.finditer(text):
        value = float(m.group("value"))
        unit = m.group("unit")
        if unit:
            ul = unit.lower()
            if ul in ("k", "thousand"):
                value *= 1_000
                unit = None
            elif ul in ("m", "million"):
                value *= 1_000_000
                unit = None
        out.append(CostMention(kind="money", raw=m.group(0), value=value, unit=unit))

    for m in TIME_REGEX.finditer(text):
        out.append(
            CostMention(
                kind="time",
                raw=m.group(0),
                value=float(m.group("value")),
                unit=m.group("unit").lower(),
            )
        )

    for m in TEAM_REGEX.finditer(text):
        raw_val = m.group("value") or m.group("value2")
        if raw_val is None:
            continue
        out.append(
            CostMention(kind="team", raw=m.group(0), value=float(raw_val), unit="people")
        )

    return out


def _sentiment(text: str) -> float:
    return float(_vader().polarity_scores(text)["compound"])


def _vader() -> Any:
    """Lazy-load VADER so the module imports without the dep installed."""
    global _SIA
    if _SIA is None:
        from vaderSentiment.vaderSentiment import (  # noqa: PLC0415
            SentimentIntensityAnalyzer,
        )

        _SIA = SentimentIntensityAnalyzer()
    return _SIA
