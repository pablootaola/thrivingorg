"""Minimal HTTP helper. Honest user agent, retries with backoff, no credential handling."""
from __future__ import annotations

import time

import requests

from . import USER_AGENT

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def get(url: str, *, params=None, timeout=60, retries=3, stream=False, **kw) -> requests.Response:
    last = None
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout, stream=stream, **kw)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}", response=r)
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def post_json(url: str, payload: dict, timeout=60, retries=3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            r = _session.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            last = e
            time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]
