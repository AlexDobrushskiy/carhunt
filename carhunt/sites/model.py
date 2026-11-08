"""Data shapes shared by every site plugin, discover and liveness.

Plugins fill what the site gives and leave the rest None. Normalisation (VAT, scope, options) is discover's job;
plugins only parse. Prices are integers in the listing currency (EUR for every site so far).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Literal

SellerType = Literal["private", "dealer", "unknown"]
LiveState = Literal["live", "removed", "unknown"]


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, [], {}, "")}


@dataclass(frozen=True)
class SearchQuery:
    """One site search. One make/model per query: every site takes one model per URL; discover loops models.

    make/model are the user's names ("Volkswagen", "ID.4"); each plugin maps them through its `codes.yaml`.
    `country` picks the domain/market on multi-country sites (AS24 de/it/…, marktplaats nl/be).
    `extra` = raw site params, appended last (escape hatch for a filter the table lacks).
    """
    make: str | None = None
    model: str | None = None
    country: str | None = None          # ISO-3166 alpha-2
    price_min: int | None = None
    price_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    km_max: int | None = None
    fuel: str | None = None             # bev | phev | hev | petrol | diesel (cardb powertrain vocabulary)
    seller: Literal["private", "dealer", "any"] = "any"
    sort: Literal["newest", "price", "relevance"] = "newest"
    max_pages: int = 1
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> SearchQuery:
        names = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Card:
    """One search-result row. Enough to dedupe, scope and decide whether to read the full ad."""
    url: str
    site: str
    site_ref: str                       # the site's ad id (cursor + dedupe key)
    title: str | None = None
    price: int | None = None
    price_is_net: bool | None = None    # dealer price shown without VAT (AS24 isNetPrice)
    km: int | None = None
    year: int | None = None
    first_registration: str | None = None   # "YYYY-MM" (or "YYYY" when the site gives only the year)
    make: str | None = None
    model: str | None = None
    version: str | None = None
    fuel: str | None = None
    power_kw: int | None = None
    seller_type: SellerType = "unknown"
    location: str | None = None
    country: str | None = None
    thumb: str | None = None
    phones: list[str] = field(default_factory=list)   # only when the list page already carries them (AS24)
    sponsored: bool = False             # promoted row: may violate filters, never a cursor
    created: str | None = None          # ISO timestamp when the site gives one

    def to_dict(self) -> dict[str, Any]:
        return _clean(dataclasses.asdict(self)) | {"url": self.url, "site": self.site, "site_ref": self.site_ref}


@dataclass
class Seller:
    type: SellerType = "unknown"
    name: str | None = None
    id: str | None = None
    city: str | None = None
    postcode: str | None = None
    region: str | None = None
    country: str | None = None
    url: str | None = None


@dataclass
class RawAd:
    """A full ad, parsed. `raw` keeps the site's own JSON for anything the fields miss (never committed)."""
    url: str
    site: str
    site_ref: str
    title: str | None = None
    price: int | None = None
    price_is_net: bool | None = None
    currency: str = "EUR"
    make: str | None = None
    model: str | None = None
    version: str | None = None
    year: int | None = None
    first_registration: str | None = None
    km: int | None = None
    fuel: str | None = None
    power_kw: int | None = None
    power_hp: int | None = None
    drive: str | None = None            # site's own drive label (normalised by discover)
    gearbox: str | None = None
    body: str | None = None
    color: str | None = None
    seats: int | None = None
    doors: int | None = None
    owners: int | None = None
    accident_free: bool | None = None
    service_history: bool | None = None
    battery_kwh: float | None = None
    vin: str | None = None
    plate: str | None = None
    description: str | None = None
    equipment: list[str] = field(default_factory=list)
    photos: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    whatsapp: str | None = None
    seller: Seller = field(default_factory=Seller)
    location: str | None = None
    country: str | None = None
    created: str | None = None
    status: str | None = None           # site's own status label when present
    contact: dict[str, bool] = field(default_factory=dict)   # e.g. {"chat": True, "phone": False, "form": True}
    extra: dict[str, Any] = field(default_factory=dict)      # site-specific parsed fields
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self, *, raw: bool = False) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        if not raw:
            d.pop("raw")
        d["seller"] = _clean(d["seller"])
        d["extra"] = _clean(d["extra"])
        return _clean(d) | {"url": self.url, "site": self.site, "site_ref": self.site_ref}


@dataclass(frozen=True)
class Liveness:
    """Result of one read-only ad check.

    state removed + soft=True = a weak signal (redirect to a list page): liveness removes only on the 2nd soft
    signal ≥1 h later. A block is never a Liveness: plugins raise Blocked instead.
    """
    state: LiveState
    evidence: str
    soft: bool = False
    moved_to: str | None = None         # same ad under a new URL (AS24 308 slug change)

    def to_dict(self) -> dict[str, Any]:
        return _clean(dataclasses.asdict(self)) | {"state": self.state}
