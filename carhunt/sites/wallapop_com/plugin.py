"""wallapop.com (ES): plain HTTP to the web app's public JSON API (api.wallapop.com/api/v3, CloudFront, no wall).
Search = keyword search, 40 rows/page, `next_page` token; ad = item page (→ hash id) + `items/<hash>` + `users/<id>`.

Two ids: the URL ends in a numeric legacy id (`site_ref`, liveness, cursors); the API wants the hash id, read from
the search row (cached per instance) or from the item page. Private sellers have no phone (chat only)."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from carhunt.sites.base import overrides, BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

_HASH = re.compile(r'"item":\{"id":"([a-z0-9]+)"')
_LEGACY = re.compile(r"-(\d{6,})$")


def _val(v: Any) -> Any:
    """Item attributes come as {"value": …}; search rows as plain values."""
    return v.get("value") if isinstance(v, dict) else v


def _orig(v: Any) -> Any:
    return v.get("original") if isinstance(v, dict) else v


def _iso_ms(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def _img(i: Any, size: str = "big") -> str | None:
    if isinstance(i, dict):
        return (i.get("urls") or {}).get(size)
    return i if isinstance(i, str) else None


class Plugin(BaseSite):
    pkg = "wallapop_com"

    def __init__(self, net: Any = None):
        super().__init__(net)
        self._hash: dict[str, str] = {}     # legacy id → API hash id, filled by search

    def _api_headers(self) -> dict[str, str]:
        web = self.codes["web"]
        return {"X-DeviceOS": "0", "Origin": web, "Referer": web + "/"}

    # --- search ------------------------------------------------------------
    def geo(self) -> dict:
        return overrides(self.id).get("geo") or self.codes["geo"]

    def search_url(self, q: SearchQuery, next_page: str | None = None) -> str:
        api = self.codes["api"]
        if next_page:   # the token carries the whole query
            return f"{api}/search?{urllib.parse.urlencode({'next_page': next_page})}"
        if (q.country or "ES").upper() != "ES":
            raise Unsupported(f"{self.id}: Spain only (country {q.country})")
        text = self.code("keywords", q.make, q.model, slug=False) or " ".join(x for x in (q.make, q.model) if x)
        p: dict[str, str] = {"category_id": str(self.codes["category"])}
        if text:
            p["keywords"] = text
        # results are distance-sorted from this point; config sites.overrides["wallapop.com"].geo wins
        p.update({k: str(v) for k, v in self.geo().items()})
        p["order_by"] = self.codes["sort"][q.sort]
        p["source"] = "search_box"
        if q.seller != "any":
            p["seller_type"] = self.need_code("seller", q.seller)
        for key, v in (("min_year", q.year_min), ("max_km", q.km_max), ("min_sale_price", q.price_min),
                       ("max_sale_price", q.price_max)):
            if v:
                p[key] = str(v)
        p.update(q.extra)
        return f"{api}/search?{urllib.parse.urlencode(p)}"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        token: str | None = None
        for _ in range(max(q.max_pages, 1)):
            url = self.search_url(q, token)
            d = self.net.json(url, headers=self._api_headers())
            try:
                rows = d["data"]["section"]["payload"]["items"]
            except (KeyError, TypeError):
                raise Blocked("no-items", site=self.id, url=url) from None
            for it in rows:
                c = self.card(it, q.seller)
                if c:
                    yield c
            token = (d.get("meta") or {}).get("next_page")
            if not token:
                break

    def card(self, it: dict, seller: str = "any") -> Card | None:
        m = _LEGACY.search(str(it.get("web_slug") or ""))
        if not m:
            return None
        legacy = m.group(1)
        if it.get("id"):
            self._hash[legacy] = str(it["id"])
        ta, loc = it.get("type_attributes") or {}, it.get("location") or {}
        year = num(ta.get("year"))
        imgs = it.get("images") or []
        return Card(url=f"{self.codes['web']}/item/{it['web_slug']}", site=self.id, site_ref=legacy,
                    title=it.get("title"), price=num((it.get("price") or {}).get("amount")), km=num(ta.get("km")),
                    year=year, first_registration=str(year) if year else None, make=ta.get("brand"),
                    model=ta.get("model"), version=ta.get("version"), fuel=ta.get("engine"),
                    seller_type={"private": "private", "dealer": "dealer"}.get(seller, "unknown"),
                    location=" ".join(x for x in (loc.get("postal_code"), loc.get("city")) if x) or None,
                    country=loc.get("country_code") or "ES",
                    thumb=_img(imgs[0], "medium") if imgs else None,
                    # bumped rows (paid "city"/"country" bumps) can be older than the whole page: never a cursor
                    sponsored=(it.get("bump") or {}).get("type") not in (None, "", "none"),
                    created=_iso_ms(it.get("created_at")))

    # --- ad ----------------------------------------------------------------
    def hash_id(self, url: str) -> str:
        """API hash id of an item URL: from a search row seen by this instance, else one item-page load."""
        aid = self.ad_id(url)
        if not aid:
            raise Unsupported(f"{self.id}: not an item URL: {url}")
        if aid in self._hash:
            return self._hash[aid]
        m = _HASH.search(self.net.get(url, ad_id=aid).text)
        if not m:
            raise Blocked("no-item-id", site=self.id, url=url)
        self._hash[aid] = m.group(1)
        return m.group(1)

    def ad(self, url: str) -> RawAd:
        api, h = self.codes["api"], self._api_headers()
        d = self.net.json(f"{api}/items/{self.hash_id(url)}", headers=h)
        if not isinstance(d, dict) or not d.get("title"):
            raise Blocked("no-item", site=self.id, url=url)
        user = None
        uid = (d.get("user") or {}).get("id")
        if uid:
            try:
                user = self.net.json(f"{api}/users/{uid}", headers=h)
            except Gone:     # seller profile removed: the item is still readable
                user = None
        return self.parse_ad(url, d, user)

    def parse_ad(self, url: str, d: dict, user: dict | None = None) -> RawAd:
        ta = {k: _val(v) for k, v in (d.get("type_attributes") or {}).items()}
        loc, u = d.get("location") or {}, user or {}
        x = u.get("extra_info") or {}
        price = d.get("price") or {}
        price = (price.get("cash") or price).get("amount") if isinstance(price, dict) else price
        year = num(ta.get("year"))
        engine = ta.get("engine")
        st = u.get("seller_type")
        st = str((st.get("type") if isinstance(st, dict) else st) or "").lower()
        utype = str(u.get("type") or "").lower()
        seller_type = ("dealer" if "professional" in (utype, st) or x.get("phone_number")
                       else "private" if utype == "normal" or st == "private" else "unknown")
        flags = d.get("flags") or {}
        ulocc = u.get("location") or {}
        return RawAd(
            url=url, site=self.id, site_ref=self.ad_id(url) or str(d.get("id")), title=_orig(d.get("title")),
            price=num(price), make=ta.get("brand"), model=ta.get("model"), version=ta.get("version"), year=year,
            first_registration=str(year) if year else None, km=num(ta.get("km")),
            fuel=self.code("engine", engine, slug=False) or engine if engine else None,
            power_hp=num(ta.get("horse_power") or ta.get("horsepower")),   # "299.0" = decimal (num handles it)
            gearbox=ta.get("gear_box") or ta.get("gearbox"), body=ta.get("body_type"), color=ta.get("color"),
            seats=num(ta.get("seats")), doors=num(ta.get("doors")), description=_orig(d.get("description")),
            photos=[p for p in (_img(i) for i in d.get("images") or []) if p],
            phones=[str(x["phone_number"])] if x.get("phone_number") else [],
            seller=Seller(type=seller_type, name=u.get("micro_name"), id=u.get("id") or (d.get("user") or {}).get("id"),
                          city=ulocc.get("city"), url=u.get("url_share")),
            location=" ".join(str(v) for v in (loc.get("postal_code"), loc.get("city")) if v) or None,
            country=loc.get("country_code") or "ES",
            # status is informational: a sold flag in API JSON is never a liveness verdict (is_live decides)
            status="sold" if flags.get("sold") else "reserved" if flags.get("reserved") else None,
            contact={"chat": True, "phone": bool(x.get("phone_number"))},
            extra={"engine": engine, "hash_id": d.get("id"), "share_url": d.get("share_url"),
                   "eco_label": ta.get("eco_label"), "address": x.get("address"), "website": x.get("link"),
                   "counters": d.get("counters")},
            raw={"item": d, "user": user})
