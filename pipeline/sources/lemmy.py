"""Lemmy source — federated Reddit-clone, public REST API per instance.

Lemmy was added after Reddit's Nov-2025 API gating made Reddit ingestion
infeasible from CI. Volume is lower (Lemmy is small) but signal-to-noise
is high — instances like programming.dev are dev-focused by construction.

The Lemmy API is documented at https://join-lemmy.org/api/. Each instance
exposes `/api/v3/post/list` with no auth required; data-center IPs are
fine. Pagination is `?page=N` (1-indexed); `?sort=New` returns reverse
chronological, so we can short-circuit once we cross the `since` cutoff.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipeline.config import LEMMY_COMMUNITIES
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

PAGE_SIZE = 50
MAX_PAGES = 10


def fetch(since: datetime) -> Iterator[RawPost]:
    """Yield every Lemmy post newer than `since` across all configured communities."""
    for instance, community, role_hint in LEMMY_COMMUNITIES:
        count = 0
        for post in _fetch_community(instance, community, role_hint, since):
            count += 1
            yield post
        log.info("lemmy: %s/c/%s yielded %d posts", instance, community, count)


def _fetch_community(
    instance: str,
    community: str,
    role_hint: str,
    since: datetime,
) -> Iterator[RawPost]:
    url = f"https://{instance}/api/v3/post/list"
    page = 1
    while page <= MAX_PAGES:
        params: dict[str, Any] = {
            "community_name": community,
            "sort": "New",
            "limit": PAGE_SIZE,
            "page": page,
        }
        try:
            data = get_json(url, params=params)
        except Exception:
            log.exception(
                "lemmy: fetch failed for %s/c/%s page=%d", instance, community, page
            )
            return

        posts = data.get("posts", [])
        if not posts:
            return

        saw_old = False
        for entry in posts:
            raw = _to_raw_post(entry, instance, community, role_hint)
            if raw is None:
                continue
            if raw.posted_at < since:
                # `sort=New` is reverse-chronological; once we see anything
                # below the cutoff we can stop paginating after this page.
                saw_old = True
                continue
            yield raw

        if saw_old or len(posts) < PAGE_SIZE:
            return
        page += 1


def _to_raw_post(
    entry: dict[str, Any],
    instance: str,
    community: str,
    role_hint: str,
) -> RawPost | None:
    post = entry.get("post") or {}
    pid = post.get("id")
    if pid is None:
        return None

    name = (post.get("name") or "").strip()
    body = (post.get("body") or "").strip()
    text = f"{name}\n\n{body}".strip()
    if not text:
        return None

    published = post.get("published")
    if not published:
        return None
    try:
        posted_at = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
    except ValueError:
        return None
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    creator = entry.get("creator") or {}
    counts = entry.get("counts") or {}

    permalink = post.get("ap_id") or f"https://{instance}/post/{pid}"

    return RawPost(
        id=f"lemmy:{instance}:{pid}",
        source="lemmy",
        author_handle=creator.get("name"),
        author_role_hint=role_hint,
        posted_at=posted_at,
        url=str(permalink),
        text=text,
        score=int(counts.get("score") or 0),
        replies_count=int(counts.get("comments") or 0),
        raw={"instance": instance, "community": community},
    )
