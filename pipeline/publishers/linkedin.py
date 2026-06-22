"""LinkedIn UGC Posts publisher.

Posts the weekly intelligence briefing to LinkedIn using a stored OAuth 2.0
access token. LinkedIn does not provide refresh tokens to standard (non-partner)
apps, so the 60-day access token must be renewed manually every ~55 days.
The workflow opens a GitHub issue when the token is within 10 days of expiry.

CLI usage:
    uv run python -m pipeline.publishers.linkedin post <post_file>
    uv run python -m pipeline.publishers.linkedin check-expiry

Required env vars:
    LINKEDIN_ACCESS_TOKEN     OAuth 2.0 access token (60-day expiry)
    LINKEDIN_PERSON_URN       Your person URN: urn:li:person:{sub from id_token}

Optional env vars:
    LINKEDIN_TOKEN_EXPIRES_AT ISO-8601 date when the token expires — enables
                              expiry warnings before the token goes stale
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_UGC_POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"
_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
_EXPIRY_WARN_DAYS = 10


# ---------------------------------------------------------------------------
# Person URN discovery
# ---------------------------------------------------------------------------


def get_person_urn(access_token: str) -> str:
    """Return the LinkedIn person URN for the token owner.

    Checks LINKEDIN_PERSON_URN env var first (no API call needed).
    Falls back to /v2/userinfo if the openid scope is present.
    """
    urn = os.environ.get("LINKEDIN_PERSON_URN", "").strip()
    if urn:
        return urn

    req = urllib.request.Request(
        _USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"LinkedIn userinfo failed ({exc.code}): {body_text}\n"
            "Set LINKEDIN_PERSON_URN in GitHub Secrets to fix this.\n"
            "Find your person ID by decoding the id_token JWT:\n"
            "  echo YOUR_ID_TOKEN | cut -d. -f2 | base64 -d | python3 -m json.tool\n"
            "Then set LINKEDIN_PERSON_URN=urn:li:person:{sub}"
        ) from exc

    sub = data.get("sub")
    if not sub:
        raise RuntimeError(f"userinfo response missing 'sub': {data!r}")
    return f"urn:li:person:{sub}"


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def post_text(text: str, access_token: str, person_urn: str) -> str:
    """Create a public LinkedIn text post. Returns the post URN."""
    payload = json.dumps(
        {
            "author": person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": text},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }
    ).encode()

    req = urllib.request.Request(
        _UGC_POSTS_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            post_id = resp.headers.get("x-restli-id", "")
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"LinkedIn post failed ({exc.code}): {body_text}"
        ) from exc

    log.info("linkedin: posted successfully — id=%s", post_id)
    return post_id


# ---------------------------------------------------------------------------
# Expiry check
# ---------------------------------------------------------------------------


def days_until_expiry() -> int | None:
    """Return days until LINKEDIN_TOKEN_EXPIRES_AT, or None if not set."""
    expires_at = os.environ.get("LINKEDIN_TOKEN_EXPIRES_AT", "").strip()
    if not expires_at:
        return None
    try:
        expiry = datetime.fromisoformat(expires_at).replace(tzinfo=UTC)
        return (expiry - datetime.now(tz=UTC)).days
    except ValueError:
        log.warning("linkedin: cannot parse LINKEDIN_TOKEN_EXPIRES_AT=%r", expires_at)
        return None


def check_expiry() -> bool:
    """Return True if the token is within EXPIRY_WARN_DAYS of expiry."""
    days = days_until_expiry()
    if days is None:
        log.info("linkedin: LINKEDIN_TOKEN_EXPIRES_AT not set — skipping expiry check")
        return False
    if days <= _EXPIRY_WARN_DAYS:
        log.warning("linkedin: token expires in %d days — renewal needed", days)
        return True
    log.info("linkedin: token valid for %d more days", days)
    return False


# ---------------------------------------------------------------------------
# High-level commands
# ---------------------------------------------------------------------------


def cmd_post(post_file: str) -> None:
    """Post text from file to LinkedIn."""
    text = Path(post_file).read_text(encoding="utf-8").strip()
    if not text:
        raise RuntimeError(f"Post file is empty: {post_file!r}")
    if len(text) > 3000:
        log.warning("linkedin: post text %d chars > 3000 — truncating", len(text))
        text = text[:3000].rsplit("\n", 1)[0].strip()

    access_token = _require_env("LINKEDIN_ACCESS_TOKEN")
    person_urn = get_person_urn(access_token)
    post_id = post_text(text, access_token, person_urn)
    print(f"Posted: {post_id}")


def cmd_check_expiry() -> None:
    """Exit with code 1 if token is within 10 days of expiry (for CI gating)."""
    if check_expiry():
        days = days_until_expiry()
        print(f"TOKEN_EXPIRING_SOON:{days}")
        raise SystemExit(1)
    print("TOKEN_OK")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set.")
    return value


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(prog="linkedin", description="LinkedIn publisher.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("post", help="Post text from a file to LinkedIn.")
    p.add_argument("file", help="Path to the plain-text post file.")

    sub.add_parser("check-expiry", help="Warn if token expires within 10 days.")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "post":
            cmd_post(args.file)
        elif args.cmd == "check-expiry":
            cmd_check_expiry()
    except RuntimeError as exc:
        log.error("linkedin: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
