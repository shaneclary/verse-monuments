"""Shared HTTP client + cache-through fetch for network connectors (Spec §3).

* Polite rate limiting (default <= 5 req/s, configurable per source).
* Fail loudly: any transport error or HTTP >= 400 raises FetchError. We never
  return empty-on-error.
* Cache-through: every successful body is written to raw_cache, so a later
  --offline run reproduces the report from SQLite with no network (Spec §4).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..db import DB
from ..errors import FetchError

USER_AGENT = "KODEX/1.0 (offline ADR decision-support; operator-run batch)"


class HttpClient:
    """Thin rate-limited wrapper over httpx.Client."""

    def __init__(self, rps: float = 5.0, timeout: float = 30.0):
        self._min_interval = 1.0 / rps if rps > 0 else 0.0
        self._last = 0.0
        self.client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        self._throttle()
        try:
            resp = self.client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise FetchError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise FetchError(f"GET {url} -> HTTP {resp.status_code}")
        return resp

    def stream_to_file(self, url: str, dest_path: str, max_bytes: int) -> int:
        """Stream a (potentially huge) body to disk without buffering it whole
        in memory (Spec §3.4). Returns bytes written; raises if over max_bytes."""
        self._throttle()
        written = 0
        try:
            with self.client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise FetchError(f"GET {url} -> HTTP {resp.status_code}")
                with open(dest_path, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=1 << 20):  # 1 MiB
                        fh.write(chunk)
                        written += len(chunk)
                        if written > max_bytes:
                            raise FetchError(
                                f"GET {url} exceeded max_download_bytes ({max_bytes}); aborting stream."
                            )
        except httpx.HTTPError as exc:
            raise FetchError(f"stream {url} failed: {type(exc).__name__}: {exc}") from exc
        return written

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def cached_text(
    db: DB,
    http: HttpClient | None,
    *,
    source: str,
    key: str,
    url: str,
    params: dict[str, Any] | None = None,
    offline: bool,
) -> str:
    """Return a response body, using the cache.

    offline=True  -> read from cache only; CacheMiss if absent (no fabrication).
    offline=False -> fetch, cache, return. http must be provided.
    """
    if offline:
        return db.cache_require(source, key)
    if http is None:
        raise ValueError("cached_text requires an HttpClient when offline=False")
    body = http.get(url, params=params).text
    db.cache_put(source, key, body, url=url)
    return body
