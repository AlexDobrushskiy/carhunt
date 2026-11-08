"""mobile.de: Akamai lets only a plain (non-automated) Chrome through, so every read is a navigation in the
plain-chrome tab. List and ad pages are Next.js RSC: the data sits in the `self.__next_f` flight stream, so one load
= one search page (20 organic rows) or one full ad, phones included when the seller published them (no login)."""
from __future__ import annotations

import datetime
import re
import urllib.parse
from collections.abc import Iterator
from typing import Any

from carhunt.sites.base import BaseSite, Blocked, Gone
from carhunt.sites.extract import flight, flight_ref_text, num, objects_after, title, year_month, year_of
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

SEARCH = "https://suchen.mobile.de/fahrzeuge/search.html"
MODEL_PAGE = "https://suchen.mobile.de/auto/{}.html"
DETAILS = "https://suchen.mobile.de/fahrzeuge/details.html?id={}"
SPONSORED = {"topOfPage", "topInCategory"}   # paid rows on page 1; "eyecatcher" rows are organic
GONE_TITLE = re.compile(r"nicht verfügbar", re.I)
DRIVES = ("Allradantrieb", "Heckantrieb", "Frontantrieb")


def _s(v: Any) -> Any:
    return v.replace(" ", " ").strip() if isinstance(v, str) else v


def strip_html(t: str | None) -> str | None:
    if not t:
        return t
    t = re.sub(r"<br\s*/?>|</p>|</li>", "\n", t)
    return _s(re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", t)))


def kw_hp(v: str | None) -> tuple[int | None, int | None]:
    """'150 kW (204 PS)' → (150, 204)."""
    s = _s(v) or ""
    k, h = re.search(r"(\d+)\s*kW", s), re.search(r"(\d+)\s*PS", s)
    return (int(k.group(1)) if k else None), (int(h.group(1)) if h else None)


def gross(price: dict | None) -> int | None:
    """`price.grs.amount` is gross EUR, never cents; never fall back to net."""
    return num(((price or {}).get("grs") or {}).get("amount"))


def phones(contact: dict | None) -> list[str]:
    return [p["uri"][4:] for p in (contact or {}).get("phones") or [] if str(p.get("uri", "")).startswith("tel:")]


def seller_type(contact: dict | None) -> str:
    t = (contact or {}).get("enumType")
    return "private" if t == "FSBO" else "dealer" if t == "DEALER" else "unknown"


class Plugin(BaseSite):
    pkg = "mobile_de"

    # --- query ------------------------------------------------------------
    def targets(self, q: SearchQuery) -> list[tuple[str, str | None]]:
        """(base URL, ms code) per sub-search: one per model code, or the model page for code-less models."""
        if not q.make:
            return [(SEARCH, None)]
        page = self.code("model_pages", q.make, q.model, slug=False) if q.model else None
        if page:
            return [(MODEL_PAGE.format(page), None)]
        make = self.need_code("makes", q.make)
        if not q.model:
            return [(SEARCH, f"{make};;;")]
        models = {str(k).lower(): v for k, v in (self.codes.get("models", {}).get(q.make) or {}).items()}
        codes = models.get(q.model.lower())
        if codes is None:
            self.need_code("models", q.make, q.model)   # raises Unsupported with the codes.yaml hint
        return [(SEARCH, f"{make};{c};;") for c in (codes if isinstance(codes, list) else [codes])]

    def search_url(self, q: SearchQuery, page: int = 1, target: int = 0) -> str:
        base, ms = self.targets(q)[target]
        p: dict[str, str] = {"isSearchRequest": "true", "s": "Car", "vc": "Car"}
        if ms:
            p["ms"] = ms
        if q.seller != "any":
            p["adLimitation"] = self.need_code("seller", q.seller)
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["ft"] = self.code("fuel", q.fuel, slug=False)
        if q.year_min or q.year_max:
            p["fr"] = f"{q.year_min or ''}:{q.year_max or ''}"
        if q.km_max:
            p["ml"] = f":{q.km_max}"
        if q.price_min or q.price_max:
            p["p"] = f"{q.price_min or ''}:{q.price_max or ''}"
        p["cn"] = (q.country or "DE").upper()
        p.update(self.codes["sort"][q.sort])
        if page > 1:
            p["pageNumber"] = str(page)
        p.update(q.extra)
        return f"{base}?{urllib.parse.urlencode(p, safe=':;')}"

    # --- transport ----------------------------------------------------------
    def _stream(self, url: str, ad_id: str | None = None) -> str:
        r = self.net.browser_get(url, mode="goto", ad_id=ad_id)   # ads live on suchen.mobile.de: cross-origin
        if ad_id and GONE_TITLE.search(title(r.text) or ""):
            raise Gone(url, "200 nicht verfügbar")
        return flight(r.text)

    # --- search -------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        size = int(self.codes.get("page_size", 20))
        for t in range(len(self.targets(q))):
            for page in range(1, max(q.max_pages, 1) + 1):
                url = self.search_url(q, page, t)
                res = self.parse_search(self._stream(url), url)
                for row in res.get("listings") or []:
                    yield self.card(row)
                organic = sum(1 for r in res.get("listings") or [] if r.get("type") not in SPONSORED)
                if not organic or page * size >= int(res.get("numResultsTotal") or 0):
                    break

    def parse_search(self, stream: str, url: str = "") -> dict:
        res = next((o for o in objects_after(stream, "searchResults") if isinstance(o, dict)), None)
        if res is None:
            raise Blocked("no-search-data", site=self.id, url=url)
        return res

    def card(self, row: dict) -> Card:
        a, c = row.get("attr") or {}, row.get("contact") or {}
        reg = year_month(_s(a.get("fr")))
        make, model = (row.get("make") or {}).get("localized"), (row.get("model") or {}).get("localized")
        loc = " ".join(x for x in (_s(a.get("z")), _s(a.get("loc"))) if x) or None
        return Card(url=DETAILS.format(row["id"]), site=self.id, site_ref=str(row["id"]),
                    title=" ".join(x for x in (make, model, row.get("subTitle")) if x) or None,
                    price=gross(row.get("price")), price_is_net=False if gross(row.get("price")) else None,
                    km=num(_s(a.get("ml"))), year=year_of(reg), first_registration=reg, make=make, model=model,
                    version=row.get("subTitle"), fuel=_s(a.get("ft")), power_kw=kw_hp(a.get("pw"))[0],
                    seller_type=seller_type(c), location=loc, country=a.get("cn"), phones=phones(c),
                    sponsored=row.get("type") in SPONSORED)

    # --- ad -----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        stream = self._stream(url, ad_id=self.ad_id(url))
        return self.parse_ad(url, stream)

    def parse_ad(self, url: str, stream: str) -> RawAd:
        L = next((o for o in objects_after(stream, "listing") if isinstance(o, dict) and "attributes" in o), None)
        if L is None:
            raise Blocked("no-listing", site=self.id, url=url)
        at = {x.get("tag"): _s(x.get("value")) for x in L.get("attributes") or [] if x.get("tag")}
        c, price = L.get("contact") or {}, L.get("price") or {}
        desc = L.get("htmlDescription")
        if isinstance(desc, str) and re.fullmatch(r"\$[0-9a-fA-F]+", desc):
            desc = flight_ref_text(stream, desc)
        reg = year_month(at.get("firstRegistration"))
        kw, hp = kw_hp(at.get("power"))
        feats = [_s(f) for f in L.get("features") or []]
        dmg = at.get("damageCondition") or ""
        addr = _s(c.get("address2")) or ""
        m = re.match(r"([A-Z]{2})-(\d{4,5})\s+(.*)", addr)
        cc, zp, city = (m.group(1), m.group(2), m.group(3)) if m else (c.get("country"), None, addr or None)
        bat = re.search(r"(\d+(?:[.,]\d+)?)", at.get("batteryCapacity") or "")
        partner = next((x.get("href") for x in L.get("links") or [] if x.get("rel") == "partner-vip"), None)
        mirror = str(L.get("sellerId")) == str(self.codes.get("mirror_seller_id")) or bool(partner)
        created = L.get("created")
        ph = phones(c)
        return RawAd(
            url=L.get("url") or url, site=self.id, site_ref=str(L.get("id") or self.ad_id(url)),
            title=L.get("title") or L.get("shortTitle"), price=gross(price),
            price_is_net=False if gross(price) else None,
            make=(L.get("make") or {}).get("localized"), model=(L.get("model") or {}).get("localized"),
            version=L.get("subTitle"), year=year_of(reg), first_registration=reg, km=num(at.get("mileage")),
            fuel=at.get("fuel") or at.get("envkv.engineType"), power_kw=kw, power_hp=hp,
            drive=next((d for d in DRIVES if d in feats), None), gearbox=at.get("transmission"),
            body=at.get("category"), color=at.get("color"), seats=num(at.get("numSeats")),
            doors=_last_int(at.get("doorCount")), owners=num(at.get("numberOfPreviousOwners")),
            accident_free=True if "Unfallfrei" in dmg else False if "Unfall" in dmg or L.get("isDamageCase") else None,
            service_history=True if any("scheckheft" in (f or "").lower() for f in feats) else None,
            battery_kwh=float(bat.group(1).replace(",", ".")) if bat else None, description=strip_html(desc),
            equipment=feats,
            photos=[_photo(i.get("uri")) for i in L.get("images") or [] if isinstance(i, dict) and i.get("uri")],
            phones=ph,
            seller=Seller(type=seller_type(c), name=_s(c.get("name")),
                          id=str(L["sellerId"]) if L.get("sellerId") else None, city=city, postcode=zp, country=cc),
            location=" ".join(x for x in (zp, city) if x) or None, country=cc,
            created=(datetime.datetime.fromtimestamp(int(created), datetime.UTC).isoformat()
                     if isinstance(created, (int, float)) else None),
            contact={"phone": bool(ph), "form": True},
            extra={"price_net": num((price.get("nt") or {}).get("amount")), "vat_rate": price.get("vat"),
                   "price_rating": (L.get("priceRating") or {}).get("rating"), "mirror": mirror or None,
                   "partner_url": partner, "damage_case": L.get("isDamageCase") or None,
                   "phone_note": "kleinanzeigen.de mirror: phones are call-tracking proxies" if mirror and ph
                   else None},
            raw={"listing": L})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        return list(ad.phones)   # the page already carries every published number; there is no reveal


def _last_int(v: str | None) -> int | None:
    m = re.search(r"(\d+)\D*$", v or "")     # doors "4/5" → 5
    return int(m.group(1)) if m else None


def _photo(uri: str) -> str:
    return uri if uri.startswith("http") else "https://" + uri.lstrip("/") + "?rule=mo-1024.jpg"
