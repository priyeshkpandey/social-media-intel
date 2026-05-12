"""Reddit source — paginates `new` listings for each subreddit in config.SUBREDDITS.

`old.reddit.com` blocks data-center IPs (GitHub-hosted runners always 403).
When `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` are present in the env we
use Reddit's OAuth app-only flow against `oauth.reddit.com` (100 req/min,
works from cloud IPs). Without those credentials we fall back to the
anonymous endpoint, which is fine for local dev from a residential IP.

Register a "script"-type app at https://www.reddit.com/prefs/apps to obtain
the client_id and client_secret.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests

from pipeline.config import HTTP_TIMEOUT_SECONDS, SUBREDDITS, USER_AGENT
from pipeline.models import RawPost
from pipeline.sources._http import get_json

log = logging.getLogger(__name__)

OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE = "https://oauth.reddit.com"
ANON_BASE = "https://old.reddit.com"
PAGE_SIZE = 100

# Module-level cache for the app-only OAuth token (one per pipeline run).
_oauth_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def fetch(since: datetime) -> Iterator[RawPost]:
    """Yield every Reddit post newer than `since` from each configured subreddit."""
    token = _get_oauth_token()
    if token:
        log.info("reddit: using OAuth app-only auth (oauth.reddit.com)")
    else:
        log.warning(
            "reddit: no REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET — falling back to "
            "anonymous endpoint, which is blocked from data-center IPs (GHA runners)"
        )

    for subreddit, role_hint in SUBREDDITS.items():
        count = 0
        for post in _fetch_subreddit(subreddit, role_hint, since, token):
            count += 1
            yield post
        log.info("reddit: r/%s yielded %d posts", subreddit, count)


def _get_oauth_token() -> str | None:
    """Fetch and cache an app-only OAuth token. Returns None when creds are unset."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (client_id and client_secret):
        return None

    now = time.monotonic()
    if _oauth_cache["token"] and _oauth_cache["expires_at"] > now + 30:
        return str(_oauth_cache["token"])

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        resp = requests.post(
            OAUTH_TOKEN_URL,
            headers={
                "Authorization": f"Basic {creds}",
                "User-Agent": USER_AGENT,
            },
            data={
                "grant_type": "client_credentials",
                "device_id": "DO_NOT_TRACK_THIS_DEVICE",
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except Exception:
        log.exception("reddit: OAuth token request failed; falling back to anonymous")
        return None
    if not resp.ok:
        log.warning(
            "reddit: OAuth token request returned %d; falling back to anonymous",
            resp.status_code,
        )
        return None

    data = resp.json()
    token = data.get("access_token")
    if not token:
        log.warning("reddit: OAuth response missing access_token; falling back")
        return None
    _oauth_cache["token"] = token
    _oauth_cache["expires_at"] = now + int(data.get("expires_in", 3600))
    return str(token)


def _fetch_subreddit(
    subreddit: str,
    role_hint: str,
    since: datetime,
    token: str | None,
) -> Iterator[RawPost]:
    base = OAUTH_BASE if token else ANON_BASE
    url = f"{base}/r/{subreddit}/new.json"
    headers = {"Authorization": f"Bearer {token}"} if token else None

    after: str | None = None
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if after is not None:
            params["after"] = after
        try:
            data = get_json(url, params=params, headers=headers)
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
