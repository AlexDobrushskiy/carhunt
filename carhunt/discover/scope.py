"""Config `search` → keep/drop a normalized listing, with a reason code (`<code>: <detail>`).

Drops are logged to `$CARHUNT_HOME/discover/dispositions.jsonl`, never silent. Unknown values pass (an ad that does
not state km is not out of scope); `partial=True` is the search-card prefilter before a detail load.
Model matching uses make/model/variant/title only, never the description: dealer prose lists other models (2026-11-03).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from carhunt.discover.normalize import Listing, fold

DEFAULT_PRICE_SANITY = {"min_eur": 1000, "max_eur": 250000}


@dataclass(frozen=True)
class Model:
    make: str
    model: str
    tier: int
    rx: re.Pattern
    make_rx: re.Pattern

    @property
    def name(self) -> str:
        return f"{self.make} {self.model}"


MAKE_ALIASES = {"volkswagen": ["vw"], "mercedes-benz": ["mercedes", "mb"], "skoda": ["skoda"],
                "mini": ["bmw mini"], "citroen": ["citroen"]}


def _model_rx(model: str) -> str:
    """'ID.4' → id[\\s.-]*4(?!\\d); 'Q4 e-tron' → q4\\b.{0,25}?e[\\s.-]*tron (words may be split by trim names)."""
    words = []
    for w in fold(model).split():
        runs = re.findall(r"[a-z]+|\d+", w)
        words.append(r"[\s.\-]*".join(re.escape(r) for r in runs))
    body = r"\b.{0,25}?".join(words)
    return rf"(?<![a-z0-9]){body}(?![0-9])"


def models(search: dict) -> list[Model]:
    out = []
    for m in search.get("models") or []:
        make = str(m["make"])
        names = [fold(make)] + MAKE_ALIASES.get(fold(make), [])
        make_rx = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b")
        rx = re.compile(m.get("match") or _model_rx(str(m["model"])))
        out.append(Model(make, str(m["model"]), int(m.get("tier") or 1), rx, make_rx))
    return out


def match_model(lst: Listing, mods: list[Model]) -> Model | None:
    """Structured make/model first, then title/variant."""
    structured = fold(f"{lst.make or ''} {lst.model or ''} {lst.variant or ''}")
    head = fold(f"{lst.make or ''} {lst.title or ''} {lst.variant or ''}")
    for text in (structured, head):
        for m in mods:
            if m.rx.search(text) and (not lst.make or m.make_rx.search(fold(lst.make)) or m.make_rx.search(text)):
                return m
    return None


def _value(lst: Listing, key: str) -> Any:
    if hasattr(lst, key):
        return getattr(lst, key)
    v = lst.facts.get(key)
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.]", "", v[0]))
    except ValueError:
        return v[0]


def _hard_filter(lst: Listing, rule: dict) -> str | None:
    if "flag" in rule:
        if rule.get("exclude") and rule["flag"] in lst.flags:
            return f"flag: {rule['flag']}"
        return None
    key = rule.get("fact") or rule.get("field")
    v = _value(lst, key)
    if v is None:
        return None
    if "min" in rule and isinstance(v, (int, float)) and v < rule["min"]:
        return f"hard_filter: {key} {v:g} < {rule['min']}"
    if "max" in rule and isinstance(v, (int, float)) and v > rule["max"]:
        return f"hard_filter: {key} {v:g} > {rule['max']}"
    if "equals" in rule and str(v) != str(rule["equals"]):
        return f"hard_filter: {key} {v} != {rule['equals']}"
    return None


def check(lst: Listing, cfg: dict, *, partial: bool = False) -> str | None:
    """None = keep; else the drop reason. Sets lst.family/tier on a model match."""
    search = cfg.get("search") or {}
    disc = cfg.get("discover") or {}
    home = ((cfg.get("owner") or {}).get("home") or {}).get("country")
    countries = [c.upper() for c in search.get("countries") or []]
    if countries and lst.country and lst.country not in countries:
        return f"country: {lst.country} not in search.countries"
    if lst.region and lst.region in (search.get("exclude_regions") or []):
        return f"region: {lst.region} excluded (search.exclude_regions)"
    mods = models(search)
    if mods:
        m = match_model(lst, mods)
        if m is None:
            return "model: not in search.models"
        lst.family, lst.tier = m.name, m.tier
    fuels = [f.lower() for f in search.get("powertrain") or []]
    if fuels and lst.fuel and lst.fuel not in fuels:
        return f"fuel: {lst.fuel} not in search.powertrain"
    if search.get("year_min"):
        if lst.year is None and not partial:
            return "reg: first registration missing (unregistered or not stated)"
        if lst.year is not None and lst.year < int(search["year_min"]):
            return f"year: {lst.year} < {search['year_min']}"
    if search.get("km_max") and lst.km is not None and lst.km > int(search["km_max"]):
        return f"km: {lst.km} > {search['km_max']}"
    if lst.km is not None and lst.km < 0:
        return "km: negative (parse error)"
    sanity = {**DEFAULT_PRICE_SANITY, **(disc.get("price_sanity") or {})}
    if lst.price is not None and not sanity["min_eur"] <= lst.price <= sanity["max_eur"]:
        # ×100 / monthly-rate parse errors: 10 mobile.de prices were stored ×100 (2026-11-03)
        return f"price_sanity: {lst.price} outside {sanity['min_eur']}–{sanity['max_eur']} (parse error until checked)"
    pmax = (search.get("price") or {}).get("max_eur")
    if pmax and lst.price is not None and lst.price > int(pmax):
        return f"price: {lst.price} > {pmax}"
    pmin = (search.get("price") or {}).get("min_eur")
    if pmin and lst.price is not None and lst.price < int(pmin):
        return f"price: {lst.price} < {pmin}"
    if (search.get("private_sellers_abroad") is False and home and lst.country and lst.country != home
            and lst.seller_type == "private"):
        return "seller: private seller abroad (search.private_sellers_abroad: false)"
    dmax = search.get("max_distance_km")
    km = lst.distance_km if lst.distance_km is not None else lst.distance_est_km
    if dmax and km is not None and km > int(dmax):
        return f"distance: {km} km > {dmax}"
    if "lease_transfer" in lst.flags:
        return "flag: lease_transfer (ask is a monthly rate)"
    for rule in search.get("hard_filters") or []:
        why = _hard_filter(lst, rule)
        if why:
            return why
    return None
