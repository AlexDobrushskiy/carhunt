"""leparking.fr: French used-car aggregator behind Cloudflare (lane passes). Used to find cross-posts of one car.
The model list URL and the in-page JS filters are known; the result rows were never captured → search/ad are
Unsupported. `/tools/<id>/0/P/P.html` redirects to the source ad, which the source site's plugin reads."""
from __future__ import annotations

from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Unsupported
from carhunt.sites.model import Card, RawAd, SearchQuery

ORIGIN = "https://www.leparking.fr"


class Plugin(BaseSite):
    pkg = "leparking_fr"

    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        if not (q.make and q.model):
            raise Unsupported("leparking.fr: needs make + model (list URL slug)")
        if page > 1:
            raise Unsupported("leparking.fr: pagination not measured")
        return f"{ORIGIN}/voiture-occasion/{self.need_code('models', q.make, q.model)}.html"

    def filter_js(self, q: SearchQuery) -> str:
        """In-page JS that applies the country/seller filters (the site has no URL params for them)."""
        f = self.codes["filters"]
        crit = []
        if q.country:
            c = f["country"].get(q.country.upper())
            if not c:
                raise Unsupported(f"leparking.fr: no country filter id for {q.country}")
            crit.append(c)
        if q.seller != "any":
            s = f["seller"].get(q.seller)
            if not s:
                raise Unsupported(f"leparking.fr: no seller filter id for {q.seller}")
            crit.append(s)
        calls = [f"ctrl.set_criteria('{c['field']}',{c['id']},'{c['label']}',window);" for c in crit]
        return " ".join(calls + ["ctrl.need_refresh()"])

    def source_redirect_url(self, row_id: str) -> str:
        """Redirects to the source ad (leboncoin, La Centrale, …): open it in that site's own route."""
        return f"{ORIGIN}/tools/{row_id}/0/P/P.html"

    def search(self, q: SearchQuery) -> Iterator[Card]:
        raise Unsupported(f"leparking.fr: no search reader (result rows never captured); lane tab: open "
                          f"{self.search_url(q)}, run filter_js(q)")

    def ad(self, url: str) -> RawAd:
        raise Unsupported("leparking.fr: aggregator, no ad pages — /tools/<id>/0/P/P.html redirects to the source "
                          "ad; read it with the source site's plugin")
