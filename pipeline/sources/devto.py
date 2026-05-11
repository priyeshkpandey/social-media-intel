"""dev.to source — public REST API, no auth.

For each tag in config.DEVTO_TAGS, paginate /api/articles newest-first and yield
articles newer than `since`. We pull only the listing endpoint (title +
description); fetching full article bodies would multiply requests by ~100.
Normalization is responsible for any further text cleanup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipeline.config import DEVTO_TAGS
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

DEVTO_URL = "https://dev.to/api/articles"
PER_PAGE = 100
MAX_PAGES = 10


def fetch(since: datetime) -> Iterator[RawPost]:
    for tag in DEVTO_TAGS:
        count = 0
        for post in _fetch_tag(tag, since):
            count += 1
            yield post
        log.info("devto: tag=%s yielded %d articles", tag, count)


def _fetch_tag(tag: str, since: datetime) -> Iterator[RawPost]:
    page = 1
    while page <= MAX_PAGES:
        params: dict[str, Any] = {"tag": tag, "per_page": PER_PAGE, "page": page}
        try:
            data = get_json(DEVTO_URL, params=params)
        except Exception:
            log.exception("devto: fetch failed for tag=%s page=%d", tag, page)
            return

        if not isinstance(data, list):
            log.warning("devto: unexpected payload shape for tag=%s", tag)
            return
        if not data:
            return

        saw_old = False
        for article in data:
            post = _to_raw_post(article, tag)
            if post is None:
                continue
            if post.posted_at < since:
                saw_old = True
                continue
            yield post

        # dev.to returns newest-first; once any article on the page predates `since`,
        # subsequent pages will only go further back.
        if saw_old or len(data) < PER_PAGE:
            return
        page += 1


def _to_raw_post(article: dict[str, Any], primary_tag: str) -> RawPost | None:
    article_id = article.get("id")
    if article_id is None:
        return None
    title = (article.get("title") or "").strip()
    desc = (article.get("description") or "").strip()
    text = f"{title}\n\n{desc}".strip()
    if not text:
        return None
    published = article.get("published_at") or article.get("created_at")
    if not published:
        return None
    try:
        posted_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
    except ValueError:
        return None
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    user = article.get("user") or {}
    return RawPost(
        id=f"devto:{article_id}",
        source="devto",
        author_handle=user.get("username"),
        author_role_hint=None,
        posted_at=posted_at,
        url=article.get("url") or article.get("canonical_url") or "",
        text=text,
        score=int(article.get("public_reactions_count") or 0),
        replies_count=int(article.get("comments_count") or 0),
        raw={"tag_list": article.get("tag_list", []), "primary_tag": primary_tag},
    )
