"""HTTP helper: timeout, retry with exponential backoff, polite User-Agent."""
from __future__ import annotations
import time
import requests

USER_AGENT = "BhuNetra/0.0.1 (open-source research; github.com/your-org/bhunetra)"


class IngestError(RuntimeError):
    """Raised when a source cannot be fetched. We fail loudly, never fake data."""


def fetch(url: str, params: dict | None = None, headers: dict | None = None,
          retries: int = 4, backoff: float = 1.0, timeout: float = 30.0) -> requests.Response:
    """GET with retries on network errors, 429 and 5xx. 4xx (except 429) fail at once."""
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    last = "no attempt"
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code != 429 and r.status_code < 500:
                raise IngestError(f"{url} -> {last}: {r.text[:200]}")
            wait = float(r.headers.get("Retry-After", backoff * 2 ** attempt))
        except requests.RequestException as e:
            last, wait = f"network error: {e}", backoff * 2 ** attempt
        if attempt < retries:
            time.sleep(wait)
    raise IngestError(f"{url} failed after {retries + 1} attempts ({last})")
