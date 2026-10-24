#!/usr/bin/env python3
"""Serve the BhuNetra page and the four public sources it is allowed to call.

The browser asks this process. This process asks only the endpoints already
used by the page: Open-Meteo geocoding, forecast, and air quality, and the
USGS earthquake catalogue. Answers are cached in memory for 10 minutes.
A missing value is an error, never a zero filled in here.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "public"
PAGE = ROOT / "index.html"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
TTL = 600
UA = "BhuNetra/0.1 (open research page; https://github.com/Himanshu-5680/BhuNetra)"
LOCK = threading.Lock()
CACHE: dict[str, dict] = {}
HITS: dict[str, list[float]] = {}

GEO = "https://geocoding-api.open-meteo.com/v1/search?count=5&countryCode=IN&name="
FORECAST = (
    "https://api.open-meteo.com/v1/forecast?current=temperature_2m"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum"
    "&timezone=auto&forecast_days=3&latitude={lat}&longitude={lon}"
)
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality?current=us_aqi,pm2_5&latitude={lat}&longitude={lon}"
QUAKE = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
    "&maxradiuskm=300&minmagnitude=3&orderby=magnitude&limit=20"
    "&latitude={lat}&longitude={lon}&starttime={start}"
)


def clean_name(raw: str | None) -> str | None:
    name = (raw or "").strip()
    if not name or len(name) > 80:
        return None
    if any(ord(ch) < 32 for ch in name):
        return None
    return name


def as_float(raw: str | None) -> float | None:
    try:
        value = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if value is None or not math.isfinite(value):
        return None
    return value


def in_india_box(lat: float, lon: float) -> bool:
    return 6.0 <= lat <= 37.5 and 68.0 <= lon <= 98.0


def allow(ip: str) -> bool:
    now = time.time()
    with LOCK:
        recent = [t for t in HITS.get(ip, []) if now - t < 60]
        if len(recent) >= 60:
            HITS[ip] = recent
            return False
        recent.append(now)
        HITS[ip] = recent
    return True


def fetch(url: str) -> tuple[object, int]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=12) as response:
        body = response.read()
    elapsed = int((time.perf_counter() - started) * 1000)
    return json.loads(body), elapsed


def cached(url: str) -> tuple[object, int, bool]:
    now = time.time()
    with LOCK:
        hit = CACHE.get(url)
        if hit and now - hit["t"] < TTL:
            return hit["data"], hit["ms"], True
    data, elapsed = fetch(url)
    with LOCK:
        CACHE[url] = {"t": time.time(), "data": data, "ms": elapsed}
    return data, elapsed, False


def other_places(results: list[dict], picked: dict) -> list[dict]:
    seen = set()
    out = []
    for row in results:
        if row is picked or (picked.get("id") is not None and row.get("id") == picked.get("id")):
            continue
        key = "|".join(str(row.get(k) or "") for k in ("name", "admin1", "admin2")).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(place_view(row))
        if len(out) == 3:
            break
    return out


def place_view(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "admin1": row.get("admin1"),
        "admin2": row.get("admin2"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
    }


def pick_place(results: list[dict], query: str) -> dict:
    wanted = query.strip().lower()
    for row in results:
        if str(row.get("name") or "").lower() == wanted:
            return row
    return results[0]


def pack_error(url: str, message: str) -> dict:
    return {"ok": False, "error": message, "url": url, "elapsed_ms": None, "cached": False}


def read_source(url: str) -> dict:
    try:
        data, elapsed, was_cached = cached(url)
    except urllib.error.HTTPError as exc:
        return pack_error(url, "HTTP " + str(exc.code))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return pack_error(url, "source did not respond")
    return {"ok": True, "data": data, "url": url, "elapsed_ms": elapsed, "cached": was_cached}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            self.send_error(404)
            return
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(raw)

    def client_ip(self) -> str:
        return self.client_address[0]

    def query(self) -> dict[str, str]:
        parsed = urllib.parse.urlparse(self.path)
        pairs = urllib.parse.parse_qs(parsed.query)
        return {key: values[0] for key, values in pairs.items() if values}

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html", "/bhunetra.html"):
            self.send_file(PAGE, "text/html; charset=utf-8")
            return
        if path == "/favicon.svg":
            self.send_file(ROOT / "favicon.svg", "image/svg+xml")
            return
        if path in ("/favicon.ico", "/favicon.png"):
            self.send_file(ROOT / "favicon.png", "image/png")
            return
        if path == "/healthz":
            self.send_json({"ok": True})
            return
        if not path.startswith("/api/"):
            self.send_error(404)
            return
        if not allow(self.client_ip()):
            self.send_json({"ok": False, "error": "too many requests"}, 429)
            return
        if path == "/api/geo":
            self.geo()
        elif path == "/api/weather":
            self.point_source(FORECAST)
        elif path == "/api/air":
            self.point_source(AIR)
        elif path == "/api/quakes":
            self.quakes()
        else:
            self.send_json({"ok": False, "error": "unknown"}, 404)

    def point(self) -> tuple[float, float] | None:
        args = self.query()
        lat, lon = as_float(args.get("lat")), as_float(args.get("lon"))
        if lat is None or lon is None or not in_india_box(lat, lon):
            self.send_json({"ok": False, "error": "coordinates are missing or outside the India box"}, 400)
            return None
        return lat, lon

    def geo(self) -> None:
        name = clean_name(self.query().get("name"))
        if not name:
            self.send_json({"ok": False, "error": "type a place name"}, 400)
            return
        url = GEO + urllib.parse.quote(name)
        try:
            payload, elapsed, was_cached = cached(url)
        except urllib.error.HTTPError as exc:
            self.send_json(pack_error(url, "HTTP " + str(exc.code)))
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self.send_json(pack_error(url, "source did not respond"))
            return
        results = payload.get("results") if isinstance(payload, dict) else None
        if not results:
            self.send_json({"ok": False, "error": "no_place", "url": url, "elapsed_ms": elapsed, "cached": was_cached})
            return
        picked = pick_place(results, name)
        if as_float(str(picked.get("latitude"))) is None or as_float(str(picked.get("longitude"))) is None:
            self.send_json({"ok": False, "error": "no_place", "url": url, "elapsed_ms": elapsed, "cached": was_cached})
            return
        viewed = [place_view(row) for row in results]
        place = place_view(picked)
        self.send_json({
            "ok": True,
            "url": url,
            "elapsed_ms": elapsed,
            "cached": was_cached,
            "place": place,
            "alternatives": other_places(results, picked),
            "pool": viewed,
        })

    def point_source(self, template: str) -> None:
        pair = self.point()
        if not pair:
            return
        lat, lon = pair
        self.send_json(read_source(template.format(lat=lat, lon=lon)))

    def quakes(self) -> None:
        pair = self.point()
        if not pair:
            return
        lat, lon = pair
        start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 30 * 86400))
        self.send_json(read_source(QUAKE.format(lat=lat, lon=lon, start=start)))


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"BhuNetra listening on http://{HOST}:{PORT}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
