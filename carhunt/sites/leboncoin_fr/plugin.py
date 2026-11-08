"""leboncoin.fr: DataDome. Plain HTTP reads carry a `datadome` cookie from a real browser's trust jar; all data is in
Next.js `__NEXT_DATA__` (search `searchData.ads`, 35/page, ≤100 pages; ad `pageProps.ad`). Phones and messages need
the logged-in account on a French IP → Unsupported here (browsers + contact modules)."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Iterator
from typing import Any

from carhunt.sites import live
from carhunt.sites._net import Response
from carhunt.sites.base import BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num, page_props, year_month, year_of
from carhunt.sites.model import Card, Liveness, RawAd, SearchQuery, Seller

ORIGIN = "https://www.leboncoin.fr"
MAX_PAGES = 100
# DataDome's hard-block page; the shared BOT regex already catches the slider (captcha-delivery).
HARD_BLOCK = re.compile(r"access (is )?temporarily restricted", re.I)
LOGIN_WALL = re.compile(r"auth\.leboncoin|/login|/connexion")
DESC_PHONE = re.compile(r"(?<!\d)(?:\+33\s*[1-9](?:[ .-]*\d){8}|0[1-9](?:[ .-]*\d){8})(?!\d)")
CookieSource = Callable[[], "str | None"]


def jar_cookie() -> str | None:
    """The trust jar's leboncoin `datadome` cookie (browsers module), None when the jar or the cookie is missing."""
    try:
        from carhunt.access import jar  # type: ignore[attr-defined]
    except ImportError:
        return None
    return jar.cookie("leboncoin.fr", "datadome")


def attrs(ad: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    """(label by key, raw value by key) from the ad's `attributes` list."""
    a = ad.get("attributes") or []
    return ({x["key"]: x.get("value_label") or x.get("value") for x in a if x.get("key")},
            {x["key"]: x.get("value") for x in a if x.get("key")})


def _reg(val: dict) -> str | None:
    """First registration "MM/YYYY" (issuance_date) → "YYYY-MM"; else the model year."""
    return year_month(val.get("issuance_date")) or year_month(val.get("regdate"))


def _price(ad: dict) -> int | None:
    if ad.get("price_cents"):
        return int(ad["price_cents"]) // 100
    p = ad.get("price")
    return num(p[0] if isinstance(p, list) and p else p)


def _hp_kw(val: dict) -> tuple[int | None, int | None]:
    hp = num(val.get("horse_power_din"))   # "Puissance DIN" (Ch); `horsepower` is the fiscal CV
    return hp, round(hp * 0.7355) if hp else None


def _seller_type(ad: dict) -> str:
    t = (ad.get("owner") or {}).get("type")
    return "dealer" if t == "pro" else "private" if t == "private" else "unknown"


def _location(loc: dict) -> str | None:
    return " ".join(x for x in (loc.get("zipcode"), loc.get("city")) if x) or None


def _created(ad: dict) -> str | None:
    d = ad.get("first_publication_date")
    return d.replace(" ", "T") if isinstance(d, str) else None


def _photos(ad: dict) -> list[str]:
    im = ad.get("images") or {}
    return list(im.get("urls_large") or im.get("urls") or [])


def ad_url(ad: dict) -> str:
    u = ad.get("url") or f"{ORIGIN}/ad/voitures/{ad['list_id']}"
    return u if u.startswith("http") else ORIGIN + u


class Plugin(BaseSite):
    pkg = "leboncoin_fr"

    def __init__(self, net: Any = None, *, cookie: str | CookieSource | None = None):
        """`cookie`: a datadome value or a callable returning one (default: the browsers module's trust jar)."""
        super().__init__(net)
        self._source: CookieSource = (lambda: cookie) if isinstance(cookie, str) else (cookie or jar_cookie)
        self._dd: str | None = None
        self._referer = ORIGIN + "/"

    # --- query -------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        if q.country and q.country.upper() != "FR":
            raise Unsupported(f"leboncoin.fr: France only (asked {q.country})")
        p: dict[str, str] = {"category": str(self.codes["category"])}
        model = self.code("models", q.make, q.model, slug=False) if q.make and q.model else None
        if model:
            p["u_car_model"] = model
        elif q.make and not q.model and self.code("brands", q.make, slug=False):
            p["u_car_brand"] = self.code("brands", q.make, slug=False)
        elif q.make or q.model:
            p["text"] = " ".join(x for x in (q.make, q.model) if x)
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["fuel"] = self.code("fuel", q.fuel, slug=False)
        rng = self.codes["ranges"]
        for field, lo, hi in (("year", q.year_min, q.year_max), ("km", None, q.km_max),
                              ("price", q.price_min, q.price_max)):
            if lo or hi:
                p[rng[field]] = f"{lo or 'min'}-{hi or 'max'}"
        if q.seller != "any":
            p["owner_type"] = self.need_code("seller", q.seller)
        p.update(self.codes["sort"].get(q.sort) or {})
        if page > 1:
            p["page"] = str(page)
        p.update(q.extra)
        return f"{ORIGIN}/recherche?{urllib.parse.urlencode(p)}"

    # --- transport ---------------------------------------------------------
    def _cookie(self, url: str) -> str:
        if self._dd is None:
            self._dd = self._source()
        if not self._dd:   # no request without a cookie: a cookieless hit only raises the bot score
            raise Blocked("datadome-no-cookie", site=self.id, url=url,
                          detail="no leboncoin datadome cookie: one real-browser home-page load fills the trust jar")
        return self._dd

    def _fetch(self, url: str, *, ad_id: str | None = None, follow: bool = True, check: bool = True) -> Response:
        h = {"Cookie": f"datadome={self._cookie(url)}", "Referer": self._referer}
        r = self.net.get(url, headers=h, ad_id=ad_id, follow=follow, check=check,
                         country=self.meta.get("country_ip"))
        m = re.search(r"datadome=([^;,\s]+)", r.headers.get("set-cookie", ""))
        if m:   # DataDome rotates its cookie on every response: keep the newest for this run
            self._dd = m.group(1)
        if r.final_url and LOGIN_WALL.search(r.final_url):
            raise Blocked("login-wall", site=self.id, url=url)
        if HARD_BLOCK.search(r.text[:20000]):
            raise Blocked("datadome-hard-block", site=self.id, url=url, detail="stop for hours")
        if r.status == 200:
            self._referer = url
        return r

    def _props(self, url: str, ad_id: str | None = None) -> dict:
        r = self._fetch(url, ad_id=ad_id)
        pp = page_props(r.text)
        if pp is None:
            if re.search(self.meta["liveness"]["gone_text"], r.text, re.I):
                raise Gone(url, "200 Annonce introuvable")
            raise Blocked("no-next-data", site=self.id, url=url)
        return pp

    # --- search ------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, min(max(q.max_pages, 1), MAX_PAGES) + 1):
            url = self.search_url(q, page)
            sd = self._props(url).get("searchData")
            if sd is None:
                raise Blocked("no-search-data", site=self.id, url=url)
            ads = sd.get("ads") or []
            for ad in ads:
                yield self.card(ad)
            if not ads or page >= int(sd.get("max_pages") or 1):
                break

    def card(self, ad: dict) -> Card:
        lab, val = attrs(ad)
        reg = _reg(val)
        _, kw = _hp_kw(val)
        loc = ad.get("location") or {}
        im = ad.get("images") or {}
        return Card(url=ad_url(ad), site=self.id, site_ref=str(ad["list_id"]), title=ad.get("subject"),
                    price=_price(ad), km=num(val.get("mileage")), year=year_of(reg), first_registration=reg,
                    make=lab.get("brand"), model=lab.get("u_car_model") or lab.get("model"),
                    version=lab.get("u_car_version") or lab.get("u_car_finition"), fuel=lab.get("fuel"),
                    power_kw=kw, seller_type=_seller_type(ad), location=_location(loc),
                    country=loc.get("country_id"), thumb=im.get("thumb_url") or (_photos(ad) or [None])[0],
                    created=_created(ad))

    # --- ad ----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        aid = self.ad_id(url)
        x = self._props(url, ad_id=aid).get("ad")
        if not x:
            raise Blocked("no-ad", site=self.id, url=url)
        if x.get("status") not in (None, "active"):
            raise Gone(url, f"status {x.get('status')}")
        if aid and str(x.get("list_id")) != aid:
            raise Blocked("ad-id-mismatch", site=self.id, url=url)
        return self.parse_ad(url, x)

    def ad_from_page(self, url: str, text: str) -> RawAd | None:
        """Liveness price from the page is_live already read (no second cookie'd load)."""
        x = (page_props(text) or {}).get("ad") or {}
        if str(x.get("list_id")) != self.ad_id(url):
            return None
        try:
            return self.parse_ad(url, x)
        except Exception:   # noqa: BLE001
            return None

    def parse_ad(self, url: str, x: dict) -> RawAd:
        lab, val = attrs(x)
        reg = _reg(val)
        hp, kw = _hp_kw(val)
        loc, own = x.get("location") or {}, x.get("owner") or {}
        history = str(lab.get("vehicle_history") or "")
        body = x.get("body") or ""
        extra = {
            "model_year": num(val.get("regdate")),
            "battery_soh_pct": float(val["vehicle_battery_state_of_health"])
            if re.fullmatch(r"\d+(\.\d+)?", str(val.get("vehicle_battery_state_of_health") or "")) else None,
            "battery_soh_date": val.get("vehicle_battery_state_of_health_date"),
            "condition": lab.get("vehicle_damage"),
            "maintenance": lab.get("vehicle_maintenance"),
            "history": history or None,
            "upholstery": lab.get("vehicle_upholstery"),
            "interior": lab.get("vehicle_interior_specs"),
            "import": str(val.get("is_import")).lower() == "true" or "import" in history.lower() or None,
            "inspection_valid": {"true": True, "false": False}.get(str(val.get("vehicle_technical_inspection_valid"))),
            "history_report_url": val.get("vehicle_history_report_public_url"),
            "fiscal_hp": num(val.get("horsepower")),
            "store_name": lab.get("store_name") if own.get("type") == "pro" else None,
        }
        return RawAd(
            url=url, site=self.id, site_ref=str(x.get("list_id") or self.ad_id(url)), title=x.get("subject"),
            price=_price(x), make=lab.get("brand"), model=lab.get("u_car_model") or lab.get("model"),
            version=lab.get("u_car_version") or lab.get("u_car_finition"), year=year_of(reg),
            first_registration=reg, km=num(val.get("mileage")), fuel=lab.get("fuel"), power_kw=kw, power_hp=hp,
            gearbox=lab.get("gearbox"), body=lab.get("vehicle_type"), color=lab.get("vehicule_color"),
            seats=num(val.get("seats")), doors=num(val.get("doors")),
            owners=1 if "première main" in history.lower() or str(val.get("first_hand_vehicle")).lower() == "true"
            else None,
            service_history=True if "carnet d'entretien" in str(lab.get("vehicle_maintenance") or "").lower()
            else None,
            description=body or None, photos=_photos(x),
            phones=list(dict.fromkeys(DESC_PHONE.findall(body))),   # only numbers the seller typed in the text
            seller=Seller(type=_seller_type(x), name=own.get("name"),
                          id=str(own.get("store_id") or own.get("user_id") or "") or None, city=loc.get("city"),
                          postcode=loc.get("zipcode"), region=loc.get("region_name"), country=loc.get("country_id")),
            location=_location(loc), country=loc.get("country_id"), created=_created(x), status=x.get("status"),
            contact={"chat": True, "phone": bool(x.get("has_phone"))}, extra=extra, raw={"ad": x})

    # --- phone -------------------------------------------------------------
    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        if not reveal:
            return list(ad.phones)
        raise Unsupported("leboncoin.fr: 'Voir le numéro' needs the logged-in account on its one French IP "
                          "(browsers + contact modules); cap ≤40 reveals/day, take the slot before the click")

    # --- liveness ----------------------------------------------------------
    def is_live(self, url: str, *, country: str | None = None) -> Liveness:
        """One cookie'd read without redirects. 200 counts as live only with this ad in the page data: a DataDome
        page can quote the ad URL (and so its id) without being the ad."""
        rules = self.meta.get("liveness") or {}
        aid = self.ad_id(url)
        r = self._fetch(url, ad_id=aid, follow=False, check=False)
        hint = live.hint_of(r.text, aid, rules)
        verdict, sig = live.classify(url, r.status, r.location, hint, rules=rules, ad_id=self.ad_id)
        if verdict == "live" and r.status == 200:
            ad = (page_props(r.text) or {}).get("ad") or {}
            if str(ad.get("list_id")) != aid:
                verdict, sig = "unknown", "200 without the ad in page data"
            elif ad.get("status") not in (None, "active"):
                verdict, sig = "gone", f"200 status {ad.get('status')}"
        return live.with_price(self, url, live.to_liveness(self.id, url, verdict, sig), r.text)
