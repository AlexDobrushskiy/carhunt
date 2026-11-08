"""Synthetic site: bundled fixture ads, no network. For discover/integrator e2e tests.

Env knobs: CARHUNT_FAKE_SITES_FIXTURES = path to an ads.json of the same shape (default: bundled);
CARHUNT_FAKE_SITES_BLOCK = comma list of actions (search, ad, live) that raise Blocked, to test stop-at-first-block.
Fixture `state`: live | removed (404) | soft (redirect to a list page) | blocked.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from carhunt.sites.base import BaseSite, Blocked, Gone
from carhunt.sites.extract import year_of
from carhunt.sites.model import Card, Liveness, RawAd, SearchQuery, Seller

BASE = "https://fake.example.invalid"


class _NoNet:
    def close(self) -> None:
        pass


class Plugin(BaseSite):
    pkg = "fake"

    def __init__(self, net=None):
        super().__init__(net=net or _NoNet())

    def _ads(self) -> list[dict]:
        p = os.environ.get("CARHUNT_FAKE_SITES_FIXTURES") or Path(__file__).parent / "fixtures" / "ads.json"
        return json.loads(Path(p).read_text(encoding="utf-8"))

    def _block(self, action: str) -> None:
        if action in (os.environ.get("CARHUNT_FAKE_SITES_BLOCK") or "").split(","):
            raise Blocked("fake-wall", site=self.id)

    @staticmethod
    def url(ref: str) -> str:
        return f"{BASE}/ad/{ref}"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        self._block("search")
        for a in self._ads():
            if a.get("state") == "removed":
                continue
            yr = year_of(a.get("first_registration"))
            if q.make and (a.get("make") or "").lower() != q.make.lower():
                continue
            if q.model and (a.get("model") or "").lower() != q.model.lower():
                continue
            if q.country and a.get("country") != q.country:
                continue
            if q.price_max and (a.get("price") or 0) > q.price_max:
                continue
            if q.price_min and (a.get("price") or 0) < q.price_min:
                continue
            if q.year_min and yr and yr < q.year_min:
                continue
            if q.km_max and (a.get("km") or 0) > q.km_max:
                continue
            st = (a.get("seller") or {}).get("type", "unknown")
            if q.seller != "any" and st != q.seller:
                continue
            yield Card(url=self.url(a["site_ref"]), site=self.id, site_ref=a["site_ref"], title=a.get("title"),
                       price=a.get("price"), price_is_net=a.get("price_is_net"), km=a.get("km"), year=yr,
                       first_registration=a.get("first_registration"), make=a.get("make"), model=a.get("model"),
                       version=a.get("version"), fuel=a.get("fuel"), power_kw=a.get("power_kw"), seller_type=st,
                       location=a.get("location"), country=a.get("country"),
                       thumb=(a.get("photos") or [None])[0], created=a.get("created"))

    def _find(self, url: str) -> dict:
        ref = self.ad_id(url)
        for a in self._ads():
            if a["site_ref"] == ref:
                return a
        raise Gone(url, "http-404")

    def ad(self, url: str) -> RawAd:
        self._block("ad")
        a = self._find(url)
        if a.get("state") == "removed":
            raise Gone(url, "http-404")
        if a.get("state") == "blocked":
            raise Blocked("fake-wall", site=self.id, url=url)
        s = a.get("seller") or {}
        fields = {k: a.get(k) for k in ("title", "price", "price_is_net", "make", "model", "version", "km", "fuel",
                                        "power_kw", "drive", "battery_kwh", "vin", "description", "location",
                                        "country", "created", "first_registration")}
        return RawAd(url=url, site=self.id, site_ref=a["site_ref"], year=year_of(a.get("first_registration")),
                     equipment=a.get("equipment") or [], photos=a.get("photos") or [], phones=a.get("phones") or [],
                     seller=Seller(**{k: v for k, v in s.items() if k in Seller.__dataclass_fields__}),
                     raw=a, **fields)

    def is_live(self, url: str) -> Liveness:
        self._block("live")
        try:
            a = self._find(url)
        except Gone:
            return Liveness("removed", "404")
        st = a.get("state", "live")
        if st == "removed":
            return Liveness("removed", "404")
        if st == "soft":
            return Liveness("removed", f"redirect to {BASE}/list", soft=True)
        if st == "blocked":
            raise Blocked("fake-wall", site=self.id, url=url)
        return Liveness("live", "200")
