"""subito.it: plain HTTP (Chrome UA), no login. List pages carry the rows in `__NEXT_DATA__` (30 per page); ad pages
are Next App Router with the ad JSON in the RSC flight stream. The phone is the public JSON call the "Mostra numero"
button makes (`/hades/v1/contacts/ads/<urn>`), only for ads whose advertiser has a phone."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites._net import raise_for
from carhunt.sites.base import BaseSite, Blocked, Unsupported
from carhunt.sites.extract import flight, flight_ref_text, next_data, num, year_month, year_of
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

LIST = "https://www.subito.it/annunci-italia/vendita/auto/"
PHONE = "https://www.subito.it/hades/v1/contacts/ads/{}"
IMG_RULE = "?rule=gallery-desktop-1x-auto"


def it_phone(raw: str) -> str:
    """Subito returns national numbers ("0399…", "347…"): E.164 needs +39 (stored without it 11-04)."""
    d = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return "+" + d
    return "+" + d[2:] if d.startswith("00") else "+39" + d


def feats(ad: dict) -> dict[str, dict]:
    """features → {uri: first value}; /car → {"make"|"model"|"version": value} by label ("Altro allestimento"
    trims come with level 0, so the level alone mislabels them as the make)."""
    f = ad.get("features") or {}
    out = {uri: (v.get("values") or [{}])[0] for uri, v in f.items() if isinstance(v, dict)}
    by_label = {"Marca": "make", "Modello": "model", "Versione": "version"}
    by_level = {0: "make", 1: "model", 2: "version"}
    for v in (f.get("/car") or {}).get("values") or []:
        k = by_label.get(v.get("label")) or by_level.get(v.get("level"))
        if k and k not in out and v.get("key") != "000000":   # "Altro allestimento" = no trim given
            out[k] = v
    return out


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


class Plugin(BaseSite):
    pkg = "subito_it"

    # --- query ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        if q.country and q.country.upper() != "IT":
            raise Unsupported(f"subito.it: Italy only (country {q.country})")
        if q.sort not in self.codes["sort"]:
            raise Unsupported(f"subito.it: no sort code for {q.sort!r}")
        p: dict[str, str] = {}
        if q.make:
            cb = self.code("makes", q.make, slug=False)
            p.update({"cb": cb} if cb else {"q": q.make})
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["fl"] = self.code("fuel", q.fuel, slug=False)
        if q.year_min:
            p["ys"] = str(q.year_min)
        if q.year_max:
            p["ye"] = str(q.year_max)
        if q.price_min:
            p["ps"] = str(q.price_min)
        if q.price_max:
            p["pe"] = str(q.price_max)
        if q.km_max:
            p["me"] = str(q.km_max // int(self.codes["km_bucket"]) + 1)
        if q.seller != "any":
            p["advt"] = self.need_code("seller", q.seller)
        p.update(self.codes["sort"][q.sort])
        if page > 1:
            p["o"] = str(page)
        p.update(q.extra)
        return f"{LIST}?{urllib.parse.urlencode(p)}"

    def model_match(self, q: SearchQuery, ad: dict) -> bool:
        """The list filters by brand only: keep rows whose Modello group is the asked model."""
        if not q.model:
            return True
        m, mk = feats(ad).get("model") or {}, feats(ad).get("make") or {}
        if q.make and not self.code("makes", q.make, slug=False) and _norm(mk.get("value")) != _norm(q.make):
            return False   # make searched as text (q=): the text search also returns other brands
        keys = (self.codes.get("models", {}).get(q.make) or {}) if q.make else {}
        want = {str(k).lower(): v for k, v in keys.items()}.get(q.model.lower())
        if want:
            return m.get("group_key") in (want if isinstance(want, list) else [want])
        return _norm(q.model) in (_norm(m.get("group_label")), _norm(m.get("value")))

    # --- search -------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            items = self.parse_search(self.net.get(url).text, url)
            for ad in items.get("originalList") or []:
                if ad.get("kind", "AdItem") == "AdItem" and self.model_match(q, ad):
                    yield self.card(ad)
            if not items.get("originalList") or page >= int(items.get("totalPages") or 1):
                break

    def parse_search(self, page: str, url: str = "") -> dict:
        try:
            items = next_data(page)["props"]["pageProps"]["initialState"]["items"]
        except (TypeError, KeyError):
            raise Blocked("no-next-data", site=self.id, url=url) from None
        return items

    def card(self, ad: dict) -> Card:
        f, geo, adv = feats(ad), ad.get("geo") or {}, ad.get("advertiser") or {}
        reg = year_month((f.get("/register_date") or {}).get("key")) or (f.get("/year") or {}).get("key")
        imgs = ad.get("images") or []
        return Card(url=(ad.get("urls") or {}).get("default"), site=self.id, site_ref=ad["urn"].rsplit(":", 1)[-1],
                    title=ad.get("subject"), price=num((f.get("/price") or {}).get("key")),
                    km=num((f.get("/mileage_scalar") or {}).get("key")), year=year_of(reg), first_registration=reg,
                    make=(f.get("make") or {}).get("value"), model=(f.get("model") or {}).get("value"),
                    version=(f.get("version") or {}).get("value"), fuel=(f.get("/fuel") or {}).get("value"),
                    power_kw=_kw(f), seller_type="dealer" if adv.get("company") else "private",
                    location=_place(geo), country="IT",
                    thumb=imgs[0]["cdnBaseUrl"] + IMG_RULE if imgs and imgs[0].get("cdnBaseUrl") else None,
                    created=str(ad["date"]).replace(" ", "T") if ad.get("date") else None)

    # --- ad -----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        r = self.net.get(url, ad_id=self.ad_id(url))
        return self.parse_ad(url, r.text)

    def parse_ad(self, url: str, page: str) -> RawAd:
        stream = flight(page)
        i = stream.find('{"ad":{"kind":"AdItem"')
        if i < 0:
            raise Blocked("no-ad-data", site=self.id, url=url)
        ad = json.JSONDecoder().raw_decode(stream, i)[0]["ad"]
        body = ad.get("body")
        if isinstance(body, str) and re.fullmatch(r"\$[0-9a-fA-F]+", body):
            ad["body"] = flight_ref_text(stream, body)   # long texts: an RSC text record, not the "$4a" pointer (11-06)
        c = self.card(ad)
        f, adv, geo = feats(ad), ad.get("advertiser") or {}, ad.get("geo") or {}
        hp = re.search(r"(\d+)\s*(?:CV|PS|hp)", str((f.get("/power") or {}).get("value") or ""), re.I)
        warranty = num((f.get("/warranty_months") or {}).get("key"))
        return RawAd(
            url=c.url or url, site=self.id, site_ref=c.site_ref, title=c.title, price=c.price, make=c.make,
            model=c.model, version=c.version, year=c.year, first_registration=c.first_registration, km=c.km,
            fuel=c.fuel, power_kw=c.power_kw, power_hp=int(hp.group(1)) if hp else None,
            gearbox=(f.get("/gearbox") or {}).get("value"), body=(f.get("/car_type") or {}).get("value"),
            color=(f.get("/color") or {}).get("value"), seats=num((f.get("/seats") or {}).get("value")),
            doors=num(str((f.get("/doors") or {}).get("value") or "").split("/")[-1]), description=ad.get("body"),
            photos=[i["cdnBaseUrl"] + IMG_RULE for i in ad.get("images") or [] if i.get("cdnBaseUrl")],
            seller=Seller(type=c.seller_type, name=adv.get("shopName") or adv.get("name"),
                          id=adv.get("shopId") or adv.get("userId"), city=(geo.get("town") or {}).get("value"),
                          region=(geo.get("region") or {}).get("value"), country="IT"),
            location=c.location, country="IT", created=c.created, status=(ad.get("type") or {}).get("value"),
            contact={"chat": True, "phone": bool(adv.get("phone"))},
            extra={"urn": ad.get("urn"), "has_phone": bool(adv.get("phone")),
                   "condition": (f.get("/vehicle_status") or {}).get("value"),
                   "euro": (f.get("/pollution") or {}).get("value"), "warranty_months": warranty,
                   "stock_ref": (f.get("/ad_code") or {}).get("value")},
            raw={"ad": ad})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        """No phone on the page. reveal=True calls the public contacts endpoint (no login) — one phone slot."""
        if ad.phones or not reveal or not ad.extra.get("has_phone") or not ad.extra.get("urn"):
            return list(ad.phones)
        r = self.net.get(PHONE.format(ad.extra["urn"]), kind="phone", accept="application/json",
                         headers={"Referer": ad.url}, check=False)
        if r.status in (404, 410):
            return []   # seller hides the number
        raise_for(self.id, r)
        num_ = r.json().get("phone_number")
        ad.phones = [it_phone(str(num_))] if num_ else []
        return list(ad.phones)


def _kw(f: dict) -> int | None:
    m = re.search(r"(\d+)\s*kW", str((f.get("/power") or {}).get("value") or ""))
    return int(m.group(1)) if m else None


def _place(geo: dict) -> str | None:
    town, prov = (geo.get("town") or {}).get("value"), (geo.get("city") or {}).get("shortName")
    return f"{town} ({prov})" if town and prov else town or None
