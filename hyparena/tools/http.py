"""Shared HTTP helper for connectors: one client, retries with backoff, last error kept."""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx


class Http:
    def __init__(self, timeout: float = 30.0, retries: int = 2, client: Optional[httpx.Client] = None):
        self.retries = retries
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.last_error = ""

    def get_json(self, url: str, params: Optional[dict] = None, ok_404: bool = False) -> Optional[Any]:
        for attempt in range(self.retries + 1):
            try:
                r = self.client.get(url, params=params)
                if ok_404 and r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPError, ValueError) as e:
                self.last_error = f"{type(e).__name__}: {e}"[:300]
                time.sleep(2 * (attempt + 1))
        return None
