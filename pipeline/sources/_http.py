"""Shared HTTP helper for source ingesters.

Centralizes the User-Agent, timeout, and retry-with-backoff policy so that
each source doesn't have to reinvent it. Treats 429 / 5xx as transient and
retries with exponential backoff; everything else surfaces immediately.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.config import (
    HTTP_BACKOFF_BASE_SECONDS,
    HTTP_MAX_RETRIES,
    HTTP_TIMEOUT_SECONDS,
    USER_AGENT,
)

log = logging.getLogger(__name__)


class TransientHTTPError(RuntimeError):
    """Retryable HTTP failure (429 or 5xx)."""


@retry(
    retry=retry_if_exception_type(TransientHTTPError),
    wait=wait_exponential(multiplier=HTTP_BACKOFF_BASE_SECONDS, max=30),
    stop=stop_after_attempt(HTTP_MAX_RETRIES),
    reraise=True,
)
def get_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET `url` and return the parsed JSON body."""
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    if response.status_code in (429, 500, 502, 503, 504):
        log.warning("transient HTTP %s for %s; will retry", response.status_code, url)
        raise TransientHTTPError(f"{response.status_code} for {url}")
    response.raise_for_status()
    return response.json()
