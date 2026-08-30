from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_TIMEOUT = 30


def make_session(
    *,
    referer: str | None = None,
    retries: int = 5,
    backoff_factor: float = 1.0,
) -> requests.Session:
    """
    Create a requests.Session with retry/backoff for transient failures.

    Retries connection/read errors and HTTP 429/500/502/503/504 responses.
    """
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,
        pool_maxsize=10,
    )

    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    if referer:
        session.headers["Referer"] = referer

    return session


def get(
    session: requests.Session,
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
) -> requests.Response:
    """GET with a consistent timeout and final HTTP status check."""
    response = session.get(url, timeout=timeout, **kwargs)
    response.raise_for_status()
    return response
