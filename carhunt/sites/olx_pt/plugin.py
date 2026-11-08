"""OLX.pt (category Carros): CloudFront WAF 403s every plain HTTP client, so all reads are the site's own JSON API
(`/api/v1/offers/`) fetched from inside one plain-chrome tab on www.olx.pt. A search row is already the full offer
(description, params, gallery): `ad()` serves rows seen in this session's searches without another request."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Iterator
from typing import Any

from carhunt.sites._net import Response, raise_for
from carhunt.sites.base import BaseSite, Blocked, Unsupported
from carhunt.sites.extract import num
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

ORIGIN = "https://www.olx.pt"
API = ORIGIN + "/api/v1/offers/"
CV_TO_KW = 0.7355
_SKU = (re.compile(r'"sku"\s*:\s*"(\d+)"'), re.compile(r"ID:\s*(\d{6,})"))


def params(o: dict) -> dict[str, dict]:
    return {p.get("key"): (p.get("value") or {}) for p in o.get("params") or []}


def photo_url(link: str) -> str:
    """Gallery link template `…/image;s={width}x{height}` → the original image."""
    return re.sub(r";s=\{width\}x\{height\}", "", link)


def _kw(hp: int | None) -> int | None:
    return round(hp * CV_TO_KW) if hp else None


def _reg(p: dict) -> tuple[int | None, str | None]:
    year = num((p.get("year") or {}).get("key"))
    month = num((p.get("first_registration_month") or {}).get("key"))
    return year, (f"{year}-{month:02d}" if year and month else (str(year) if year else None))


def _text(p: dict, key: str) -> str | None:
    v = p.get(key) or {}
    s = str(v.get("label") or v.get("key") or "").strip()
    return s or None


class Plugin(BaseSite):
    pkg = "olx_pt"

    def __init__(self, net: Any = None):
        super().__init__(net)
        self._offers: dict[str, dict] = {}     # numeric id → offer (search rows = full offers)
        self._ids: dict[str, str] = {}         # ad URL → numeric id

    # --- transport -----------------------------------------------------------
    def api(self, url: str) -> Any:
        """One API read in the tab. A stray 400/404 right after a fresh tab was seen once: retry once, then it is a
        block (an API 404 is never "ad gone")."""
        r: Response = self.net.browser_get(url, mode="fetch", check=False)
        if r.status in (400, 404):
            r = self.net.browser_get(url, mode="fetch", check=False)
            if r.status in (400, 404):
                raise Blocked(f"http-{r.status}", site=self.id, url=url, detail=r.text[:120])
        raise_for(self.id, r)
        try:
            return r.json()
        except json.JSONDecodeError:
            raise Blocked("non-json", site=self.id, url=url) from None

    # --- search ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        limit = int(self.codes.get("limit", 40))
        p: dict[str, str] = {"offset": str((page - 1) * limit), "limit": str(limit),
                             "category_id": str(self.codes["category"])}
        if q.make or q.model:
            p["query"] = (self.code("queries", q.make, q.model, slug=False) if q.make and q.model else None) \
                or " ".join(x for x in (q.make, q.model) if x)
        for f in ("year_min", "year_max", "price_min", "price_max", "km_max"):
            if getattr(q, f):
                p[self.need_code("filters", f)] = str(getattr(q, f))
        if q.seller == "private":
            p["owner_type"] = self.need_code("owner_type", "private")
        p.update(q.extra)
        return f"{API}?{urllib.parse.urlencode(p)}"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        """Sort is not honoured: the API ignores sort_by — discover keeps a numeric id cursor instead."""
        fuel_key = self.code("fuel", q.fuel, slug=False) if q.fuel else None
        if q.fuel and not fuel_key:
            raise Unsupported(f"{self.id}: no combustivel key for fuel {q.fuel!r} (codes.yaml fuel)")
        for page in range(1, max(q.max_pages, 1) + 1):
            d = self.api(self.search_url(q, page))
            rows = d.get("data") or []
            promoted = set((d.get("metadata") or {}).get("promoted") or [])
            for i, o in enumerate(rows):
                self._remember(o)
                p = params(o)
                if fuel_key and (p.get("combustivel") or {}).get("key") != fuel_key:
                    continue
                if q.seller == "dealer" and not o.get("business"):
                    continue
                yield self.card(o, sponsored=i in promoted)
            if not rows or not (d.get("links") or {}).get("next"):
                break

    def _remember(self, o: dict) -> None:
        if o.get("id"):
            self._offers[str(o["id"])] = o
            if o.get("url"):
                self._ids[o["url"]] = str(o["id"])

    def card(self, o: dict, *, sponsored: bool = False) -> Card:
        p = params(o)
        year, reg = _reg(p)
        loc = o.get("location") or {}
        photos = o.get("photos") or []
        return Card(url=o["url"], site=self.id, site_ref=str(o["id"]), title=o.get("title"),
                    price=num((p.get("price") or {}).get("value")), km=num((p.get("quilometros") or {}).get("key")),
                    year=year, first_registration=reg, model=_text(p, "modelo"),
                    fuel=(p.get("combustivel") or {}).get("key"),
                    power_kw=_kw(num((p.get("engine_power") or {}).get("key"))),
                    seller_type="dealer" if o.get("business") else "private",
                    location=", ".join(x for x in ((loc.get("city") or {}).get("name"),
                                                   (loc.get("region") or {}).get("name")) if x) or None,
                    country="PT", thumb=photo_url(photos[0]["link"]) if photos and photos[0].get("link") else None,
                    sponsored=sponsored, created=o.get("created_time"))

    # --- ad ----------------------------------------------------------------
    def offer_id(self, url: str) -> str:
        """Numeric offer id for an ad URL: from this session's searches, else from the ad page (`"sku"`)."""
        if url in self._ids:
            return self._ids[url]
        if re.fullmatch(r"\d+", url):
            return url
        r = self.net.browser_get(url, mode="fetch", ad_id=self.ad_id(url))   # 404/410 → Gone, 403 → Blocked
        for rx in _SKU:
            m = rx.search(r.text)
            if m:
                self._ids[url] = m.group(1)
                return m.group(1)
        raise Blocked("no-offer-id", site=self.id, url=url)

    def ad(self, url: str) -> RawAd:
        oid = self.offer_id(url)
        o = self._offers.get(oid)
        if o is None:
            o = (self.api(f"{API}{oid}/") or {}).get("data")
            if not o:
                raise Blocked("no-offer", site=self.id, url=url)
            self._remember(o)
        return self.parse_ad(o)

    def parse_ad(self, o: dict) -> RawAd:
        p = params(o)
        year, reg = _reg(p)
        hp = num((p.get("engine_power") or {}).get("key"))
        price = p.get("price") or {}
        loc = o.get("location") or {}
        city, region = (loc.get("city") or {}).get("name"), (loc.get("region") or {}).get("name")
        user, contact, partner = o.get("user") or {}, o.get("contact") or {}, o.get("partner") or {}
        stype = "dealer" if o.get("business") else "private"
        return RawAd(
            url=o["url"], site=self.id, site_ref=str(o["id"]), title=o.get("title"), price=num(price.get("value")),
            currency=price.get("currency") or "EUR", model=_text(p, "modelo"), year=year, first_registration=reg,
            km=num((p.get("quilometros") or {}).get("key")), fuel=(p.get("combustivel") or {}).get("key"),
            power_kw=_kw(hp), power_hp=hp, gearbox=(p.get("gearbox") or {}).get("key"),
            body=(p.get("body_type") or {}).get("key"), seats=num((p.get("nr_seats") or {}).get("key")),
            vin=_text(p, "vin"), plate=_text(p, "matricula"),
            description=re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", o.get("description") or "")).strip() or None,
            photos=[photo_url(x["link"]) for x in o.get("photos") or [] if x.get("link")],
            seller=Seller(type=stype, name=user.get("company_name") or user.get("name"),
                          id=str(user["id"]) if user.get("id") else None, city=city, region=region, country="PT"),
            location=", ".join(x for x in (city, region) if x) or None, country="PT", created=o.get("created_time"),
            status=o.get("status"), contact={"chat": bool(contact.get("chat")), "phone": bool(contact.get("phone"))},
            extra={"url_id": self.ad_id(o["url"]), "negotiable": price.get("negotiable"),
                   "condition": (p.get("condicao") or {}).get("key"), "origin": (p.get("origin") or {}).get("key"),
                   "doors": (p.get("portas") or {}).get("key"),
                   # cross-post of a Standvirtual ad: read the phone there (decoded offline, no login)
                   "mirror_of": o.get("external_url") if partner.get("code") else None,
                   "mirror_site": partner.get("code")},
            raw={"offer": o})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        if ad.phones or not reveal or not ad.contact.get("phone"):
            return list(ad.phones)        # contact.phone false = chat only, no number exists
        raise Unsupported(f"{self.id}: phone reveal (/api/v1/offers/<id>/limited-phones/) needs a logged-in Bearer "
                          "token (logged out → 400 'Disallowed for this user'); login lives in browsers/contact")
