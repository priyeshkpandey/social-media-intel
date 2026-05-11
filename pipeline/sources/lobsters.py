"""Lobsters source — public RSS feed via feedparser.

The feed exposes ~25 most recent stories. Lower volume than Reddit/HN but the
signal-to-noise ratio is excellent (every story is vetted). We filter to items
posted on or after `since`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import feedparser  # type: ignore[import-untyped]

from pipeline.config import LOBSTERS_RSS
from pipeline.models import RawPost

log = logging.getLogger(__name__)


def fetch(since: datetime) -> Iterator[RawPost]:
    feed = feedparser.parse(LOBSTERS_RSS)
    if getattr(feed, "bozo", False):
        log.warning("lobsters: feed parse warning: %s", getattr(feed, "bozo_exception", "?"))
    count = 0
    for entry in feed.entries:
        post = _to_raw_post(entry)
        if post is None:
            continue
        if post.posted_at < since:
            continue
        count += 1
        yield post
    log.info("lobsters: yielded %d posts", count)


def _to_raw_post(entry: Any) -> RawPost | None:
    link = entry.get("link") or entry.get("id")
    if not link:
        return None
    title = (entry.get("title") or "").strip()
    summary = (entry.get("summary") or "").strip()
    text = f"{title}\n\n{summary}".strip()
    if not text:
        return None

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        posted_at = datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None

    raw_id = entry.get("id") or link
    return RawPost(
        id=f"lobsters:{_short_id(raw_id)}",
        source="lobsters",
        author_handle=_author_name(entry),
        author_role_hint=None,
        posted_at=posted_at,
        url=link,
        text=text,
        score=0,
        replies_count=0,
        raw={"tags": [t.get("term") for t in (entry.get("tags") or []) if isinstance(t, dict)]},
    )


def _short_id(s: str) -> str:
    """Pull the Lobsters story slug from a URL like https://lobste.rs/s/abc123/title."""
    if "/s/" in s:
        parts = s.rsplit("/", 2)
        if len(parts) >= 2:
            return parts[-2] or parts[-1]
    return s


def _author_name(entry: Any) -> str | None:
    author = entry.get("author")
    if isinstance(author, str) and author:
        return author
    detail = entry.get("author_detail")
    if isinstance(detail, dict):
        name = detail.get("name")
        if isinstance(name, str) and name:
            return name
    return None
