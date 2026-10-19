"""HTTP fuer die Universum-Quellen: Retry und ein ehrlicher User-Agent."""

from __future__ import annotations

from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

USER_AGENT = "value-analyzer/1.0 (private, weekly)"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def http_get(url: str, params: dict[str, str] | None = None, timeout: float = 30.0) -> Any:
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response
