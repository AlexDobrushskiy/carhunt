"""AutoScout24 (every country domain): plain HTTP, all data in the Next.js `__NEXT_DATA__` (list + ad pages),
including private sellers' phones. 20 rows per page, newest first = sort=age&desc=1."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Blocked, Unsupported
from carhunt.sites.extract import num, page_props, year_month, year_of
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

LANG = {"de": "de-DE", "at": "de-AT", "it": "it-IT", "es": "es-ES", "fr": "fr-FR", "nl": "nl-NL", "be": "nl-BE",
        "lu": "fr-LU", "com": "en-GB", "pl": "pl-PL"}


def _phones(seller: dict | None) -> list[str]:
    return [str(p["callTo"]) for p in (seller or {}).get("phones") or [] if p.get("callTo")]


def _seller_type(s: dict) -> str:
    t = str(s.get("type") or "").lower()
    if s.get("isDealer") or t == "dealer":
        return "dealer"
    return "private" if t.startswith("private") or t == "p" else "unknown"   # live value "PrivateSeller"


def _reg(v: str | None) -> str | None:
    """Card firstRegistration "MM-YYYY" / "MM/YYYY" → "YYYY-MM"."""
    m = re.search(r"(\d\d)[/-](\d{4})", v or "")
    return f"{m.group(2)}-{m.group(1)}" if m else year_month(v)


class Plugin(BaseSite):
    pkg = "autoscout24"

    def origin(self, country: str | None) -> tuple[str, str]:
        dom = self.codes["domains"].get((country or "DE").upper())
        if not dom:
            raise Unsupported(f"autoscout24: no domain for country {country}")
        tld, prefix, cy = dom
        return f"https://www.autoscout24.{tld}{prefix}", cy

    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        origin, cy = self.origin(q.country)
        path = "/lst"
        if q.make:
            path += "/" + self.code("makes", q.make)
            if q.model:
                path += "/" + self.code("models", q.make, q.model)
        p: dict[str, str] = {"atype": "C", "cy": cy}
        if q.year_min:
            p["fregfrom"] = str(q.year_min)
        if q.year_max:
            p["fregto"] = str(q.year_max)
        if q.km_max:
            p["kmto"] = str(q.km_max)
        if q.price_min:
            p["pricefrom"] = str(q.price_min)
        if q.price_max:
            p["priceto"] = str(q.price_max)
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["fuel"] = self.code("fuel", q.fuel, slug=False)
        if q.seller != "any":
            p["custtype"] = self.need_code("seller", q.seller)
        p.update(self.codes["sort"][q.sort])
        if page > 1:
            p["page"] = str(page)
        p.update(q.extra)
        return f"{origin}{path}?{urllib.parse.urlencode(p)}"

    def _props(self, url: str, ad_id: str | None = None) -> dict:
        tld = urllib.parse.urlparse(url).hostname.rsplit(".", 1)[-1]
        r = self.net.get(url, ad_id=ad_id, headers={"Accept-Language": LANG.get(tld, "en") + ",en;q=0.8"})
        pp = page_props(r.text)
        if pp is None:
            raise Blocked("no-next-data", site=self.id, url=url)
        return pp

    def search(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            pp = self._props(url)
            origin = "{0.scheme}://{0.netloc}/".format(urllib.parse.urlparse(url))
            for row in pp.get("listings") or []:
                yield self.card(row, origin)
            if page >= (pp.get("numberOfPages") or 0):
                break

    def card(self, row: dict, origin: str) -> Card:
        v, s, t = row.get("vehicle") or {}, row.get("seller") or {}, row.get("tracking") or {}
        loc = row.get("location") or {}
        price = row.get("price") or {}
        reg = _reg(t.get("firstRegistration"))
        details = " ".join(str(d.get("data") or "") for d in row.get("vehicleDetails") or [])
        kw = re.search(r"(\d{2,3})\s*kW", details)
        imgs = row.get("images") or []
        return Card(url=urllib.parse.urljoin(origin, row["url"]), site=self.id, site_ref=row["id"],
                    title=" ".join(x for x in (row.get("title") or f"{v.get('make', '')} {v.get('model', '')}".strip(),
                                               v.get("modelVersionInput")) if x) or None,
                    price=num(price.get("priceRaw") if isinstance(price, dict) else price),
                    price_is_net=(price.get("isNetPrice") if isinstance(price, dict) else None),
                    km=num(t.get("mileage")), year=year_of(reg), first_registration=reg, make=v.get("make"),
                    model=v.get("model"), version=v.get("modelVersionInput"), fuel=v.get("fuel"),
                    power_kw=int(kw.group(1)) if kw else None, seller_type=_seller_type(s),
                    location=" ".join(x for x in (loc.get("zip"), loc.get("city")) if x) or None,
                    country=loc.get("countryCode"), thumb=(imgs[0] if imgs and isinstance(imgs[0], str) else None),
                    phones=_phones(s), sponsored=row.get("searchResultType", "Organic") != "Organic")

    def ad(self, url: str) -> RawAd:
        aid = self.ad_id(url)
        x = self._props(url, ad_id=aid).get("listingDetails")
        if not x:
            raise Blocked("no-listing", site=self.id, url=url)
        return self.parse_ad(url, x)

    def parse_ad(self, url: str, x: dict) -> RawAd:
        s, v, loc = x.get("seller") or {}, x.get("vehicle") or {}, x.get("location") or {}
        pub = (x.get("prices") or {}).get("public") or {}
        price = num(pub.get("priceRaw")) or (num(x.get("price")) if isinstance(x.get("price"), (int, float)) else None)
        reg = year_month(v.get("firstRegistrationDateRaw"))
        eq = v.get("equipment") or {}
        equipment = [i.get("id") for cat in (eq.values() if isinstance(eq, dict) else [])
                     if isinstance(cat, list) for i in cat if isinstance(i, dict) and i.get("id")]
        acc = v.get("hadAccident")
        return RawAd(
            url=url, site=self.id, site_ref=str(x.get("id") or self.ad_id(url)), title=x.get("title"),
            price=price, price_is_net=bool(pub.get("isNetPrice") or pub.get("isNet")) or None,
            make=v.get("make"), model=v.get("model"), version=v.get("modelVersionInput"), year=year_of(reg),
            first_registration=reg, km=num(v.get("mileageInKmRaw")), fuel=v.get("fuelType") or v.get("fuel"),
            power_kw=num(v.get("rawPowerInKw") or v.get("powerInKw")), power_hp=num(v.get("powerInHp")),
            drive=v.get("driveTrain"), gearbox=v.get("transmissionType") or v.get("transmission"),
            body=v.get("bodyType"), color=v.get("bodyColor"), seats=num(v.get("numberOfSeats")),
            doors=num(v.get("numberOfDoors")), owners=num(v.get("noOfPreviousOwners")),
            accident_free=(not acc) if acc is not None else None, service_history=v.get("hasFullServiceHistory"),
            plate=v.get("licensePlate"), description=x.get("description"), equipment=equipment,
            photos=[i if isinstance(i, str) else i.get("url") for i in x.get("images") or [] if i],
            phones=_phones(s), whatsapp=x.get("whatsappNumber"),
            seller=Seller(type=_seller_type(s), name=s.get("companyName") or s.get("contactName"),
                          id=str(s["id"]) if s.get("id") else None, city=loc.get("city"), postcode=loc.get("zip"),
                          country=loc.get("countryCode")),
            location=" ".join(x for x in (loc.get("zip"), loc.get("city")) if x) or None,
            country=loc.get("countryCode"), created=x.get("createdTimestampWithOffset"), status=x.get("status"),
            extra={"upholstery": v.get("upholstery"), "upholstery_color": v.get("upholsteryColor")},
            raw={"listingDetails": x})
