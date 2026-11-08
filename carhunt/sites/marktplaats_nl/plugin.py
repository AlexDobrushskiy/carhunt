"""marktplaats.nl / 2dehands.be / 2ememain.be (one Adevinta platform): plain HTTP. Search = the site's JSON API
`/lrp/api/search` (30 rows/page, attribute-id filters); ad = page data `window.__CONFIG__.listing`.

Never warm up on `/`: CloudFront 403s the home page to scripts while the API and ad pages pass (11-01).
Private phones are hidden logged-out and the login needs SMS 2FA per new device (never set up) → no reveal."""
from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Blocked, Unsupported
from carhunt.sites.extract import num, window_var
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

_DESC = re.compile(r'<div data-collapsable="description">(.*?)</div>', re.S)
_META_DESC = re.compile(r'<meta name="description" content="([^"]*)"')


def _attrs(listing: dict) -> dict:
    """Search row `attributes` + `extendedAttributes` ([{key, value}]) → {key: value}."""
    rows = (listing.get("attributes") or []) + (listing.get("extendedAttributes") or [])
    return {a["key"]: a.get("value") for a in rows if isinstance(a, dict) and a.get("key")}


def _car_attrs(listing: dict) -> dict:
    """Ad `carAttributes.groupedWithIcons[].attributes[]` → {key: value | values}; first group wins."""
    out: dict = {}
    for g in (listing.get("carAttributes") or {}).get("groupedWithIcons") or []:
        for a in (g or {}).get("attributes") or []:
            if a.get("key"):
                out.setdefault(a["key"], a.get("value") if a.get("value") is not None else a.get("values"))
    return out


def _price(listing: dict) -> int | None:
    cents = (listing.get("priceInfo") or {}).get("priceCents")
    return int(cents) // 100 if cents else None


def _text(fragment: str) -> str:
    s = re.sub(r"<br\s*/?>|</p>", "\n", fragment, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _seller_type(s: dict) -> str:
    t = str(s.get("sellerType") or "").upper()
    if t == "TRADER" or s.get("sellerWebsiteUrl"):
        return "dealer"
    return "private" if t in ("CONSUMER", "PRIVATE") else "unknown"


class Plugin(BaseSite):
    pkg = "marktplaats_nl"

    # --- domains -----------------------------------------------------------
    def domain(self, country: str | None, lang: str | None = None) -> tuple[str, str, str]:
        """(origin, Accept-Language, country) for NL / BE / BE + lang=fr (2ememain mirror)."""
        key = (country or "NL").upper() + ("-fr" if (lang or "").lower() == "fr" else "")
        dom = self.codes["domains"].get(key)
        if not dom:
            raise Unsupported(f"{self.id}: no domain for country {country} lang {lang}")
        return dom[0], dom[1], dom[2]

    def domain_of(self, url: str) -> tuple[str, str, str]:
        host = urllib.parse.urlparse(url).hostname or ""
        for origin, lang, cc in self.codes["domains"].values():
            if urllib.parse.urlparse(origin).hostname == host:
                return origin, lang, cc
        raise Unsupported(f"{self.id}: unknown host {host}")

    # --- search ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        extra = dict(q.extra)
        origin, _, _ = self.domain(q.country, q.lang or extra.pop("lang", None))
        size = int(self.codes["page_size"])
        p: list[tuple[str, str]] = [("l1CategoryId", str(self.codes["category"])), ("limit", str(size)),
                                    ("offset", str((page - 1) * size))]
        text = self.code("query", q.make, q.model, slug=False) or " ".join(x for x in (q.make, q.model) if x)
        if text:
            p.append(("query", text))
        if q.seller != "any":
            p.append(("attributesById[]", self.need_code("seller", q.seller)))
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p.append(("attributesById[]", self.code("fuel", q.fuel, slug=False)))
        rk = self.codes["range_keys"]

        def rng(key: str, lo: int | None, hi: int | None) -> None:
            if lo or hi:
                p.append(("attributeRanges[]", f"{key}:{lo or 'null'}:{hi or 'null'}"))

        rng(rk["year"], q.year_min, q.year_max)
        rng(rk["km"], None, q.km_max)
        rng(rk["price_cents"], q.price_min and q.price_min * 100, q.price_max and q.price_max * 100)
        p += [(k, str(v)) for k, v in (self.codes["sort"].get(q.sort) or {}).items()]
        p += list(extra.items())
        return f"{origin}/lrp/api/search?{urllib.parse.urlencode(p)}"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        origin, lang, cc = self.domain(q.country, q.lang or q.extra.get("lang"))
        size = int(self.codes["page_size"])
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            d = self.net.json(url, headers={"Accept-Language": lang})
            rows = d.get("listings") if isinstance(d, dict) else None
            if rows is None:
                raise Blocked("no-listings", site=self.id, url=url)
            for row in rows:
                yield self.card(row, origin, cc, q.seller)
            if len(rows) < size or page >= int(d.get("maxAllowedPageNumber") or 1):
                break

    def card(self, row: dict, origin: str, country: str, seller: str = "any") -> Card:
        a, loc = _attrs(row), row.get("location") or {}
        year = num(a.get("constructionYear"))
        return Card(url=urllib.parse.urljoin(origin, row["vipUrl"]), site=self.id, site_ref=row["itemId"],
                    title=row.get("title"), price=_price(row), km=num(a.get("mileage")), year=year,
                    first_registration=str(year) if year else None, make=a.get("brand"), model=a.get("model"),
                    fuel=a.get("fuel"),
                    # the API has no seller type per row: known only when the query filtered on it
                    seller_type=seller if seller in ("private", "dealer") else "unknown",
                    location=loc.get("cityName"), country=loc.get("countryAbbreviation") or country)

    # --- ad ----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        _, lang, _ = self.domain_of(url)
        r = self.net.get(url, ad_id=self.ad_id(url), headers={"Accept-Language": lang})
        return self.parse_ad(url, r.text)

    def parse_ad(self, url: str, page: str) -> RawAd:
        try:
            cfg = window_var(page, "__CONFIG__")
        except ValueError:
            cfg = None
        listing = cfg.get("listing") if isinstance(cfg, dict) else None
        if not listing:
            raise Blocked("no-listing-config", site=self.id, url=url)
        origin, _, dom_cc = self.domain_of(url)
        a, cd = _car_attrs(listing), listing.get("carDetails") or {}
        s = listing.get("seller") or {}
        loc = s.get("location") or {}
        cc = loc.get("countryAbbreviation") or dom_cc
        dm = _DESC.search(page)
        mm = _META_DESC.search(page)
        year = num(a.get("constructionYear") or cd.get("constructionYear"))
        phone = s.get("phoneNumber") if not s.get("phoneNumberHidden") else None
        if phone and str(phone).startswith("0") and cc in self.codes["phone_cc"]:
            phone = self.codes["phone_cc"][cc] + str(phone)[1:]
        opts = set(s.get("contactOptions") or [])
        profile = s.get("sellerProfileUrl")
        imgs = (listing.get("gallery") or {}).get("imageUrls") or []
        photos = ["https:" + i if i.startswith("//") else i for i in imgs]
        bat = num(a.get("batteryCapacity"))
        return RawAd(
            url=url, site=self.id, site_ref=listing.get("itemId") or self.ad_id(url), title=listing.get("title"),
            price=_price(listing), make=cd.get("brand"), model=cd.get("model"), version=a.get("trim"),
            year=year, first_registration=str(year) if year else None, km=num(a.get("mileage")), fuel=a.get("fuel"),
            power_kw=num(a.get("powerInKiloWatt")), power_hp=num(a.get("powerInHorsePower")),
            drive=a.get("powerWheelDriver"), gearbox=a.get("transmission"), body=a.get("vehicleType"),
            color=a.get("color"), seats=num(a.get("numberOfSeats")), doors=num(a.get("numberOfDoors")),
            owners=num(a.get("totalNumberOfOwners")), battery_kwh=float(bat) if bat else None,
            plate=listing.get("licensePlate") or cd.get("licensePlate") or a.get("licensePlate"),
            description=_text(dm.group(1)) if dm else (html.unescape(mm.group(1)) if mm else None),
            equipment=[str(o) for o in a.get("options") or [] if o] if isinstance(a.get("options"), list) else [],
            # `$_#` is the image size placeholder: 85 = large
            photos=[p.replace("$_#.jpg", "$_85.jpg") for p in photos],
            phones=[str(phone)] if phone else [],
            seller=Seller(type=_seller_type(s), name=s.get("name"), id=str(s["id"]) if s.get("id") else None,
                          city=loc.get("cityName"), postcode=loc.get("postcode"), country=cc,
                          url=urllib.parse.urljoin(origin, profile) if profile else None),
            location=" ".join(x for x in (loc.get("postcode"), loc.get("cityName")) if x) or None, country=cc,
            created=(listing.get("stats") or {}).get("since"),
            status="reserved" if listing.get("isReserved") else None,
            contact={"chat": "asq" in opts, "phone": "phone" in opts, "website": "website" in opts},
            extra={"price_type": (listing.get("priceInfo") or {}).get("priceType"),
                   "phone_hidden": bool(s.get("phoneNumberHidden")) or None,
                   "service_history": a.get("serviceHistory"), "imported": a.get("isImported"),
                   "range_km": num(a.get("range")), "interior_color": a.get("interiorColor"),
                   "upholstery": a.get("upholstery"), "lease": (listing.get("flags") or {}).get("isLeaseCar") or None,
                   "car_pass_url": cd.get("carPassUrl") or (listing.get("carAttributes") or {}).get("carPassUrl"),
                   "views": (listing.get("stats") or {}).get("viewCount")},
            raw={"listing": listing})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        if ad.phones or not reveal:
            return list(ad.phones)
        raise Unsupported(f"{self.id}: phone hidden logged-out ('Toon nummer' needs a login; the account needs "
                          "SMS 2FA per new device, never set up)")
