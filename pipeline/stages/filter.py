"""Filter stage — two-pass relevance filter.

1. `cheap_pass` (keyword allow/block, pure function): drops obvious spam and
   keeps anything mentioning a software-industry role or pain keyword.
2. `SemanticFilter` (cosine similarity to curated anchor sentences): drops
   posts that pass the keyword pass but aren't actually about a pain point.

The embedder is injected as a callable so this module imports without
sentence-transformers; the real embedder lives in `pipeline/stages/embed.py`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Iterator
from typing import Final

import numpy as np

from pipeline.config import (
    ANCHOR_PAIN_SENTENCES,
    KEYWORD_ALLOW,
    KEYWORD_BLOCK,
    SEMANTIC_FILTER_THRESHOLD,
)
from pipeline.models import NormalizedPost

log = logging.getLogger(__name__)

EmbedFn = Callable[[list[str]], np.ndarray]

# `\w{0,4}` trailing absorbs common inflections (engineer/engineers/engineering,
# stakeholder/stakeholders, deploy/deploys/deployment-up-to-4-chars). It will
# miss heavy stem-changing forms like "estimating" (drops the 'e'); add those
# explicitly to KEYWORD_ALLOW in config.py when they come up.
_INFLECTION_SUFFIX: Final[str] = r"\w{0,4}\b"

_ALLOW_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in KEYWORD_ALLOW) + r")" + _INFLECTION_SUFFIX,
    re.IGNORECASE,
)
_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in KEYWORD_BLOCK) + r")" + _INFLECTION_SUFFIX,
    re.IGNORECASE,
)

_SEMANTIC_BATCH: Final[int] = 64


def cheap_pass(text: str) -> bool:
    """True if `text` mentions an allow term and no block term."""
    if _BLOCK_RE.search(text):
        return False
    return bool(_ALLOW_RE.search(text))


class SemanticFilter:
    """Cosine-similarity gate against curated pain-point anchors.

    The anchors are embedded once at construction time. `keep_many` batches the
    candidate posts through `embed_fn` and returns a boolean per post.
    """

    def __init__(
        self,
        embed_fn: EmbedFn,
        anchors: tuple[str, ...] = ANCHOR_PAIN_SENTENCES,
        threshold: float = SEMANTIC_FILTER_THRESHOLD,
    ) -> None:
        if not anchors:
            raise ValueError("SemanticFilter requires at least one anchor sentence")
        self.threshold = threshold
        self._embed_fn = embed_fn
        self._anchor_emb = _l2_normalize(embed_fn(list(anchors)))

    def keep_many(self, texts: list[str]) -> list[bool]:
        if not texts:
            return []
        vecs = _l2_normalize(self._embed_fn(texts))
        # Both sides L2-normalized → dot product == cosine similarity.
        sims = vecs @ self._anchor_emb.T
        max_sims = sims.max(axis=1)
        return [bool(v) for v in (max_sims >= self.threshold).tolist()]


def filter_posts(
    posts: Iterable[NormalizedPost],
    semantic_filter: SemanticFilter | None = None,
) -> Iterator[NormalizedPost]:
    """Apply the cheap pass, then the optional semantic pass."""
    cheap_kept: list[NormalizedPost] = [p for p in posts if cheap_pass(p.text)]
    log.info("filter.cheap: %d posts kept", len(cheap_kept))

    if semantic_filter is None:
        yield from cheap_kept
        return

    semantic_kept = 0
    for start in range(0, len(cheap_kept), _SEMANTIC_BATCH):
        batch = cheap_kept[start : start + _SEMANTIC_BATCH]
        decisions = semantic_filter.keep_many([p.text for p in batch])
        for post, keep in zip(batch, decisions, strict=True):
            if keep:
                semantic_kept += 1
                yield post
    log.info("filter.semantic: %d posts kept", semantic_kept)


def _l2_normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return arr / norms
