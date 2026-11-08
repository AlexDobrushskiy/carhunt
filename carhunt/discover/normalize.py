"""RawAd/Card → one normalized listing (cardb ListingUpsert shape + flags/facts/options/asks). No scoring.

Rules (data-driven parts live in data/*.yaml):
- Prices stored gross: net asks (+ country VAT) and the ES "precio al contado" over a finance-conditional headline.
- Text is data, not truth: structured site fields first, then title/variant, then description — dealer prose lists
  other models and options of other cars.
- Unknown ≠ no: an option without a cue stays unknown (no row), never "no".
"""
from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from carhunt.discover import _env
from carhunt.sites.model import Card, RawAd

HP_TO_KW = 0.7355


# --- text helpers -------------------------------------------------------------

def fold(text: Any) -> str:
    """ascii-folded lowercase (é → e, ü → u, ß → ss)."""
    t = str(text or "").replace("ß", "ss")
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()


def prose(text: Any) -> str:
    """HTML → one line of plain text."""
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip())


def number(v: Any) -> float | None:
    """'41.900' → 41900, '41.900,50' → 41900.5, '299.0' → 299 (decimal = 1–2 trailing digits after the last sep)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^0-9.,]", "", str(v or ""))
    if not s:
        return None
    dec = re.search(r"[.,](\d{1,2})$", s)
    if dec:
        s = s[:dec.start()].replace(".", "").replace(",", "") + "." + dec.group(1)
    else:
        s = s.replace(".", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _rx(pattern: str) -> re.Pattern:
    return re.compile(re.sub(r"\s*\n\s*", "", pattern.strip()))


def keywords() -> dict:
    return _env.data("keywords")


def flag_match(name: str, text: str) -> bool:
    return bool(_rx(keywords()["flags"][name]["match"]).search(text))


# --- prices -------------------------------------------------------------------

def vat_rate(country: str | None) -> float | None:
    r = _env.data("vat").get((country or "").upper())
    return float(r) if r is not None else None


def gross_of(net: float, country: str | None) -> tuple[int | None, float | None]:
    rate = vat_rate(country)
    return (round(net * (1 + rate / 100)), rate) if rate is not None else (None, None)


def cash_price(text: str) -> int | None:
    """ES 'precio al contado: 41.780 €' → 41780. All matches must agree (a second 'ejemplo' price = conflict)."""
    vals = set()
    for m in _rx(keywords()["cash_price"]["match"]).finditer(fold(prose(text))):
        v = number(next(g for g in m.groups() if g))
        if v is not None and v >= 1000:
            vals.add(round(v))
    return vals.pop() if len(vals) == 1 else None


# --- power / drive / fuel -----------------------------------------------------

_CHARGE_CTX = re.compile(r"(?:\bdc|charg\w*|lade\w*|laad\w*|recharge|carga|ricarica|carregamento)\W{0,3}$")


def advertised_power_kw(title: str, desc: str = "") -> int | None:
    """Motor power from title/variant text; description only via an explicit 'power: N kW' label.

    kW and hp must agree within 1 kW. Charging numbers ('DC 135 kW') are skipped. A kW < 100 that disagrees with
    the hp figure is a battery written as kW ('77kw 204CV') → hp wins.
    """
    t = fold(title)
    hp = re.search(r"\b(\d{2,4})\s*(?:pk|ps|ch|cv|hp|bhp)\b", t)
    hp_kw = round(int(hp.group(1)) * HP_TO_KW) if hp else None
    kws = []
    for m in re.finditer(r"\b(\d{2,3}(?:[.,]\d+)?)\s*kw\b(?!h)", t):
        if _CHARGE_CTX.search(t[max(0, m.start() - 20):m.start()]):
            continue
        kws.append(round(float(m.group(1).replace(",", "."))))
    if kws:
        if hp_kw is None:
            return kws[0]
        agree = [k for k in kws if abs(k - hp_kw) <= 1]
        if agree:
            return agree[0]
        return hp_kw if all(k < 100 for k in kws) else None
    if hp_kw:
        return hp_kw
    m = re.search(r"\b(?:vermogen|puissance|potencia|potenza|leistung|potencia|power)\s*[:=-]?\s*(\d{2,4})\s*"
                  r"(kw|pk|ps|ch|cv|hp)\b(?!h)", fold(desc))
    if m and not _CHARGE_CTX.search(fold(desc)[max(0, m.start() - 20):m.start()]):
        return int(m.group(1)) if m.group(2) == "kw" else round(int(m.group(1)) * HP_TO_KW)
    return None


def fuel_of(label: Any) -> str | None:
    t = fold(label).strip()
    if not t:
        return None
    for fuel, rx in keywords()["fuel"]["map"]:
        if re.search(rx, t):
            return fuel
    return None


def drive_label(value: Any) -> str | None:
    """A site's structured drive label → fwd/rwd/awd."""
    t = fold(value).strip()
    if not t:
        return None
    for drive, labels in keywords()["drive"]["labels"].items():
        if t in labels:
            return drive
    up = t.upper()
    return {"FRONT": "fwd", "REAR": "rwd", "FOUR": "awd", "ALL": "awd"}.get(up)


def drive_from_text(text: str) -> str | None:
    d = keywords()["drive"]
    t = fold(text)
    for drive in ("awd", "rwd", "fwd"):
        if re.search(d[f"text_{drive}"], t):
            return drive
    return None


# --- location -----------------------------------------------------------------

def postcodes_of(*values: Any) -> list[str]:
    out = []
    for v in values:
        if v is None:
            continue
        s = str(v)
        for m in re.finditer(r"\b(\d{4,5}|2[AB]\d{3})(?:-\d{3})?\b", s):
            out.append(m.group(1))
    return out


def region_of(country: str | None, postcodes: list[str], places: list[str]) -> str | None:
    """ISO 3166-2 region from postcode (authoritative when present), else from place names in location fields."""
    regions = {k: v for k, v in _env.data("regions").items() if v["country"] == (country or "").upper()}
    if postcodes:
        for code in postcodes:
            for rid, r in regions.items():
                if any(re.match(rx, code) for rx in r["postcode"]):
                    return rid
        return None
    text = " ".join(fold(p) for p in places if p)
    for rid, r in regions.items():
        if any(re.search(rf"\b{re.escape(p)}\b", text) for p in r["places"]):
            return rid
    return None


# --- phones -------------------------------------------------------------------

def canonical_phone(value: Any, country: str | None) -> str:
    """E.164 digits without '+' (cardb Contact.value). '00…'/'+…' are international already."""
    raw = str(value or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        return digits[2:]
    if "+" in raw:
        return digits
    rule = _env.data("phone").get((country or "").upper())
    if not rule or not digits:
        return digits
    cc = rule["cc"]
    if rule.get("keep0"):           # IT: 39 + national number incl. a landline's 0
        if digits.startswith(cc + "0") or (digits.startswith(cc) and len(digits) > 10):
            return digits           # 39 + landline 0… is already international
        return cc + digits
    if rule.get("national_len") and len(digits) == rule["national_len"]:
        return cc + digits
    if rule.get("trunk0") and digits.startswith("0"):
        return cc + digits[1:]
    if digits.startswith(cc) and len(digits) > 9:
        return digits
    return digits


# --- reg date -----------------------------------------------------------------

def reg_date(first_registration: Any, year: Any = None) -> tuple[str | None, bool]:
    """→ ('YYYY-MM', year_only). 'MM/YYYY' and 'YYYY-M' accepted; year-only sources give 'YYYY-01' + year_only."""
    s = str(first_registration or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})", s) or None
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}", False
    m = re.match(r"^(\d{1,2})[/.-](\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}", False
    m = re.match(r"^(\d{4})$", s) or (re.match(r"^(\d{4})$", str(year)) if year else None)
    if m:
        return f"{m.group(1)}-01", True
    return None, False


# --- options + facts from text ------------------------------------------------

def cue_hit(match: str, text: str, unless: str | None = None) -> bool:
    """`match` found in a clause (text between . ; ! ?) that `unless` does not also match."""
    rx, un = _rx(match), (_rx(unless) if unless else None)
    for m in rx.finditer(text):
        if un is None:
            return True
        a = max(text.rfind(c, 0, m.start()) for c in ".;!?") + 1
        ends = [i for i in (text.find(c, m.end()) for c in ".;!?") if i >= 0]
        if not un.search(text[a:min(ends) if ends else len(text)]):
            return True
    return False


def text_options(text: str) -> dict[str, str]:
    t = fold(prose(text))
    out: dict[str, str] = {}
    for key, rules in _env.data("options").items():
        if rules.get("absent") and cue_hit(rules["absent"], t):
            out[key] = "no"
        elif rules.get("present") and cue_hit(rules["present"], t, rules.get("unless")):
            out[key] = "yes"
    return out


def text_facts(text: str) -> dict[str, str]:
    t = fold(prose(text))
    k = keywords()["facts"]
    f: dict[str, str] = {}
    m = _rx(k["owners"]["match"]).search(t)
    if m:
        f["owners"] = m.group(1) if m.group(1).isdigit() else "1"
    if _rx(k["accident_free"]["match"]).search(t):
        f["accident_free"] = "yes (ad states)"
    if _rx(k["service_history"]["match"]).search(t):
        f["service_history"] = "stated in ad"
    m = _rx(k["soh"]["match"]).search(t)
    if m:
        f["soh"] = m.group(1).replace(",", ".") + "%"
    m = _rx(k["ac_onboard_kw"]["match"]).search(t)
    if m:
        f["ac_onboard_kw"] = next(g for g in m.groups() if g)
    return f


# --- the normalized listing ---------------------------------------------------

@dataclass
class Listing:
    url: str
    site: str
    site_ref: str
    title: str | None = None
    price: int | None = None
    price_note: str | None = None
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    reg_date: str | None = None
    year: int | None = None
    km: int | None = None
    fuel: str | None = None
    battery_net_kwh: float | None = None
    gearbox: str | None = None
    power_kw: int | None = None
    drive: str | None = None
    seats: int | None = None
    colour: str | None = None
    vin: str | None = None
    plate: str | None = None
    country: str | None = None
    city: str | None = None
    postcodes: list[str] = field(default_factory=list)
    region: str | None = None
    lat: float | None = None
    lon: float | None = None
    distance_km: int | None = None                      # road km (sent to cardb)
    distance_est_km: int | None = None                  # road km or great-circle estimate (scope only)
    seller_type: str = "unknown"
    seller_name: str | None = None
    phones: list[str] = field(default_factory=list)
    whatsapp: str | None = None
    photos: list[str] = field(default_factory=list)
    description: str = ""
    options: dict[str, tuple[str, str]] = field(default_factory=dict)   # key → (yes|no, evidence source)
    facts: dict[str, tuple[str, str]] = field(default_factory=dict)     # key → (value, evidence source)
    flags: set[str] = field(default_factory=set)        # lease_transfer, damaged, reseller, net_price, …
    family: str | None = None                           # the search.models entry it matched ("Make Model")
    tier: int | None = None
    thin: bool = False
    asks: list[str] = field(default_factory=list)
    detail: bool = True                                 # False = built from a search card only
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def fact(self, key: str, value: Any, source: str = "ad_text") -> None:
        if value not in (None, ""):
            self.facts[key] = (str(value), source)

    def opt(self, key: str, value: str, source: str = "ad_text") -> None:
        self.options.setdefault(key, (value, source))

    def text(self, *, description: bool = True) -> str:
        parts = [self.make, self.model, self.variant, self.title]
        if description:
            parts.append(self.description)
        return " ".join(str(p) for p in parts if p)

    def to_upsert(self) -> dict[str, Any]:
        """cardb `POST /listings/upsert` body. No photo_urls: photos go in after the upsert (stock-gallery merges)."""
        contacts = [{"kind": "phone", "value": p} for p in self.phones]
        if self.whatsapp:
            contacts.append({"kind": "whatsapp", "value": self.whatsapp})
        if not contacts:
            contacts.append({"kind": "site_chat", "value": self.url})
        seller = {"type": self.seller_type, "name": self.seller_name, "city": self.city, "contacts": contacts}
        powertrain = {k: v for k, v in {"fuel": self.fuel, "battery_net_kwh": self.battery_net_kwh,
                                        "gearbox": self.gearbox}.items() if v is not None}
        body: dict[str, Any] = {
            "url": self.url, "site": self.site, "title": self.title, "price": self.price, "price_vat": "gross",
            "price_note": self.price_note, "make": self.make, "model": self.model, "variant": self.variant,
            "reg_date": self.reg_date, "km": self.km, "power_kw": self.power_kw, "drive": self.drive,
            "seats": self.seats, "colour": self.colour, "vin": self.vin, "plate": self.plate,
            "country": self.country, "city": self.city, "lat": self.lat, "lon": self.lon,
            "distance_km": self.distance_km, "powertrain": powertrain or None,
            "seller": {k: v for k, v in seller.items() if v not in (None, "", [])},
            "options": {k: {"value": v, "source": s} for k, (v, s) in self.options.items()} or None,
            "facts": {k: {"value": v, "source": s} for k, (v, s) in self.facts.items()} or None,
            "raw": self.raw or None,
        }
        if self.price is None:
            body.pop("price_vat")
        return {k: v for k, v in body.items() if v not in (None, "", [], {})}

    def summary(self) -> dict[str, Any]:
        return {"url": self.url, "family": self.family, "price": self.price, "km": self.km, "reg": self.reg_date,
                "country": self.country, "city": self.city, "seller": self.seller_type, "drive": self.drive,
                "power_kw": self.power_kw, "thin": self.thin, "flags": sorted(self.flags),
                "options": {k: v for k, (v, _) in self.options.items()}}


# --- build --------------------------------------------------------------------

def from_ad(ad: RawAd) -> Listing:
    s = ad.seller
    loc = [ad.location, s.city, s.region]
    reg, year_only = reg_date(ad.first_registration, ad.year)
    lst = Listing(url=ad.url, site=ad.site, site_ref=ad.site_ref, title=ad.title, make=ad.make, model=ad.model,
                  variant=ad.version, reg_date=reg, km=_int(ad.km), fuel=fuel_of(ad.fuel), gearbox=_gearbox(ad.gearbox),
                  battery_net_kwh=ad.battery_kwh, power_kw=_int(ad.power_kw), seats=ad.seats, colour=ad.color,
                  vin=(ad.vin or None), plate=ad.plate, country=(ad.country or s.country or "").upper() or None,
                  city=s.city or ad.location, seller_type=s.type or "unknown", seller_name=s.name,
                  photos=list(ad.photos), description=prose(ad.description), whatsapp=ad.whatsapp,
                  raw=ad.raw or {})
    lst.postcodes = postcodes_of(s.postcode, ad.extra.get("postcode"), ad.location)
    lst.region = region_of(lst.country, lst.postcodes, loc)
    if year_only:
        lst.fact("reg_precision", "year only in source; month is a placeholder")
    if ad.power_kw is None and ad.power_hp:
        lst.power_kw = round(ad.power_hp * HP_TO_KW)
    lst.phones = sorted({canonical_phone(p, lst.country) for p in ad.phones if len(re.sub(r"\D", "", str(p))) >= 8})
    if lst.whatsapp:
        lst.whatsapp = canonical_phone(lst.whatsapp, lst.country)
    for k in ("owners",):
        if ad.owners is not None:
            lst.fact(k, ad.owners, "ad_spec")
    if ad.accident_free is not None:
        lst.fact("accident_free", "yes (ad spec)" if ad.accident_free else "no (ad spec)", "ad_spec")
    if ad.service_history:
        lst.fact("service_history", "ad spec", "ad_spec")
    stock = ad.extra.get("stock_ref") or ad.extra.get("dealer_stock_ref")
    if stock:
        lst.fact("dealer_stock_ref", stock, "ad_spec")
    _price(lst, ad.price, ad.price_is_net)
    _structured_options(lst, ad.equipment)
    _drive(lst, ad.drive)
    _common(lst)
    return lst


def from_card(card: Card) -> Listing:
    """Card-only listing (no detail load): market picture for deprioritised families."""
    reg, year_only = reg_date(card.first_registration, card.year)
    lst = Listing(url=card.url, site=card.site, site_ref=card.site_ref, title=card.title, make=card.make,
                  model=card.model, variant=card.version, reg_date=reg, km=_int(card.km), fuel=fuel_of(card.fuel),
                  power_kw=_int(card.power_kw), country=(card.country or "").upper() or None, city=card.location,
                  seller_type=card.seller_type, detail=False)
    lst.phones = sorted({canonical_phone(p, lst.country) for p in card.phones})
    lst.postcodes = postcodes_of(card.location)
    lst.region = region_of(lst.country, lst.postcodes, [card.location])
    if year_only:
        lst.fact("reg_precision", "year only in source; month is a placeholder")
    lst.fact("evidence_scope", "search card only; no detail/gallery load", "agent_inference")
    _price(lst, card.price, card.price_is_net)
    _drive(lst, None)
    _common(lst)
    return lst


def _int(v: Any) -> int | None:
    n = number(v)
    return round(n) if n is not None else None


def _gearbox(v: Any) -> str | None:
    t = fold(v)
    if not t:
        return None
    if re.search(r"auto|dsg|cvt|automat", t):
        return "automatic"
    if re.search(r"manu|schalt|handgesch", t):
        return "manual"
    return None


def _price(lst: Listing, price: Any, is_net: bool | None) -> None:
    p = number(price)
    if p is None:
        return
    p = round(p)
    if is_net:
        gross, rate = gross_of(p, lst.country)
        if gross is None:
            lst.flags.add("net_price_unknown_vat")
            lst.fact("source_net_price_eur", p)
            lst.price = None
            return
        lst.price = gross
        lst.price_note = f"gross = net {p} + {rate:g} % VAT ({lst.country}); confirm the payable ask"
        lst.fact("price_basis", "net in source; gross derived")
        lst.fact("source_net_price_eur", p)
        lst.flags.add("net_price")
        return
    lst.price = p


def _structured_options(lst: Listing, equipment: list[str]) -> None:
    keys = set(_env.data("options"))
    for item in equipment or []:
        if item in keys:
            lst.opt(item, "yes", "ad_spec")
        else:
            for k, v in text_options(item).items():
                if v == "yes":
                    lst.opt(k, "yes", "ad_spec")


def _drive(lst: Listing, site_label: Any) -> None:
    src = drive_label(site_label)
    if src:
        lst.drive = src
        lst.fact("drive_source", f"site field: {site_label}", "ad_spec")
    title_awd = drive_from_text(lst.text(description=False)) == "awd"
    if title_awd:
        lst.drive = "awd"      # 4MOTION/quattro/AWD in the title beats everything
    if not lst.drive:
        lst.drive = drive_from_text(lst.description) if lst.detail else None


def _common(lst: Listing) -> None:
    """Text-derived rules shared by card and ad listings."""
    head = lst.text(description=False)
    full = fold(lst.text())
    if lst.power_kw is None:
        lst.power_kw = advertised_power_kw(head, lst.description)
        if lst.power_kw:
            lst.fact("power_kw_source", "advertised in title/description")
    for name in ("lease_transfer", "damaged", "history_abroad"):
        if flag_match(name, full):
            lst.flags.add(name)
    if "damaged" in lst.flags:
        lst.fact("deal_flag", "suspect: damage wording in ad")
    if "history_abroad" in lst.flags:
        lst.fact("history_flag", "PL/LT/LV/EE mentioned; verify history")
    if lst.seller_type == "private" and flag_match("reseller", full):
        lst.seller_type = "reseller"
        lst.fact("seller_note", "private-labelled ad sells on behalf of someone else")
    if lst.country == "ES" and "net_price" not in lst.flags and lst.description:
        cash = cash_price(lst.description)
        if cash is not None and cash != lst.price:
            if lst.price is not None:
                lst.fact("headline_conditional_price_eur", lst.price)
            lst.price = cash
            lst.fact("price_basis", "explicit cash ask in ad text")
    if "net_price" not in lst.flags and lst.price and _rx(keywords()["net_ask"]["match"]).search(fold(lst.description)):
        gross, rate = gross_of(lst.price, lst.country)
        if gross:
            lst.fact("source_net_price_eur", lst.price)
            lst.price_note = f"gross = net {lst.price} + {rate:g} % VAT ({lst.country}); confirm the payable ask"
            lst.price = gross
            lst.fact("price_basis", "net ask stated in text; gross derived")
            lst.flags.add("net_price")
    elif "net_price" not in lst.flags and flag_match("net_wording", full):
        lst.fact("price_basis_review", "net/export wording in ad; confirm the gross ask")
    for k, v in text_options(lst.text()).items():
        lst.opt(k, v, "ad_text")
    for k, v in text_facts(lst.text()).items():
        if k not in lst.facts:
            lst.fact(k, v)
    for name, rule in keywords().get("vin_wmi_flags", {}).items():
        if lst.vin and lst.vin.upper()[:3] in rule["wmi"]:
            lst.flags.add(f"{name}_vin")
            lst.fact("vin_origin", f"{name} WMI {lst.vin.upper()[:3]}: {rule['why']}")
    if lst.reg_date:
        lst.year = int(lst.reg_date[:4])
