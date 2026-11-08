"""Offline fixtures: temp CARHUNT_HOME, a synthetic config, a stub cardb, scripted fake sites."""
from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from carhunt.sites.base import Blocked, Gone
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

CONFIG = {
    "owner": {"name": "owner", "tz": "Europe/Lisbon", "home": {"city": "Testville", "country": "PT", "lat": 41.0,
                                                                "lon": -8.0}},
    "search": {
        "countries": ["PT", "ES", "DE", "FR", "IT", "NL", "BE"],
        "private_sellers_abroad": True,
        "exclude_regions": ["PT-20", "PT-30", "ES-CN"],
        "price": {"max_eur": 42000},
        "year_min": 2021,
        "km_max": 80000,
        "powertrain": ["bev"],
        "models": [{"make": "Volkswagen", "model": "ID.4", "tier": 1}, {"make": "Skoda", "model": "Enyaq", "tier": 1},
                   {"make": "Audi", "model": "Q4 e-tron", "tier": 2}],
        "hard_filters": [{"fact": "battery_net_kwh", "min": 70}, {"flag": "damaged", "exclude": True}],
        "options_wanted": {"heat_pump": 3, "pano": 2},
    },
    "sites": {"enabled": ["fake"]},
    "discover": {"distance": {"geocoder": "none"}, "max_loads_per_site": 60},
}


class NotFound(Exception):
    status = 404


class ApiError(Exception):
    def __init__(self, msg: str, status: int, body: Any = None):
        super().__init__(msg)
        self.status, self.body = status, body


class StubDB:
    """In-memory cardb: listings by URL, cars by id, every call recorded in order."""

    def __init__(self, reject: dict[str, str] | None = None, steal_phones: set[str] | None = None):
        self.calls: list[tuple[str, Any]] = []
        self.listings: dict[str, dict] = {}
        self.cars: dict[int, dict] = {}
        self.photos: list[tuple[int, str, int]] = []
        self.facts: list[tuple[int, str, Any]] = []
        self.reject = reject or {}
        self.steal = steal_phones or set()
        self._ids = itertools.count(1)

    def find_listing(self, url: str) -> dict:
        self.calls.append(("find", url))
        if url not in self.listings:
            raise NotFound(url)
        return dict(self.listings[url])

    def upsert_listing(self, body: dict) -> dict:
        self.calls.append(("upsert", body))
        why = self.reject.get(body["url"])
        if why == "bad_field":
            raise ApiError("field", 400, {"error": "unknown fuel"})
        if why and body.get("price") is not None:   # like cardb: only a price write is sanity-checked
            raise ApiError("price", 422, {"error": "price looks wrong", "reason": why})
        if "photo_urls" in body:
            raise AssertionError("photos must not be sent with the upsert")
        url = body["url"]
        if url in self.listings:
            lst = self.listings[url]
            changed = body.get("price") is not None and body["price"] != lst["price"]
            lst.update(price=body.get("price", lst["price"]), status="live")
            return {"car_id": lst["car_id"], "listing_id": lst["id"], "listing_created": False,
                    "car_created": False, "price_changed": changed}
        car_id = next(self._ids)
        contacts = [c for c in (body.get("seller") or {}).get("contacts", []) if c["value"] not in self.steal]
        self.cars[car_id] = {"id": car_id, "seller": {"contacts": contacts}, "body": body}
        lid = 100 + car_id
        self.listings[url] = {"id": lid, "car_id": car_id, "url": url, "price": body.get("price"), "status": "live"}
        return {"car_id": car_id, "listing_id": lid, "listing_created": True, "car_created": True}

    def photo_add(self, car: int, *, url: str, source: str | None = None, listing: int | None = None, **_: Any):
        self.calls.append(("photo", url))
        self.photos.append((car, url, listing))
        return {"id": len(self.photos)}

    def car(self, car: int) -> dict:
        self.calls.append(("car", car))
        return self.cars[car]

    def fact(self, car: int, key: str, value: Any, *, source: str | None = None) -> None:
        self.calls.append(("fact", (car, key)))
        self.facts.append((car, key, value))

    def writes(self) -> list:
        return [c for c in self.calls if c[0] in ("upsert", "photo", "fact")]


def ad_dict(ref: str, **kw: Any) -> dict:
    """A synthetic ad: in scope for CONFIG unless overridden."""
    base = {"site_ref": ref, "make": "Volkswagen", "model": "ID.4", "title": "Volkswagen ID.4 Pro 77 kWh 150 kW",
            "version": "Pro", "price": 30000, "km": 30000, "first_registration": "2022-06", "fuel": "bev",
            "country": "PT", "location": "Testville", "seller": {"type": "dealer", "city": "Testville"},
            "photos": [f"https://img.example.invalid/{ref}-{i}.jpg" for i in range(10)],
            "phones": ["+351 555 000 0" + ref[-2:]], "description": "Synthetic ad. Bomba de calor.",
            "created": "2026-11-07T10:00:00+00:00"}
    base.update(kw)
    return base


class ScriptedSite:
    """A site plugin double: cards from dicts, ads from the same dicts; per-call scripted Blocked/Gone."""

    def __init__(self, sid: str, ads: list[dict], *, block_on_ad: str | None = None, gone: set[str] | None = None,
                 block_search: bool = False, sponsored: set[str] | None = None, pages: int = 1):
        self.id = sid
        self.meta = {"site": sid, "countries": ["PT"]}
        self.ads = ads
        self.block_on_ad, self.gone, self.block_search = block_on_ad, gone or set(), block_search
        self.sponsored = sponsored or set()

        class _Net:
            loads = 0

        self.net = _Net()
        self.closed = False
        self.queries: list[SearchQuery] = []
        self.ad_calls = 0

    def url(self, ref: str) -> str:
        return f"https://{self.id}.example.invalid/ad/{ref}"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        self.queries.append(q)
        self.net.loads += 1
        if self.block_search:
            raise Blocked("test-wall", site=self.id)
        for a in self.ads:
            if q.model and a["model"] != q.model:
                continue
            yield Card(url=self.url(a["site_ref"]), site=self.id, site_ref=a["site_ref"], title=a["title"],
                       price=a["price"], km=a["km"], first_registration=a["first_registration"], make=a["make"],
                       model=a["model"], country=a["country"], seller_type=a["seller"]["type"],
                       location=a["location"], created=a.get("created"), sponsored=a["site_ref"] in self.sponsored)

    def ad(self, url: str) -> RawAd:
        self.net.loads += 1
        self.ad_calls += 1
        ref = url.rsplit("/", 1)[1]
        if ref == self.block_on_ad:
            raise Blocked("test-wall", site=self.id, url=url)
        if ref in self.gone:
            raise Gone(url, "http-410")
        a = next(x for x in self.ads if x["site_ref"] == ref)
        fields = {k: a.get(k) for k in ("title", "price", "make", "model", "version", "km", "fuel", "country",
                                        "location", "description", "first_registration", "vin", "power_kw",
                                        "battery_kwh", "drive", "price_is_net")}
        return RawAd(url=url, site=self.id, site_ref=ref, photos=a["photos"], phones=a["phones"],
                     seller=Seller(**a["seller"]), equipment=a.get("equipment", []), **fields)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "carhunt"
    home.mkdir()
    monkeypatch.setenv("CARHUNT_HOME", str(home))
    monkeypatch.delenv("CARHUNT_CONFIG", raising=False)
    monkeypatch.delenv("CARHUNT_FAKE_SITES_BLOCK", raising=False)
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T15:00:00")
    return home


@pytest.fixture
def cfg(_home) -> dict:
    import copy
    c = copy.deepcopy(CONFIG)
    (_home / "config.yaml").write_text(yaml.safe_dump(c))
    return c


@pytest.fixture
def db() -> StubDB:
    return StubDB()
