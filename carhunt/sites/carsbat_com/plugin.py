"""carsbat.com: EU auction-history archive looked up by VIN (vet: was this car auctioned, at what price/km/damage).
Cloudflare → a non-automated browser. Lot pages are public; the VIN search needs the free account's login. The lot page
shape was never captured, so readers are Unsupported; URL builders and VIN helpers work offline."""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Unsupported
from carhunt.sites.model import Card, Liveness, RawAd, SearchQuery

ORIGIN = "https://carsbat.com"
VIN = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
LOT = re.compile(r"/detail/([a-z0-9]{17})-[a-z0-9]+/?")


def norm_vin(vin: str) -> str:
    v = re.sub(r"[\s-]", "", vin or "").upper()
    if not VIN.match(v):
        raise ValueError(f"not a VIN: {vin!r}")
    return v


class Plugin(BaseSite):
    pkg = "carsbat_com"

    def vin_search_url(self, vin: str) -> str:
        """Needs the login; redirects to the lot page when the VIN is archived."""
        return f"{ORIGIN}/en/vin-search/?{urllib.parse.urlencode({'query': norm_vin(vin)})}"

    def lot_vin(self, url: str) -> str | None:
        """VIN from a lot URL (/en/detail/<vin lowercase>-<hash>/)."""
        m = LOT.search(url)
        return m.group(1).upper() if m and self.owns(url) else None

    def lookup(self, vin: str) -> RawAd:
        """Auction history for a VIN: login (browsers/accounts) + a lot-page parser, neither here yet."""
        raise Unsupported(f"carsbat.com: VIN search needs the free account's login (browsers + accounts modules) and "
                          f"the lot page shape was never captured; open {self.vin_search_url(vin)} in plain-chrome")

    def search(self, q: SearchQuery) -> Iterator[Card]:
        raise Unsupported("carsbat.com: an auction archive looked up by VIN (lookup), not a marketplace")

    def ad(self, url: str) -> RawAd:
        raise Unsupported("carsbat.com: no lot-page reader (page shape never captured); route plain-chrome")

    def is_live(self, url: str) -> Liveness:
        raise Unsupported("carsbat.com: archive lots are not live ads")
