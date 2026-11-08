"""Car location → lat/lon + distance from `owner.home`.

- Geocode: Nominatim (public, 1 request/s, generic User-Agent — never a personal email), cached in
  `$CARHUNT_HOME/discover/geocode.json` (only hits are cached; misses retry next run).
- Road km: optional OSRM router (`discover.distance.router`, default none — the public demo server has no SLA);
  otherwise great-circle × `search.road_factor` (default 1.3).
- cardb estimates distance itself from lat/lon; discover sends `distance_km` only for real road km.
"""
from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from carhunt.discover import _env

NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "carhunt/1.0 (used-car search tool; low volume, cached)"   # override: discover.distance.user_agent
MIN_GAP_S = 1.1
Fetch = Callable[[str], Any]


def _http_json(url: str, ua: str = UA) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return 6371 * math.acos(max(-1.0, min(1.0, c)))


class Geo:
    def __init__(self, cfg: dict, *, fetch: Fetch | None = None, cache: Path | None = None):
        disc = (cfg.get("discover") or {}).get("distance") or {}
        self.provider = disc.get("geocoder", "nominatim")
        self.router = disc.get("router")             # e.g. an OSRM base URL; None = great-circle estimate
        self.road_factor = float((cfg.get("search") or {}).get("road_factor") or 1.3)
        self.home = ((cfg.get("owner") or {}).get("home") or {})
        ua = disc.get("user_agent") or UA
        self.fetch = fetch or (lambda u: _http_json(u, ua))
        self.cache_path = cache or _env.path("discover", "geocode.json")
        self.cache: dict[str, dict] = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self._last = 0.0

    def _save(self) -> None:
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False))
        tmp.replace(self.cache_path)

    def geocode(self, place: str, *, offline: bool = False) -> tuple[float, float] | None:
        key = place.strip().lower()
        if not key:
            return None
        if key in self.cache:
            return self.cache[key]["lat"], self.cache[key]["lon"]
        if offline or self.provider in (None, "none"):
            return None
        wait = self._last + MIN_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            res = self.fetch(f"{NOMINATIM}?format=json&limit=1&q={urllib.parse.quote(place)}")
        except Exception:  # noqa: BLE001 - geocoding is best effort
            return None
        if not res:
            return None
        lat, lon = float(res[0]["lat"]), float(res[0]["lon"])
        self.cache[key] = {"lat": lat, "lon": lon}
        self._save()
        return lat, lon

    def km(self, lat: float, lon: float) -> tuple[int | None, str]:
        """(km, how): how = road | estimate | none."""
        if self.home.get("lat") is None:
            return None, "none"
        hl, hn = float(self.home["lat"]), float(self.home["lon"])
        if self.router:
            try:
                r = self.fetch(f"{self.router.rstrip('/')}/route/v1/driving/{lon},{lat};{hn},{hl}?overview=false")
                return round(r["routes"][0]["distance"] / 1000), "road"
            except Exception:  # noqa: BLE001 - fall back to the estimate
                pass
        return round(great_circle_km(lat, lon, hl, hn) * self.road_factor), "estimate"


def place_of(city: str | None, country: str | None) -> str:
    return ", ".join(p for p in (city, country) if p)
