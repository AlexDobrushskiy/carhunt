"""CustoJusto (PT): plain HTTP clients get 403 (client fingerprint, not the IP), a real browser passes. Pages carry
their data in Next.js `__NEXT_DATA__` (list: `listItems`, ad: `adData` + `base` + `userData`), read by a same-origin
fetch inside one browser tab. km is only a range; the phone endpoint 403s even from the page → contact form."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num, page_props
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

ORIGIN = "https://www.custojusto.pt"
PAGE_SIZE = 40
CV_TO_KW = 0.7355


def km_range(s: str | None) -> tuple[int | None, int | None]:
    """"10 000 - 19 999" → (10000, 19999); one number → (n, n)."""
    nums = [num(x) for x in re.split(r"\s*-\s*", s or "") if re.search(r"\d", x)]
    return (nums[0], nums[-1]) if nums else (None, None)


def _kw(hp: int | None) -> int | None:
    return round(hp * CV_TO_KW) if hp else None


def _reg(p: dict) -> tuple[int | None, str | None]:
    year, month = num(p.get("regdate")), num(p.get("regmonth"))
    return year, (f"{year}-{month:02d}" if year and month else (str(year) if year else None))


class Plugin(BaseSite):
    pkg = "custojusto_pt"

    # --- search ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        path = f"/{self.codes.get('region', 'portugal')}/veiculos/carros-usados"
        if q.make:
            path += "/" + self.code("makes", q.make)
            if q.model:
                path += "/" + self.code("models", q.make, q.model)
        p = dict(q.extra)
        if page > 1:
            p["o"] = str(page)
        return ORIGIN + path + (f"?{urllib.parse.urlencode(p)}" if p else "")

    def _props(self, url: str, ad_id: str | None = None) -> dict:
        r = self.net.browser_get(url, mode="fetch", ad_id=ad_id)
        if r.final_url and re.search(self.meta["liveness"]["gone_redirect"], r.final_url):
            raise Gone(url, f"redirect {r.final_url[:100]}")    # the site's own "ad gone" (list ?gone=<id>)
        pp = page_props(r.text)
        if pp is None:
            raise Blocked("no-next-data", site=self.id, url=url)
        return pp

    def search(self, q: SearchQuery) -> Iterator[Card]:
        """Newest first. `galleryAds` (promoted strip, ignores the path filters) are skipped."""
        fuel_rx = self.code("fuel", q.fuel, slug=False) if q.fuel else None
        if q.fuel and not fuel_rx:
            raise Unsupported(f"{self.id}: no fuel label for {q.fuel!r} (codes.yaml fuel)")
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            items = self._props(url).get("listItems")
            if items is None:
                raise Blocked("no-listItems", site=self.id, url=url)
            for it in items:
                c = self.card(it)
                if self._keep(c, q, fuel_rx):
                    yield c
            if len(items) < PAGE_SIZE:
                break

    @staticmethod
    def _keep(c: Card, q: SearchQuery, fuel_rx: str | None) -> bool:
        """Query filters the URL can't carry, applied on the row (unknown values pass: discover decides)."""
        if fuel_rx and not re.search(fuel_rx, c.fuel or "", re.I):
            return False
        if q.seller != "any" and c.seller_type != q.seller:
            return False
        for v, lo, hi in ((c.price, q.price_min, q.price_max), (c.year, q.year_min, q.year_max)):
            if v is not None and ((lo and v < lo) or (hi and v > hi)):
                return False
        return True

    def card(self, it: dict) -> Card:
        p = it.get("params") or {}
        year, reg = _reg(p)
        loc = it.get("locationNames") or {}
        return Card(url=urllib.parse.urljoin(ORIGIN, it["url"]), site=self.id, site_ref=str(it["listID"]),
                    title=it.get("title"), price=num(it.get("price")), year=year, first_registration=reg,
                    fuel=p.get("fuel"), seller_type="dealer" if it.get("companyAd") else "private",
                    location=", ".join(x for x in (loc.get("county"), loc.get("district")) if x) or None,
                    country="PT", thumb=it.get("imageFullURL"), created=it.get("listTime"))

    # --- ad ----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        pp = self._props(url, ad_id=self.ad_id(url))
        if pp.get("expiredAdData"):
            raise Gone(url, "expiredAdData")
        if not pp.get("adData"):
            raise Blocked("no-adData", site=self.id, url=url)
        return self.parse_ad(url, pp)

    def parse_ad(self, url: str, pp: dict) -> RawAd:
        a, b, u = pp["adData"], pp.get("base") or {}, pp.get("userData") or {}
        p = a.get("params") or {}
        year, reg = _reg(p)
        hp = num(p.get("power"))
        res = a.get("adResources") or {}
        lo, hi = km_range(b.get("mileage"))
        wa = p.get("whatsapp_nr")
        photos = [(x.get("yams_oid") or "").replace("{rule}", "play")
                  for x in sorted(a.get("extraImages") or [], key=lambda x: x.get("seq_no") or 0)
                  if x.get("yams_oid") and not x.get("deleted")]
        name = lambda k: (b.get(k) or {}).get("name")   # noqa: E731
        return RawAd(
            url=url, site=self.id, site_ref=str(a["listID"]), title=a.get("title"), price=num(a.get("price")),
            make=name("brand"), model=name("model"), year=year, first_registration=reg,
            km=None,                                  # site shows a range only: ask the seller (cluster photo)
            fuel=name("fuel"), power_kw=_kw(hp), power_hp=hp, color=name("color"),
            description=(a.get("body") or "").strip() or None,
            photos=photos or ([a["imageFullURL"]] if a.get("imageFullURL") else []),
            whatsapp=wa if isinstance(wa, str) and re.search(r"\d", wa) else None,
            seller=Seller(type="dealer" if a.get("companyAd") else "private", name=a.get("name") or u.get("name"),
                          id=str(a["userID"]) if a.get("userID") else None, city=res.get("areaName"),
                          region=res.get("regionName"), country="PT", url=u.get("shopUrl") or None),
            location=", ".join(x for x in (res.get("subAreaName"), res.get("areaName"), res.get("regionName")) if x)
            or None, country="PT", created=a.get("listTime"),
            contact={"form": True, "phone": not a.get("phoneHidden"), "chat": False},
            extra={"km_range": b.get("mileage"), "km_min": lo, "km_max": hi, "old_price": a.get("oldPrice"),
                   "whatsapp_same_as_phone": True if wa is True else None,
                   "dealer_ref": p.get("external_ad_id"), "seller_ads": u.get("adsCount")},
            raw={"pageProps": {"adData": a, "base": b, "userData": u}})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        if ad.phones or not reveal:
            return list(ad.phones)
        raise Unsupported(f"{self.id}: phone POST /api/ad/phone 403s even from the ad page; "
                          "contact the seller through the site's form (contact module)")
