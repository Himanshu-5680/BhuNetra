"""Bronze layer: raw responses, immutable, timestamped, with provenance sidecar."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from pathlib import Path


def write_bronze(root: Path, source: str, key: str, url: str, params: dict | None,
                 body: bytes, status: int = 200, ext: str = "json") -> Path:
    """Save raw bytes + <file>.meta.json (source, time, url, params, sha256). Never overwrites."""
    now = datetime.now(timezone.utc)
    d = Path(root) / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}__{now.strftime('%Y%m%dT%H%M%S%fZ')}.{ext}"
    if path.exists():
        raise FileExistsError(f"bronze is immutable: {path}")
    path.write_bytes(body)
    meta = {"source": source, "fetched_at_utc": now.isoformat(), "url": url,
            "params": params or {}, "http_status": status,
            "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    Path(str(path) + ".meta.json").write_text(json.dumps(meta, indent=2))
    return path


def read_meta(path: Path) -> dict:
    return json.loads(Path(str(path) + ".meta.json").read_text())


def verify_checksum(path: Path) -> bool:
    """True if the raw file still matches the checksum recorded at fetch time."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() == read_meta(path)["sha256"]
