// Cloudflare Worker: serves public/ as static assets and answers /api/*
// from the same four public sources serve.py proxies.
// A missing value is an error, never a zero filled in here.

const TTL = 600;
const UA = "BhuNetra/0.1 (open research page; https://github.com/Himanshu-5680/BhuNetra)";
const GEO = "https://geocoding-api.open-meteo.com/v1/search?count=5&countryCode=IN&name=";
const FORECAST = (lat, lon) =>
  "https://api.open-meteo.com/v1/forecast?current=temperature_2m" +
  "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum" +
  `&timezone=auto&forecast_days=3&latitude=${lat}&longitude=${lon}`;
const AIR = (lat, lon) =>
  `https://air-quality-api.open-meteo.com/v1/air-quality?current=us_aqi,pm2_5&latitude=${lat}&longitude=${lon}`;
const QUAKE = (lat, lon, start) =>
  "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson" +
  "&maxradiuskm=300&minmagnitude=3&orderby=magnitude&limit=20" +
  `&latitude=${lat}&longitude=${lon}&starttime=${start}`;

// Per-isolate only: Cloudflare runs many isolates, so this is a soft limit.
const hits = new Map();

class HttpError extends Error {
  constructor(status) {
    super("HTTP " + status);
    this.status = status;
  }
}

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function cleanName(raw) {
  const name = (raw || "").trim();
  if (!name || name.length > 80) return null;
  for (const ch of name) if (ch.charCodeAt(0) < 32) return null;
  return name;
}

function asFloat(raw) {
  if (raw === null || raw === undefined || String(raw).trim() === "") return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function inIndiaBox(lat, lon) {
  return lat >= 6.0 && lat <= 37.5 && lon >= 68.0 && lon <= 98.0;
}

function allow(ip) {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < 60000);
  if (recent.length >= 60) {
    hits.set(ip, recent);
    return false;
  }
  recent.push(now);
  hits.set(ip, recent);
  return true;
}

async function cached(url, waitUntil) {
  const cache = caches.default;
  const key = new Request(url);
  const hit = await cache.match(key);
  if (hit) {
    return { data: await hit.json(), ms: Number(hit.headers.get("X-Elapsed-Ms")) || 0, cached: true };
  }
  const started = Date.now();
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/json" },
    signal: AbortSignal.timeout(12000),
  });
  if (!res.ok) throw new HttpError(res.status);
  const text = await res.text();
  const data = JSON.parse(text);
  const ms = Date.now() - started;
  waitUntil(
    cache.put(
      key,
      new Response(text, {
        headers: {
          "Content-Type": "application/json",
          "Cache-Control": `max-age=${TTL}`,
          "X-Elapsed-Ms": String(ms),
        },
      }),
    ),
  );
  return { data, ms, cached: false };
}

function packError(url, message) {
  return { ok: false, error: message, url, elapsed_ms: null, cached: false };
}

function errorText(err) {
  return err instanceof HttpError ? err.message : "source did not respond";
}

async function readSource(url, waitUntil) {
  try {
    const { data, ms, cached: wasCached } = await cached(url, waitUntil);
    return { ok: true, data, url, elapsed_ms: ms, cached: wasCached };
  } catch (err) {
    return packError(url, errorText(err));
  }
}

function placeView(row) {
  return {
    id: row.id ?? null,
    name: row.name ?? null,
    admin1: row.admin1 ?? null,
    admin2: row.admin2 ?? null,
    latitude: row.latitude ?? null,
    longitude: row.longitude ?? null,
  };
}

function pickPlace(results, query) {
  const wanted = query.trim().toLowerCase();
  return results.find((row) => String(row.name || "").toLowerCase() === wanted) || results[0];
}

function otherPlaces(results, picked) {
  const seen = new Set();
  const out = [];
  for (const row of results) {
    if (row === picked || (picked.id != null && row.id === picked.id)) continue;
    const key = ["name", "admin1", "admin2"].map((k) => String(row[k] || "")).join("|").toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(placeView(row));
    if (out.length === 3) break;
  }
  return out;
}

async function geo(params, waitUntil) {
  const name = cleanName(params.get("name"));
  if (!name) return json({ ok: false, error: "type a place name" }, 400);
  const url = GEO + encodeURIComponent(name);
  let payload, ms, wasCached;
  try {
    ({ data: payload, ms, cached: wasCached } = await cached(url, waitUntil));
  } catch (err) {
    return json(packError(url, errorText(err)));
  }
  const results = payload && Array.isArray(payload.results) ? payload.results : null;
  const noPlace = { ok: false, error: "no_place", url, elapsed_ms: ms, cached: wasCached };
  if (!results || !results.length) return json(noPlace);
  const picked = pickPlace(results, name);
  if (asFloat(picked.latitude) === null || asFloat(picked.longitude) === null) return json(noPlace);
  return json({
    ok: true,
    url,
    elapsed_ms: ms,
    cached: wasCached,
    place: placeView(picked),
    alternatives: otherPlaces(results, picked),
    pool: results.map(placeView),
  });
}

function point(params) {
  const lat = asFloat(params.get("lat"));
  const lon = asFloat(params.get("lon"));
  if (lat === null || lon === null || !inIndiaBox(lat, lon)) return null;
  return [lat, lon];
}

const badPoint = () => json({ ok: false, error: "coordinates are missing or outside the India box" }, 400);

async function api(request, url, waitUntil) {
  if (request.method !== "GET") return json({ ok: false, error: "method not allowed" }, 405);
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (!allow(ip)) return json({ ok: false, error: "too many requests" }, 429);

  const route = url.pathname.slice("/api/".length).replace(/\/+$/, "");
  const query = url.searchParams;

  if (route === "geo") return geo(query, waitUntil);

  const sources = {
    weather: (lat, lon) => FORECAST(lat, lon),
    air: (lat, lon) => AIR(lat, lon),
    quakes: (lat, lon) => {
      const start = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
      return QUAKE(lat, lon, start);
    },
  };
  if (!(route in sources)) return json({ ok: false, error: "unknown" }, 404);

  const pair = point(query);
  if (!pair) return badPoint();
  return json(await readSource(sources[route](pair[0], pair[1]), waitUntil));
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) return api(request, url, (p) => ctx.waitUntil(p));
    if (url.pathname === "/favicon.ico") {
      return env.ASSETS.fetch(new Request(new URL("/favicon.png", url), request));
    }
    return env.ASSETS.fetch(request);
  },
};
