"""Stack Exchange source — Stack Overflow questions for software-ops tags.

Free tier permits ~10k requests/day unauth (300/IP per 15 min). With weekly
cadence and ~6 tags, we sit comfortably below the cap. Bodies come back as
HTML; we pass them through and let the normalize stage strip markup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipeline.config import STACKEXCHANGE_SITE, STACKEXCHANGE_TAGS
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

API_URL = "https://api.stackexchange.com/2.3/questions"
PAGE_SIZE = 100
MAX_PAGES = 25


def fetch(since: datetime) -> Iterator[RawPost]:
    fromdate = int(since.timestamp())
    for tag in STACKEXCHANGE_TAGS:
        count = 0
        for post in _fetch_tag(tag, fromdate):
            count += 1
            yield post
        log.info("stackexchange: tag=%s yielded %d questions", tag, count)


def _fetch_tag(tag: str, fromdate: int) -> Iterator[RawPost]:
    page = 1
    while page <= MAX_PAGES:
        params: dict[str, Any] = {
            "site": STACKEXCHANGE_SITE,
            "tagged": tag,
            "fromdate": fromdate,
            "pagesize": PAGE_SIZE,
            "page": page,
            "order": "desc",
            "sort": "creation",
            "filter": "withbody",
        }
        try:
            data = get_json(API_URL, params=params)
        except Exception:
            log.exception("stackexchange: fetch failed for tag=%s page=%d", tag, page)
            return

        items = data.get("items", [])
        if not items:
            return
        for item in items:
            post = _to_raw_post(item, tag)
            if post is not None:
                yield post
        if not data.get("has_more"):
            return
        page += 1


def _to_raw_post(item: dict[str, Any], primary_tag: str) -> RawPost | None:
    qid = item.get("question_id")
    if qid is None:
        return None
    title = (item.get("title") or "").strip()
    body = (item.get("body") or "").strip()
    text = f"{title}\n\n{body}".strip()
    if not text:
        return None
    created = item.get("creation_date")
    if created is None:
        return None
    owner = item.get("owner") or {}
    return RawPost(
        id=f"stackexchange:{qid}",
        source="stackexchange",
        author_handle=owner.get("display_name"),
        author_role_hint=None,
        posted_at=datetime.fromtimestamp(int(created), tz=UTC),
        url=item.get("link") or f"https://stackoverflow.com/q/{qid}",
        text=text,
        score=int(item.get("score") or 0),
        replies_count=int(item.get("answer_count") or 0),
        raw={
            "tags": item.get("tags", []),
            "view_count": item.get("view_count"),
            "primary_tag": primary_tag,
        },
    )
