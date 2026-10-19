"""HTTP client: retries with backoff, timeout, User-Agent, and Bronze caching with provenance.

Every response saved to data/bronze/ gets a sidecar `.meta.json` recording where it came
from, when, with which parameters, and a SHA-256 checksum. Bronze files are never edited.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from bhunetra import __version__

USER_AGENT = f"bhunetra/{__version__} (open-source research; +https://github.com/OWNER/bhunetra)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class DataUnavailable(RuntimeError):
    """Raised when a source cannot be fetched. The UI must show this honestly, never fill in."""

    def __init__(self, msg: str, status: int | None = None, body: str = ""):
        super().__init__(msg)
        self.status = status   # last HTTP status seen (e.g. 429), None for network errors
        self.body = body       # start of the server's reply, tells us WHICH limit was hit


@dataclass
class Fetched:
    path: Path
    meta: dict


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def fetch_to_bronze(
    source: str,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    bronze_dir: str | Path = "data/bronze",
    ext: str = "json",
    retries: int = 4,
    timeout: float = 30.0,
    backoff: float = 2.0,
    session: requests.Session | None = None,
    extra_meta: dict | None = None,
) -> Fetched:
    """GET `url`, retry on transient errors, save raw bytes + provenance sidecar."""
    s = session or requests.Session()
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last_err: Exception | None = None
    last_status, last_body = None, ""
    for attempt in range(retries + 1):
        try:
            r = s.get(url, params=params, headers=hdrs, timeout=timeout)
            if r.status_code in RETRY_STATUS:
                # Respect server's Retry-After if given, else exponential backoff.
                wait = float(r.headers.get("Retry-After", backoff ** attempt))
                last_err = RuntimeError(f"HTTP {r.status_code}")
                last_status, last_body = r.status_code, r.text[:300]
                time.sleep(min(wait, 60))
                continue
            r.raise_for_status()
            break
        except requests.RequestException as e:  # network error, timeout, 4xx
            last_err = e
            if isinstance(e, requests.HTTPError):  # 4xx other than 429: do not retry
                raise DataUnavailable(f"{source}: {e} | server said: {r.text[:300]}",
                                      status=r.status_code, body=r.text[:300]) from e
            time.sleep(min(backoff ** attempt, 60))
    else:
        raise DataUnavailable(f"{source}: failed after {retries + 1} tries: {last_err}"
                              + (f" | server said: {last_body}" if last_body else ""),
                              status=last_status, body=last_body)

    stamp = _utcnow()
    out_dir = Path(bronze_dir) / source
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stamp}.{ext}"
    path.write_bytes(r.content)
    # Never store secrets in provenance.
    safe_params = {k: v for k, v in (params or {}).items() if k.lower() not in {"api_key", "map_key"}}
    meta = {
        "source": source,
        "url": url,
        "params": safe_params,
        "fetched_at_utc": stamp,
        "http_status": r.status_code,
        "bytes": len(r.content),
        "sha256": hashlib.sha256(r.content).hexdigest(),
        "client": USER_AGENT,
        **(extra_meta or {}),
    }
    path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, indent=2))
    return Fetched(path, meta)


def latest_bronze(source: str, bronze_dir: str | Path = "data/bronze", ext: str = "json") -> Path:
    files = sorted((Path(bronze_dir) / source).glob(f"*.{ext}"))
    if not files:
        raise DataUnavailable(f"No Bronze data for '{source}'. Run: bhunetra ingest {source}")
    return files[-1]
