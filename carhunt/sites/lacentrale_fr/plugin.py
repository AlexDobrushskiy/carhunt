"""La Centrale (lacentrale.fr): DataDome, dealer listings only. Read route = a non-automated plain-chrome tab that
opens the home page first. Only the list URL is known; the result rows were never captured
non-empty, so search/ad have no reader yet → Unsupported (see README "Gaps")."""
from __future__ import annotations

import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Unsupported
from carhunt.sites.model import Card, RawAd, SearchQuery

ORIGIN = "https://www.lacentrale.fr"


class Plugin(BaseSite):
    pkg = "lacentrale_fr"

    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        if q.country and q.country.upper() != "FR":
            raise Unsupported(f"lacentrale.fr: France only (asked {q.country})")
        if q.seller == "private":
            raise Unsupported("lacentrale.fr: dealer listings only (the private filter returned 0)")
        if not (q.make and q.model):
            raise Unsupported("lacentrale.fr: needs make + model (makesModelsCommercialNames code)")
        p: dict[str, str] = {"makesModelsCommercialNames": self.need_code("models", q.make, q.model)}
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["energies"] = self.code("fuel", q.fuel, slug=False)
        for field, param in self.codes["params"].items():
            if getattr(q, field):
                p[param] = str(getattr(q, field))
        if q.seller == "dealer":
            p["customerFamilyCodes"] = self.need_code("seller", "dealer")
        if self.codes["sort"].get(q.sort):
            p["sortBy"] = self.codes["sort"][q.sort]
        if page > 1:
            p["page"] = str(page)
        p.update(q.extra)
        return f"{ORIGIN}/listing?{urllib.parse.urlencode(p)}"

    def ad_url(self, ad_id: str) -> str:
        return f"{ORIGIN}/auto-occasion-annonce-{ad_id}.html"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        raise Unsupported(f"lacentrale.fr: no search reader (result rows never captured); open "
                          f"{self.search_url(q)} in plain-chrome after the home page")

    def ad(self, url: str) -> RawAd:
        raise Unsupported("lacentrale.fr: no ad reader (ad page data never captured); route plain-chrome")
