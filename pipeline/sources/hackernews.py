"""Hacker News source — Algolia HN Search API (free, no auth).

For each query in config.HN_QUERIES, fetch both `story` and `ask_hn` tags
since the cutoff timestamp. Algolia caps responses at 1000 hits per query;
we paginate up to `nbPages` (typically <=10 pages of 100).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipeline.config import HN_QUERIES
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
HITS_PER_PAGE = 100
MAX_PAGES = 10
TAGS_TO_SEARCH: tuple[str, ...] = ("story", "ask_hn")


def fetch(since: datetime) -> Iterator[RawPost]:
    """Yield every HN post newer than `since` matching any configured query."""
    since_ts = int(since.timestamp())
    for query in HN_QUERIES:
        for tag in TAGS_TO_SEARCH:
            count = 0
            for post in _fetch_query(query, tag, since_ts):
                count += 1
                yield post
            log.info("hn: query=%r tag=%s yielded %d posts", query, tag, count)


def _fetch_query(query: str, tag: str, since_ts: int) -> Iterator[RawPost]:
    page = 0
    while page < MAX_PAGES:
        params: dict[str, Any] = {
            "query": query,
            "tags": tag,
            "numericFilters": f"created_at_i>{since_ts}",
            "hitsPerPage": HITS_PER_PAGE,
            "page": page,
        }
        try:
            data = get_json(ALGOLIA_URL, params=params)
        except Exception:
            log.exception("hn: fetch failed for query=%r tag=%s", query, tag)
            return

        hits = data.get("hits", [])
        if not hits:
            return
        for hit in hits:
            post = _to_raw_post(hit)
            if post is not None:
                yield post

        nb_pages = int(data.get("nbPages") or 0)
        page += 1
        if page >= nb_pages:
            return


def _to_raw_post(hit: dict[str, Any]) -> RawPost | None:
    object_id = hit.get("objectID")
    if not object_id:
        return None
    title = (hit.get("title") or "").strip()
    body = (hit.get("story_text") or hit.get("comment_text") or "").strip()
    text = f"{title}\n\n{body}".strip()
    if not text:
        return None
    created_at_i = hit.get("created_at_i")
    if created_at_i is None:
        return None
    return RawPost(
        id=f"hn:{object_id}",
        source="hackernews",
        author_handle=hit.get("author"),
        author_role_hint=None,
        posted_at=datetime.fromtimestamp(int(created_at_i), tz=UTC),
        url=f"https://news.ycombinator.com/item?id={object_id}",
        text=text,
        score=int(hit.get("points") or 0),
        replies_count=int(hit.get("num_comments") or 0),
        raw={"_tags": hit.get("_tags", [])},
    )
