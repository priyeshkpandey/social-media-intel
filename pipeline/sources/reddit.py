"""Reddit source — paginates `new` listings for each subreddit in config.SUBREDDITS.

No auth: the public JSON endpoint at old.reddit.com is sufficient for read-only
access. We send a descriptive User-Agent (config.USER_AGENT) and back off on
429s — see pipeline.sources._http.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from pipeline.config import SUBREDDITS
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

REDDIT_BASE = "https://old.reddit.com"
PAGE_SIZE = 100


def fetch(since: datetime) -> Iterator[RawPost]:
    """Yield every Reddit post newer than `since` from each configured subreddit."""
    for subreddit, role_hint in SUBREDDITS.items():
        count = 0
        for post in _fetch_subreddit(subreddit, role_hint, since):
            count += 1
            yield post
        log.info("reddit: r/%s yielded %d posts", subreddit, count)


def _fetch_subreddit(
    subreddit: str, role_hint: str, since: datetime
) -> Iterator[RawPost]:
    after: str | None = None
    url = f"{REDDIT_BASE}/r/{subreddit}/new.json"
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if after is not None:
            params["after"] = after
        try:
            data = get_json(url, params=params)
        except Exception:
            log.exception("reddit: fetch failed for r/%s", subreddit)
            return

        children = data.get("data", {}).get("children", [])
        if not children:
            return

        for child in children:
            post = _to_raw_post(child.get("data", {}), subreddit, role_hint)
            if post is None:
                continue
            if post.posted_at < since:
                # `new` listings are reverse-chronological — we've crossed the cutoff.
                return
            yield post

        after = data.get("data", {}).get("after")
        if not after:
            return


def _to_raw_post(
    data: dict[str, Any], subreddit: str, role_hint: str
) -> RawPost | None:
    if data.get("stickied") or data.get("is_video"):
        return None
    post_id = data.get("id")
    if not post_id:
        return None
    title = (data.get("title") or "").strip()
    selftext = (data.get("selftext") or "").strip()
    text = f"{title}\n\n{selftext}".strip()
    if not text:
        return None
    created = data.get("created_utc")
    if created is None:
        return None
    permalink = data.get("permalink") or f"/r/{subreddit}/comments/{post_id}"
    return RawPost(
        id=f"reddit:{post_id}",
        source="reddit",
        author_handle=data.get("author"),
        author_role_hint=role_hint,
        posted_at=datetime.fromtimestamp(float(created), tz=UTC),
        url=f"https://www.reddit.com{permalink}",
        text=text,
        score=int(data.get("score") or 0),
        replies_count=int(data.get("num_comments") or 0),
        raw={
            "subreddit": subreddit,
            "link_flair_text": data.get("link_flair_text"),
        },
    )
