"""coches.net (Spain): Imperva ABP. Two read routes, same numeric make/model ids (codes.yaml):

- gateway: the site's own JSON API `web.gw.coches.net` (`POST /search/listing`, `GET /details/<id>`) through a
  Spanish exit (`country="ES"`), pace kind `api`, ≥12 s apart. Used whenever a Spanish proxy is configured.
- page: plain HTTP (never a browser) with the data in `window.__INITIAL_PROPS__`, pace kind `load`, ≤2 loads per
  rolling hour for every agent on the IP. Fallback when no Spanish proxy is available.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from collections.abc import Callable, Iterator
from typing import Any

from carhunt.access.errors import PaceExceeded, ProxyUnavailable
from carhunt.sites._net import JSON, raise_for
from carhunt.sites.base import BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num, window_var, year_month
from carhunt.sites.model import Card, Liveness, RawAd, SearchQuery, Seller

ORIGIN = "https://www.coches.net"
GW = "https://web.gw.coches.net"
GW_HEADERS = {"Origin": ORIGIN, "Referer": ORIGIN + "/", "X-Adevinta-Channel": "web-desktop",
              "X-Schibsted-Tenant": "coches", "Content-Type": "application/json"}
API_MAX_PER_RUN = 60          # gateway reads per run (sweep allowance 11-07); Net counts only kind `load`
HP_TO_KW = 0.7355


def phone_e164(v: Any) -> str | None:
    digits = re.sub(r"\D", "", str(v or ""))
    if len(digits) == 9:
        return "+34" + digits
    return "+" + digits if len(digits) == 11 and digits.startswith("34") else (digits or None)


def _kw(hp: Any) -> int | None:
    h = num(hp)
    return round(h * HP_TO_KW) if h else None


def _label(v: str | None) -> str | None:
    """"SEARCH_BOX_SELECT_DRIVEN_WHEELS_REAR" / "COMMON.COLOR_RED" → "rear" / "red"."""
    return re.split(r"[._](?:WHEELS|COLOR|TRANSMISSION)_", v)[-1].lower() if v else None


def _vin_from(report_url: str | None) -> str | None:
    m = re.search(r"[?&]vin=([A-HJ-NPR-Z0-9]{17})\b", report_url or "")
    return m.group(1) if m else None


class Plugin(BaseSite):
    pkg = "coches_net"

    def __init__(self, net: Any = None):
        super().__init__(net)
        self.api_calls = 0
        self._page_loads: list[float] = []

    # --- query (codes.yaml only) ---------------------------------------------
    def vehicles(self, q: SearchQuery) -> list[dict]:
        """[{make, makeId, model, modelId}] — one user model can span several site models (Q4 + Q4 Sportback)."""
        if not q.make:
            return []
        makes = {k.lower(): v for k, v in (self.codes.get("makes") or {}).items()}
        mk = makes.get(q.make.lower())
        if mk is None:
            raise Unsupported(f"coches.net: no make id for {q.make} — add it to carhunt/sites/coches_net/codes.yaml")
        make_id, make_label = mk
        if not q.model:
            return [{"make": make_label, "makeId": make_id, "model": None, "modelId": 0}]
        models = {k.lower(): v for k, v in (self.codes.get("models") or {}).items()}.get(q.make.lower()) or {}
        ms = {str(k).lower(): v for k, v in models.items()}.get(q.model.lower())
        if not ms:
            raise Unsupported(f"coches.net: no model id for {q.make}/{q.model} — add it to "
                              f"carhunt/sites/coches_net/codes.yaml")
        return [{"make": make_label, "makeId": make_id, "model": label, "modelId": mid} for mid, label in ms]

    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        p: list[tuple[str, Any]] = []
        for i, v in enumerate(self.vehicles(q)):
            p += [(f"MakeIds[{i}]", v["makeId"]), (f"ModelIds[{i}]", v["modelId"])]
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p.append(("Fueltype2List", self.code("fuel", q.fuel, slug=False)))
        for key, val in (("MinYear", q.year_min), ("MaxYear", q.year_max), ("MaxKms", q.km_max),
                         ("MinPrice", q.price_min), ("MaxPrice", q.price_max)):
            if val:
                p.append((key, val))
        if q.seller != "any":
            p.append(("st", self.need_code("seller", q.seller)))
        p += list(self.codes["sort"][q.sort]["page"].items())
        if page > 1:
            p.append(("pg", page))
        p += list(q.extra.items())
        return f"{ORIGIN}/segunda-mano/?{urllib.parse.urlencode(p)}"

    def search_body(self, q: SearchQuery, page: int = 1) -> dict:
        """The full filter set the site's app posts (a shorter body got 400 on 11-05)."""
        rng = lambda lo=None, hi=None: {"from": lo, "to": hi}  # noqa: E731
        fuel = self.code("fuel", q.fuel, slug=False) if q.fuel else None
        filters: dict[str, Any] = {
            "price": rng(q.price_min, q.price_max), "fee": rng(), "commitmentMonths": [], "priceRank": [],
            "batteryCapacity": rng(), "bodyTypeIds": [], "categories": {"category1Ids": [self.codes["category1"]]},
            "chargingTimeFastMode": rng(), "chargingTimeStandardMode": rng(), "contractId": 0, "drivenWheelsIds": [],
            "electricAutonomy": rng(), "entry": None, "environmentalLabels": [], "equipments": [],
            "fuelTypeIds": [int(fuel)] if fuel else [], "hasPriceDrop": None, "hasPhoto": None,
            "hasOnlineFinancing": None, "hasReservation": None, "hasStock": None, "hasWarranty": None, "hp": rng(),
            "isCertified": False, "km": rng(None, q.km_max), "luggageCapacity": rng(), "maxTerms": None,
            "onlyPeninsula": False, "offerTypeIds": list(self.codes["offer_types"]), "priceDrop": None,
            "provinceIds": [], "rating": rng(), "searchText": None,
            "sellerTypeId": int(self.need_code("seller", q.seller)) if q.seller != "any" else 0,
            "subscriptionVehicleState": None, "targetBuyer": None, "transmissionTypeId": 0,
            "vehicles": self.vehicles(q), "year": rng(q.year_min, q.year_max)}
        for k, v in q.extra.items():   # raw gateway filters: JSON values ("[28]", "true") or plain strings
            try:
                filters[k] = json.loads(v)
            except (TypeError, ValueError):
                filters[k] = v
        return {"pagination": {"page": page, "size": self.codes["page_size"]},
                "sort": dict(self.codes["sort"][q.sort]["gateway"]), "filters": filters}

    # --- transport -----------------------------------------------------------
    def _api(self, url: str, *, body: dict | None = None, ad_id: str | None = None) -> Any:
        if self.api_calls >= API_MAX_PER_RUN:
            raise PaceExceeded(self.id, "api", reason=f"gateway allowance {API_MAX_PER_RUN}/run")
        self.api_calls += 1
        data = json.dumps(body).encode() if body is not None else None
        r = self.net.get(url, kind="api", accept=JSON, headers=GW_HEADERS, country="ES", ad_id=ad_id, data=data,
                         method="POST" if data is not None else None)
        try:
            return r.json()
        except ValueError as e:
            raise Blocked("gateway-not-json", site=self.id, url=url) from e

    def _page_gate(self) -> None:
        """≤2 page loads per rolling hour even without the shared ledger (5th load at 10 s pace = bot page, 11-03)."""
        per_hour = int((self.meta.get("pace") or {}).get("max_loads_per_hour") or 2)
        now = time.monotonic()
        self._page_loads = [t for t in self._page_loads if now - t < 3600]
        if len(self._page_loads) >= per_hour:
            raise PaceExceeded(self.id, "load", reason=f"max_loads_per_hour={per_hour} (page route)")
        self._page_loads.append(now)

    def _page(self, url: str, ad_id: str | None = None) -> tuple[dict, str | None]:
        self._page_gate()
        r = self.net.get(url, ad_id=ad_id)
        props = window_var(r.text, "__INITIAL_PROPS__") if r.text else None
        return props if isinstance(props, dict) else {}, r.final_url

    def _with_fallback(self, api: Callable[[], Any], page: Callable[[], Any]) -> Any:
        try:
            return api()
        except ProxyUnavailable:
            return page()

    # --- search ----------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        """Gateway when a Spanish exit exists, else the page route. Order = the site's relevance (promoted rows
        first, then newest): there is no creation-date sort, so a sweep cursor needs every page."""
        yielded = False
        try:
            for c in self._search_api(q):
                yielded = True
                yield c
        except ProxyUnavailable:
            if yielded:
                raise
            yield from self._search_pages(q)

    def _search_api(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, max(q.max_pages, 1) + 1):
            d = self._api(f"{GW}/search/listing", body=self.search_body(q, page))
            if not isinstance(d, dict) or "items" not in d:
                raise Blocked("gateway-no-items", site=self.id, url=f"{GW}/search/listing")
            yield from self.parse_api_search(d)
            if page >= int((d.get("meta") or {}).get("totalPages") or 0):
                break

    def _search_pages(self, q: SearchQuery) -> Iterator[Card]:
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            props, _ = self._page(url)
            res = props.get("initialResults")
            if not isinstance(res, dict):
                raise Blocked("no-initial-props", site=self.id, url=url)
            yield from self.parse_page_search(props)
            if page >= int(res.get("totalPages") or 0):
                break

    def parse_api_search(self, d: dict) -> Iterator[Card]:
        """Gateway `/search/listing` answer: organic `items`, promoted `paidItems` (flagged sponsored)."""
        for paid, rows in ((False, d.get("items") or []), (True, d.get("paidItems") or [])):
            for it in rows:
                price = it.get("price") if isinstance(it.get("price"), dict) else {}
                seller = it.get("seller") or {}
                pro = bool(it.get("isProfessional", seller.get("isProfessional")))
                imgs = [x.get("url") for x in it.get("resources") or [] if x.get("type") == "IMAGE" and x.get("url")]
                yield self._card(it, price=num(price.get("amount")), has_taxes=price.get("hasTaxes"), pro=pro,
                                 thumb=imgs[0] if imgs else None, sponsored=paid)

    def parse_page_search(self, props: dict) -> Iterator[Card]:
        """List page `initialResults.items` (35/page); `isTop` = promoted row."""
        for it in (props.get("initialResults") or {}).get("items") or []:
            photos = it.get("photos") or []
            yield self._card(it, price=num(it.get("price")), has_taxes=it.get("includesTaxes"),
                             pro=bool(it.get("isProfessional")), thumb=photos[0] if photos else it.get("img"),
                             sponsored=bool(it.get("isTop")))

    def _card(self, it: dict, *, price: int | None, has_taxes: Any, pro: bool, thumb: str | None,
              sponsored: bool) -> Card:
        loc = it.get("location") or {}
        ph = phone_e164(it.get("phone")) if not it.get("hidePhone") else None
        year = num(it.get("year"))
        return Card(url=urllib.parse.urljoin(ORIGIN + "/", it["url"]), site=self.id, site_ref=str(it["id"]),
                    title=it.get("title"), price=price, price_is_net=(pro and has_taxes is False) or None,
                    km=num(it.get("km")), year=year, first_registration=str(year) if year else None,
                    make=it.get("make"), model=it.get("model"), fuel=it.get("fuelType"), power_kw=_kw(it.get("hp")),
                    seller_type="dealer" if pro else "private",
                    location=", ".join(x for x in (loc.get("cityLiteral"), loc.get("mainProvince")) if x) or None,
                    country="ES", thumb=thumb, phones=[ph] if ph else [], sponsored=sponsored,
                    created=it.get("creationDate") or it.get("publishedDate"))

    # --- ad --------------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        aid = self.ad_id(url)
        if not aid:
            raise Unsupported(f"coches.net: no ad id in {url}")
        return self._with_fallback(lambda: self.parse_api_ad(url, self._api(f"{GW}/details/{aid}", ad_id=aid)),
                                   lambda: self._ad_page(url, aid))

    def _ad_page(self, url: str, aid: str) -> RawAd:
        props, final = self._page(url, ad_id=aid)
        gone_rx = (self.meta.get("liveness") or {}).get("gone_redirect")
        if final and gone_rx and re.search(gone_rx, final):
            raise Gone(url, f"redirect to {final[:100]}")
        if not props.get("ad"):
            if props.get("hasComeFromAdNotAvailable"):
                raise Gone(url, "list page: ad not available")
            raise Blocked("no-initial-props", site=self.id, url=url)
        return self.parse_page_ad(url, props)

    def parse_api_ad(self, url: str, d: dict) -> RawAd:
        """Gateway `/details/<id>`: ad.vehicle.specs (power = CV), privateSeller | professionalSeller, vehicleSpecs."""
        a = d.get("ad") or {}
        if not a.get("id"):
            raise Blocked("gateway-no-ad", site=self.id, url=url)
        v = a.get("vehicle") or {}
        sp = v.get("specs") or {}
        price = a.get("price") or {}
        priv, pro = d.get("privateSeller"), d.get("professionalSeller")
        if pro:
            c, loc = pro.get("contact") or {}, pro.get("location") or {}
            phones = [] if c.get("hidePhone") else [p for p in map(phone_e164, (c.get("phone"), c.get("phone1"))) if p]
            seller = Seller(type="dealer", name=pro.get("name"), id=str(pro.get("id") or "") or None,
                            city=loc.get("city"), postcode=loc.get("zipCode"), region=loc.get("province"),
                            country="ES", url=pro.get("stockPageUrl"))
            whatsapp = phones[0] if phones and c.get("hasWhatsappProduct") else None
        else:
            p = priv or (a.get("privateSeller") or {})
            ph = phone_e164(p.get("phone")) if not p.get("hidePhone") else None
            phones, whatsapp = [ph] if ph else [], None
            seller = Seller(type="private" if p else "unknown", name=p.get("name"),
                            id=str(p.get("userId") or "") or None, postcode=p.get("zipCode"), country="ES")
        reg = year_month(v.get("plateRegistrationDate")) or (str(v["year"]) if v.get("year") else None)
        es = ((d.get("vehicleSpecs") or {}).get("electricFeatures") or {}).get("powerSource") or {}
        batt = (es.get("maximumBatteryKWH") or {}).get("value")
        equipment = [i for g in sp.get("optionalEquipment") or [] for i in g.get("items") or []]
        fuel_id = sp.get("fuelTypeId")
        return RawAd(
            url=url, site=self.id, site_ref=str(a["id"]), title=a.get("title"), price=num(price.get("price")),
            price_is_net=(bool(pro) and price.get("hasTaxes") is False) or None, make=sp.get("make"),
            model=sp.get("model"), version=sp.get("version"), year=num(v.get("year")), first_registration=reg,
            km=num(v.get("km")), fuel=(self.codes.get("fuel_names") or {}).get(fuel_id), power_kw=_kw(sp.get("power")),
            power_hp=num(sp.get("power")), drive=(self.codes.get("drive") or {}).get(sp.get("drivenWheelsId")),
            gearbox=(self.codes.get("gearbox") or {}).get(sp.get("transmissionTypeId")),
            seats=num(sp.get("seatingCapacity")), doors=num(sp.get("doors")),
            battery_kwh=float(batt) if batt and re.fullmatch(r"\d+(\.\d+)?", str(batt)) else None,
            vin=v.get("vin") or None, description=a.get("description") or None, equipment=equipment,
            photos=[p if isinstance(p, str) else p.get("url") for p in a.get("photos") or [] if p],
            phones=phones, whatsapp=whatsapp, seller=seller, location=seller.city or seller.region, country="ES",
            created=a.get("creationDate"), status=a.get("status"),
            extra={"publication_date": a.get("publicationDate"), "warranty": (v.get("warranty") or {}).get("text"),
                   "body_type_id": sp.get("bodyTypeId"), "color_id": v.get("colorId"),
                   "tax_type_id": price.get("taxTypeId"), "has_vehicle_history": v.get("hasVehicleHistory")},
            raw=d)

    def parse_page_ad(self, url: str, props: dict) -> RawAd:
        """Ad page `__INITIAL_PROPS__`: ad, seller {isDealer, dealer | user}, vehicleInfo, groupedSpecifications."""
        a, s = props.get("ad") or {}, props.get("seller") or {}
        vi = props.get("vehicleInfo") or {}
        spec = vi.get("specifications") or {}
        eng = (props.get("groupedSpecifications") or {}).get("engine") or {}
        dealer = s.get("dealer") if isinstance(s.get("dealer"), dict) else None
        user = s.get("user") if isinstance(s.get("user"), dict) else {}
        if dealer:
            loc = dealer.get("location") or {}
            ph = phone_e164(dealer.get("phoneNumber") or a.get("phone")) if not a.get("hidePhone") else None
            seller = Seller(type="dealer", name=dealer.get("name"), id=str(dealer.get("id") or "") or None,
                            city=loc.get("city"), postcode=loc.get("postalCode"), region=loc.get("province"),
                            country="ES", url=dealer.get("stockPageUrl"))
            whatsapp = ph if ph and dealer.get("hasWhatsappProduct") else None
        else:   # private: the ad page's phone is empty even when the seller shows one → phone(reveal=True)
            ph = phone_e164(a.get("phone") or user.get("phone")) if not a.get("hidePhone") else None
            seller = Seller(type="private" if s.get("isPrivate") or user else "unknown", name=user.get("name"),
                            id=str(user.get("userId") or "") or None, region=user.get("province"), country="ES")
            whatsapp = None
        desc = a.get("description") or ""
        m = re.search(r"Matriculaci[oó]n\s*:\s*(\d\d)/(20\d\d)", desc, re.I)   # month only ever in the text
        reg = f"{m.group(2)}-{m.group(1)}" if m else (str(a["year"]) if a.get("year") else None)
        eq = vi.get("equipment") or {}
        equipment = [x.get("value") for grp in eq.get("optional") or [] for x in grp.get("descriptions") or []
                     if isinstance(x, dict) and x.get("value")]
        batt = ((spec.get("electricFeatures") or {}).get("batteryCapacity")
                or (eng.get("electricFeatures") or {}).get("batteryCapacity"))
        return RawAd(
            url=url, site=self.id, site_ref=str(a.get("id") or self.ad_id(url)), title=a.get("title"),
            price=num(a.get("price")), price_is_net=(bool(dealer) and a.get("includesTaxes") is False) or None,
            make=a.get("make"), model=a.get("model"), version=a.get("version") or spec.get("version"),
            year=num(a.get("year")), first_registration=reg, km=num(a.get("km")), fuel=a.get("fuelType"),
            power_kw=num(eng.get("kw")) or _kw(spec.get("hp") or eng.get("hp")),
            power_hp=num(spec.get("hp") or eng.get("hp")), drive=_label(a.get("traction")),
            gearbox=_label(a.get("transmissionType")), body=spec.get("bodyType"), color=_label(a.get("color")),
            seats=num(spec.get("seats")), doors=num(spec.get("doors")),
            battery_kwh=float(batt) if batt and re.fullmatch(r"\d+(\.\d+)?", str(batt)) else None,
            vin=_vin_from((props.get("vehicleHistory") or {}).get("reportUrl")), description=desc or None,
            equipment=equipment, photos=[p for p in a.get("photos") or [] if isinstance(p, str)],
            phones=[ph] if ph else [], whatsapp=whatsapp, seller=seller,
            location=seller.city or seller.region or a.get("province"), country="ES", created=a.get("creationDate"),
            extra={"publication_date": a.get("publicationDate"), "warranty": a.get("warrantyText"),
                   "environmental_label": a.get("environmentalLabel"), "traction_text": eng.get("traction")},
            raw=props)

    def is_live(self, url: str) -> Liveness:
        """One page read without redirects (site.yaml `gone_redirect`); counts against the ≤2/h page budget."""
        self._page_gate()
        return super().is_live(url)

    # --- phone -----------------------------------------------------------------
    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        """Page data first. `reveal=True`: the app's own `GET /details/<id>/phone` (no login), Spanish IP only —
        403 from every non-ES client (11-02); 200 {phone} or 204 = the seller hides it (messages only)."""
        if ad.phones or not reveal:
            return list(ad.phones)
        url = f"{GW}/details/{ad.site_ref}/phone"
        # Net.get takes the `phone` pace slot before the request (a 403 still costs it)
        r = self.net.get(url, kind="phone", accept=JSON, headers=GW_HEADERS, country="ES", check=False)
        if r.status == 204:
            return []
        raise_for(self.id, r)
        try:
            ph = phone_e164((r.json() or {}).get("phone"))
        except ValueError as e:
            raise Blocked("phone-not-json", site=self.id, url=url) from e
        return [ph] if ph else []
