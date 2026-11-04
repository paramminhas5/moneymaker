"""Polite HTTP client: honest User-Agent, timeouts, bounded retries with backoff, min interval."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from mm import __version__

USER_AGENT = f"moneymaker-data/{__version__} (+https://github.com/paramminhas5/moneymaker)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceUnavailableError(RuntimeError):
    """Raised when a source refuses us (e.g. 403/451). We do not try to get around refusals."""


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval_s: float = 0.25,
        max_retries: int = 4,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
            transport=transport,
            follow_redirects=True,
        )
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._sleep = sleep
        self._last = 0.0

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            resp = self._client.request(method, url, **kwargs)
            if resp.status_code in (401, 403, 451):
                raise SourceUnavailableError(
                    f"{url} refused with HTTP {resp.status_code}; not retrying or working around it"
                )
            if resp.status_code in RETRY_STATUS and attempt < self._max_retries:
                retry_after = resp.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                self._sleep(min(delay, 60.0))
                continue
            return resp
        raise RuntimeError("unreachable")  # pragma: no cover

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
