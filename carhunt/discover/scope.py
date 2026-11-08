"""Config `search` → keep/drop a normalized listing, with a reason code (`<code>: <detail>`).

Drops are logged to `$CARHUNT_HOME/discover/dispositions.jsonl`, never silent. Unknown values pass (an ad that does
not state km is not out of scope); `partial=True` is the search-card prefilter before a detail load.
Model matching uses make/model/variant/title only, never the description: dealer prose lists other models.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from carhunt.discover.normalize import Listing, fold

CARDB_MIN_EUR = 1500        # cardb's default price floor (search.price.min_eur unset): one floor for both
DEFAULT_MAX_EUR = 250000    # parse-error ceiling (discover.price_sanity.max_eur)


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


_FALSY = {"no", "none", "false", "0", "n", "nao", "nein", "non", "nessuno", "ninguno", "nenhum", "keine", "kein",
          "aucun", "unknown"}
_NUM = re.compile(r"-?\d+(?:[.,]\d+)?")


def _words(v: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(v)).split())


def _truthy(v: Any) -> bool:
    w = _words(v).split()
    return bool(w) and w[0] not in _FALSY


def _number(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    m = _NUM.search(str(v or ""))
    return float(m.group().replace(",", ".")) if m else None


def _out(v: float | None, rule: dict) -> bool:
    return v is not None and (("min" in rule and v < rule["min"]) or ("max" in rule and v > rule["max"]))


def _hard_filter(lst: Listing, rule: dict) -> str | None:
    """cardb's search.hard_filters grammar (cardb/internal/store/rank.go hardFilterHit), so discover drops what the
    queue would exclude anyway. Exactly one of: field + min/max (missing passes) · fact(s) + min/max | words | truthy ·
    flag (discover flag or truthy fact). `mentions_country` is left to cardb's queue (country names in EU languages)."""
    label = rule.get("label")
    if rule.get("field"):
        key = rule["field"]
        v = _number(getattr(lst, key.removeprefix("powertrain."), None))
        return f"hard_filter: {label or key} ({v:g})" if _out(v, rule) else None
    if rule.get("flag"):
        f = rule["flag"]
        hit = f in lst.flags or (f in lst.facts and _truthy(lst.facts[f][0]))
        return f"flag: {f}" if hit else None
    keys = ([rule["fact"]] if rule.get("fact") else []) + list(rule.get("facts") or [])
    for k in keys:
        if k not in lst.facts:
            continue
        v = lst.facts[k][0]
        if "min" in rule or "max" in rule:
            hit = _out(_number(v), rule)
        elif rule.get("words"):
            text = f" {_words(v)} "
            hit = any(f" {_words(w)} " in text for w in rule["words"])
        elif rule.get("mentions_country"):
            hit = False
        else:
            hit = _truthy(v)
        if hit:
            return f"hard_filter: {label or k} ({str(v)[:60]})"
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
    # Floor = search.price.min_eur (else cardb's default), the same number cardb's write check uses: a price under
    # it is a monthly rate / deposit / parse error. Ceiling: ×100 parse errors.
    price = search.get("price") or {}
    floor = int(price.get("min_eur") or CARDB_MIN_EUR)
    ceil = int((disc.get("price_sanity") or {}).get("max_eur") or DEFAULT_MAX_EUR)
    if lst.price is not None and not floor <= lst.price <= ceil:
        return f"price_sanity: {lst.price} outside {floor}–{ceil} (rate, deposit or parse error until checked)"
    pmax = price.get("max_eur")
    if pmax and lst.price is not None and lst.price > int(pmax):
        return f"price: {lst.price} > {pmax}"
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
