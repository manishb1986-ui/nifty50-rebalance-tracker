"""HTTP session that behaves like a browser (NSE rejects bare clients)."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests

from . import config

log = logging.getLogger(__name__)
_session: requests.Session | None = None
_warmed: set[str] = set()


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        _session = s
    return _session


def _warm_up(url: str) -> None:
    """NSE hosts set cookies on the home page; visit it once per run."""
    host = urlparse(url).netloc
    if "nseindia.com" in host and "nseindia" not in _warmed:
        try:
            session().get("https://www.nseindia.com", timeout=config.HTTP_TIMEOUT)
        except requests.RequestException as exc:  # warm-up is best effort
            log.debug("warm-up failed: %s", exc)
        _warmed.add("nseindia")


def get(url: str, retries: int = 3, backoff: float = 2.0, **kwargs) -> requests.Response | None:
    """GET with retries. Returns the response for 2xx, None otherwise."""
    _warm_up(url)
    headers = kwargs.pop("headers", {})
    if "nseindia.com" in url:
        headers.setdefault("Referer", "https://www.nseindia.com/")
    for attempt in range(1, retries + 1):
        try:
            r = session().get(url, timeout=config.HTTP_TIMEOUT, headers=headers, **kwargs)
            if r.status_code == 404:
                return None
            if r.ok:
                return r
            log.warning("GET %s -> HTTP %s (attempt %d)", url, r.status_code, attempt)
        except requests.RequestException as exc:
            log.warning("GET %s failed: %s (attempt %d)", url, exc, attempt)
        if attempt < retries:
            time.sleep(backoff * attempt)
    return None
