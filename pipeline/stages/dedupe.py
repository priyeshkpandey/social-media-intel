"""Dedupe stage — drops duplicates by stable ID and near-duplicates by text hash.

Same-source duplicates (e.g., Reddit reposts after a crash) are caught by ID.
Cross-source duplicates (same article submitted to both HN and Lobsters) are
caught by a SHA-256 of the canonicalized first 500 characters.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Iterator
from typing import Final

from pipeline.models import NormalizedPost

log = logging.getLogger(__name__)

_WS: Final[re.Pattern[str]] = re.compile(r"\s+")
_CANONICAL_PREFIX_LEN: Final[int] = 500


def dedupe(posts: Iterable[NormalizedPost]) -> Iterator[NormalizedPost]:
    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    dropped = 0
    for post in posts:
        if post.id in seen_ids:
            dropped += 1
            continue
        h = text_fingerprint(post.text)
        if h in seen_hashes:
            dropped += 1
            continue
        seen_ids.add(post.id)
        seen_hashes.add(h)
        yield post
    log.info("dedupe: dropped %d duplicates", dropped)


def text_fingerprint(text: str) -> str:
    canonical = _WS.sub(" ", text).strip().lower()[:_CANONICAL_PREFIX_LEN]
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
