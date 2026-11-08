"""Standvirtual (PT): plain HTTP, all data in the Next.js `__NEXT_DATA__` (list: urqlState `advertSearch`, ad:
`advert`), 32 rows per page. Phones and VIN are in the ad page encrypted with the site's own client cipher and
decoded offline here (`cipher.py`): the same as the "Ver telefone" button, no login, no reveal request."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Iterator
from datetime import date
from typing import Any

from carhunt.sites.base import BaseSite, Blocked, Unsupported
from carhunt.sites.extract import num, page_props
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller
from carhunt.sites.standvirtual_com import cipher

ORIGIN = "https://www.standvirtual.com"
CV_TO_KW = 0.7355
MAX_SCRIPTS = 60    # bundles scanned for the salt before giving up (one-time, then cached)
SELLER = {"PROFESSIONAL": "dealer", "STAND": "dealer", "ProfessionalSeller": "dealer",
          "PRIVATE": "private", "PrivateSeller": "private"}


def advert_search(pp: dict) -> dict | None:
    """The `advertSearch` result inside urqlState (values are JSON strings keyed by query hash)."""
    for v in (pp.get("urqlState") or {}).values():
        try:
            d = json.loads((v or {}).get("data") or "{}")
        except json.JSONDecodeError:
            continue
        if "advertSearch" in d:
            return d["advertSearch"]
    return None


def _pd(advert: dict, key: str, field: str = "value") -> str | None:
    vals = ((advert.get("parametersDict") or {}).get(key) or {}).get("values") or []
    return vals[0].get(field) if vals else None


def _kw(hp: int | None) -> int | None:
    return round(hp * CV_TO_KW) if hp else None


def _strip_html(s: str | None) -> str | None:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip() if s else None


def tokens(advert: dict) -> tuple[list[str], str | None]:
    """(phone tokens, VIN token) as the page carries them."""
    vin = _pd(advert, "vin")
    return [t for t in advert.get("phoneNumbers") or [] if t], vin


def phone_keys(advert: dict) -> list[str]:
    s = advert.get("seller") or {}
    return [str(k) for k in (s.get("uuid"), s.get("standId")) if k]   # dealer stands key on standId


def decode_fields(advert: dict, salt: str | None) -> tuple[list[str], str | None, dict[str, Any]]:
    """Decoded (phones, vin, notes). Undecodable fields are left out and named in notes (never a raw token)."""
    ph_tokens, vin_token = tokens(advert)
    phones: list[str] = []
    notes: dict[str, Any] = {}
    plain = [t for t in ph_tokens if not cipher.is_token(t)]
    phones += plain                                      # not encrypted: as is
    enc = [t for t in ph_tokens if cipher.is_token(t)]
    vin = vin_token if vin_token and not cipher.is_token(vin_token) else None
    if (enc or (vin_token and vin is None)) and not salt:
        notes["decode"] = "site salt not found: phones/VIN left encrypted"
        if enc:
            notes["phones_undecoded"] = len(enc)
        if vin_token and vin is None:
            notes["vin_undecoded"] = True
        return phones, vin, notes
    keys = phone_keys(advert)
    bad = 0
    for t in enc:
        p = cipher.decode(t, keys, salt or "")
        if p:
            phones.append(p)
        else:
            bad += 1
    if bad:
        notes["phones_undecoded"] = bad
        notes["decode"] = "token did not authenticate under seller uuid/standId: scheme or salt changed?"
    if vin_token and vin is None:
        vin = cipher.decode(vin_token, [str(advert.get("id") or "")], salt or "")
        if vin is None:
            notes["vin_undecoded"] = True
            notes.setdefault("decode", "VIN token did not authenticate under the advert id")
    return phones, vin, notes


class Plugin(BaseSite):
    pkg = "standvirtual_com"

    def __init__(self, net: Any = None, *, salt: str | None = None):
        super().__init__(net)
        self._salt = salt      # explicit override (config); else cached/discovered

    # --- search ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        path = "/carros"
        if q.make:
            path += "/" + self.code("makes", q.make)
            if q.model:
                path += "/" + self.code("models", q.make, q.model)
        p: dict[str, str] = {}
        for f in ("year_min", "year_max", "price_min", "price_max", "km_max"):
            if getattr(q, f):
                p[self.need_code("filters", f)] = str(getattr(q, f))
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p[self.need_code("params", "fuel")] = self.code("fuel", q.fuel, slug=False)
        if q.seller != "any":
            p[self.need_code("params", "seller")] = self.need_code("seller", q.seller)
        order = self.code("sort", q.sort, slug=False)
        if order is None:
            raise Unsupported(f"{self.id}: sort {q.sort!r} not measured (codes.yaml sort)")
        if order:
            p[self.need_code("params", "sort")] = order
        if page > 1:
            p["page"] = str(page)
        p.update(q.extra)
        return f"{ORIGIN}{path}" + (f"?{urllib.parse.urlencode(p)}" if p else "")

    def _props(self, url: str, ad_id: str | None = None) -> tuple[dict, str]:
        r = self.net.get(url, ad_id=ad_id)
        pp = page_props(r.text)
        if pp is None:
            raise Blocked("no-next-data", site=self.id, url=url)
        return pp, r.text

    def search(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            res = advert_search(self._props(url)[0])
            if res is None:
                raise Blocked("no-advertSearch", site=self.id, url=url)
            edges = res.get("edges") or []
            for e in edges:
                yield self.card(e)
            size = (res.get("pageInfo") or {}).get("pageSize") or 32
            if not edges or page * size >= (res.get("totalCount") or 0):
                break

    def card(self, edge: dict) -> Card:
        n, vas = edge.get("node") or {}, edge.get("vas") or {}
        par = {p.get("key"): p for p in n.get("parameters") or []}
        val = lambda k: (par.get(k) or {}).get("value")   # noqa: E731
        shown = lambda k: (par.get(k) or {}).get("displayValue")   # noqa: E731
        price = n.get("price") or {}
        loc = n.get("location") or {}
        city, region = ((loc.get("city") or {}).get("name"), (loc.get("region") or {}).get("name"))
        year = num(val("first_registration_year"))
        hp = num(val("engine_power"))
        return Card(url=n["url"], site=self.id, site_ref=str(n["id"]), title=n.get("title"),
                    price=num((price.get("amount") or {}).get("value")),
                    price_is_net=(not price["isGross"]) if isinstance(price.get("isGross"), bool) else None,
                    km=num(val("mileage")), year=year, first_registration=str(year) if year else None,
                    make=shown("make"), model=shown("model"), version=shown("version"), fuel=val("fuel_type"),
                    power_kw=_kw(hp), seller_type=SELLER.get((n.get("seller") or {}).get("__typename"), "unknown"),
                    location=", ".join(x for x in (city, region) if x) or None, country="PT",
                    thumb=(n.get("thumbnail") or {}).get("x1"),
                    sponsored=bool(vas.get("isPromoted") or n.get("isPremiumTopAd")), created=n.get("createdAt"))

    # --- ad ----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        pp, html = self._props(url, ad_id=self.ad_id(url))
        advert = pp.get("advert")
        if not advert:
            raise Blocked("no-advert", site=self.id, url=url)
        return self.parse_ad(url, advert, self.salt(advert, html))

    def parse_ad(self, url: str, a: dict, salt: str | None = None) -> RawAd:
        s = a.get("seller") or {}
        loc = s.get("location") or {}
        year, month = num(_pd(a, "first_registration_year")), num(_pd(a, "first_registration_month"))
        hp = num(_pd(a, "engine_power"))
        price = a.get("price") or {}
        net = (a.get("advertPriceForPriceDrop") or {}).get("isNet")
        phones, vin, notes = decode_fields(a, salt)
        book = _pd(a, "complete_review_book")   # "1"/"0" (labels Sim/Não)
        bat = _pd(a, "battery_capacity")
        health = ((a.get("electricVehicleBatteryEstimation") or {}).get("health") or {})
        return RawAd(
            url=a.get("url") or url, site=self.id, site_ref=str(a.get("id") or ""), title=a.get("title"),
            price=num(price.get("value")), price_is_net=net if isinstance(net, bool) else None,
            currency=price.get("currency") or "EUR", make=_pd(a, "make", "label"), model=_pd(a, "model", "label"),
            version=_pd(a, "version_label") or _pd(a, "version", "label"), year=year,
            first_registration=(f"{year}-{month:02d}" if year and month else (str(year) if year else None)),
            km=num(_pd(a, "mileage")), fuel=_pd(a, "fuel_type"), power_kw=_kw(hp), power_hp=hp,
            drive=_pd(a, "transmission"), gearbox=_pd(a, "gearbox"), body=_pd(a, "body_type"), color=_pd(a, "color"),
            seats=num(_pd(a, "nr_seats")), doors=num(_pd(a, "door_count")),
            owners=num(_pd(a, "number_of_registrations")) or None,
            service_history={"1": True, "sim": True, "0": False, "não": False}.get(str(book).lower()),
            battery_kwh=float(bat) if bat and re.fullmatch(r"\d+(\.\d+)?", bat) else None, vin=vin,
            description=_strip_html(a.get("description")),
            equipment=[v.get("key") for g in a.get("equipment") or [] for v in g.get("values") or [] if v.get("key")],
            photos=[p["url"] for p in (a.get("images") or {}).get("photos") or [] if p.get("url")], phones=phones,
            seller=Seller(type=SELLER.get(s.get("type"), "unknown"), name=s.get("name"),
                          id=str(s["id"]) if s.get("id") else None, city=loc.get("city"),
                          postcode=loc.get("postalCode"), region=loc.get("region"), country="PT",
                          url=s.get("sellerUrl") or s.get("website")),
            location=" ".join(x for x in (loc.get("postalCode"), loc.get("city")) if x) or None, country="PT",
            created=a.get("createdAt"), status=a.get("status"),
            extra={"url_id": self.ad_id(url), "price_labels": [str(x) for x in price.get("labels") or []],
                   "seller_active_ads": s.get("numberOfActiveAds"), "origin": _pd(a, "origin"),
                   "warranty_months": num(_pd(a, "vendors_warranty_valid_until_date")),
                   "battery_health_pct": health.get("averagePct"), **notes},
            raw={"advert": a})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        """Decoded from the ad page's own data (offline; `reveal` changes nothing: there is no reveal call)."""
        if ad.phones:
            return list(ad.phones)
        a = (ad.raw or {}).get("advert")
        if not a or not tokens(a)[0]:
            return []
        salt = self.salt(a, None)
        if salt is None:      # nothing cached: the ad page lists the bundles to search
            return list(self.ad(ad.url).phones)
        return decode_fields(a, salt)[0]

    # --- site salt -----------------------------------------------------------
    def salt(self, advert: dict, html: str | None) -> str | None:
        """The site's client salt, proven on this advert's own token: override → cache → the page's JS bundles.
        None when the advert has nothing encrypted or no bundle yields a salt that authenticates."""
        probe = self._probe(advert)
        if probe is None:
            return None
        cache = self._cache_path()
        cached = None
        try:
            cached = json.loads(cache.read_text()).get("salt") if cache.exists() else None
        except (OSError, ValueError):
            pass
        known = (self.codes.get("cipher") or {}).get("salt")   # the site's public client constant, last seen
        for s in (self._salt, cached, known):
            if s and self._proves(s, probe):
                self._salt = s
                return s
        if html is None:
            return None
        for i, js_url in enumerate(cipher.script_urls(html, ORIGIN)):
            if i >= MAX_SCRIPTS:
                break
            r = self.net.get(js_url, accept="*/*", check=False)
            if r.status in (401, 403, 429) or r.status >= 500:
                raise Blocked(f"http-{r.status}", site=self.id, url=js_url)
            if r.status != 200:
                continue
            for s in cipher.salt_candidates(r.text):
                if self._proves(s, probe):
                    self._salt = s
                    try:
                        cache.write_text(json.dumps({"salt": s, "script": urllib.parse.urlparse(js_url).path,
                                                     "found": date.today().isoformat()}))
                    except OSError:
                        pass
                    return s
        return None

    @staticmethod
    def _probe(advert: dict) -> tuple[str, list[str]] | None:
        ph, vin = tokens(advert)
        enc = [t for t in ph if cipher.is_token(t)]
        if enc:
            return enc[0], phone_keys(advert)
        if cipher.is_token(vin):
            return vin, [str(advert.get("id") or "")]
        return None

    @staticmethod
    def _proves(salt: str, probe: tuple[str, list[str]]) -> bool:
        return cipher.decode(probe[0], probe[1], salt) is not None

    def _cache_path(self):
        from carhunt.access import _core
        return _core.path("sites", self.id, "cipher-salt.json")
