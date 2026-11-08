"""milanuncios.com (Spain): Imperva (reese84) stops plain HTTP, any real Chrome passes. One plain-chrome tab opens the
home page, then the server-rendered pages are fetched from inside it (same origin, cookies included) and parsed from
`window.__INITIAL_PROPS__`. 41 rows per page. Phones need a login + a Spanish IP (browsers + contact modules)."""
from __future__ import annotations

import urllib.parse
from collections.abc import Iterator
from typing import Any

from carhunt.sites.base import BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num, window_var
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

ORIGIN = "https://www.milanuncios.com"
FETCH_OPTS = {"headers": {"Accept": "text/html"}}


def _https(u: str | None) -> str | None:
    """List rows carry scheme-less image URLs ("images.milanuncios.com/api/…")."""
    if not u:
        return None
    return u if u.startswith("http") else "https://" + u.lstrip("/")


def _cash(price: Any) -> tuple[int | None, bool | None]:
    cash = (price or {}).get("cashPrice") if isinstance(price, dict) else None
    if isinstance(cash, dict):
        return num(cash.get("value")), cash.get("includeTaxes")
    return num(price), None


def _seller_type(st: Any) -> str:
    if isinstance(st, dict):
        if st.get("isPrivate") is not None:
            return "private" if st["isPrivate"] else "dealer"
        st = st.get("value")
    return {"private": "private", "professional": "dealer"}.get(str(st or "").lower(), "unknown")


def find_ad(props: dict, aid: str | None) -> dict | None:
    """The ad object on an ad page: `adDetail` / `ad`, else the dict carrying this id + a title."""
    for k in ("adDetail", "ad"):
        if isinstance(props.get(k), dict) and props[k].get("id"):
            return props[k]
    stack: list[Any] = [props]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if aid and str(o.get("id")) == aid and "title" in o:
                return o
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None


class Plugin(BaseSite):
    pkg = "milanuncios_com"

    # --- query (codes.yaml only) ---------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        make = self.code("makes", q.make) if q.make else "coches"
        kw = [q.make] if q.make and make == "coches" else []
        if q.model:
            kw.append(self.code("models", q.make, q.model, slug=False) or q.model.lower())
        p: dict[str, Any] = {}
        if kw:
            p["s"] = " ".join(kw).lower()
        if self.code("sort", q.sort, slug=False):
            p["orden"] = self.code("sort", q.sort, slug=False)
        for field, key in (self.codes.get("params") or {}).items():
            if getattr(q, field, None):
                p[key] = getattr(q, field)
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            p["fuels"] = self.code("fuel", q.fuel, slug=False)
        if q.seller != "any":
            p["vendedor"] = self.need_code("seller", q.seller)
        p["pagina"] = page
        p.update(q.extra)
        return f"{ORIGIN}/{make}-de-segunda-mano/?{urllib.parse.urlencode(p)}"

    # --- transport -----------------------------------------------------------
    def _props(self, url: str, ad_id: str | None = None) -> tuple[dict, str | None]:
        r = self.net.browser_get(url, mode="fetch", ad_id=ad_id, opts=FETCH_OPTS)
        props = window_var(r.text, "__INITIAL_PROPS__") if r.text else None
        if not isinstance(props, dict):
            raise Blocked("no-initial-props", site=self.id, url=url)
        return props, r.final_url

    # --- search ----------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        """Newest first = `orden=date`; ids grow with time, so the numeric id is a usable cursor."""
        for page in range(1, min(max(q.max_pages, 1), int(self.codes.get("max_pages") or 200)) + 1):
            url = self.search_url(q, page)
            props, _ = self._props(url)
            lp = props.get("adListPagination")
            if not isinstance(lp, dict):
                raise Blocked("no-ad-list", site=self.id, url=url)
            rows = (lp.get("adList") or {}).get("ads") or []
            yield from self.parse_search(props)
            if not rows or page >= int((lp.get("pagination") or {}).get("totalPages") or 0):
                break

    def parse_search(self, props: dict) -> Iterator[Card]:
        for it in ((props.get("adListPagination") or {}).get("adList") or {}).get("ads") or []:
            yield self.card(it)

    def card(self, it: dict) -> Card:
        tags = {t.get("type"): t.get("text") for t in it.get("tags") or [] if isinstance(t, dict)}
        price, taxes = _cash(it.get("price"))
        st = _seller_type(it.get("sellerType"))
        cat = it.get("category") or {}
        year = num(tags.get("año"))
        imgs = it.get("images") or []
        return Card(url=urllib.parse.urljoin(ORIGIN + "/", it["url"]), site=self.id, site_ref=str(it["id"]),
                    title=it.get("title"), price=price, price_is_net=(st == "dealer" and taxes is False) or None,
                    km=num(tags.get("kilómetros")), year=year, first_registration=str(year) if year else None,
                    make=cat.get("name") if cat.get("slug") != "coches-de-segunda-mano" else None,
                    fuel=tags.get("combustible"), seller_type=st,
                    location=", ".join(x for x in ((it.get("city") or {}).get("name"),
                                                   (it.get("province") or {}).get("name")) if x) or None,
                    country="ES", thumb=_https(imgs[0]) if imgs else None, sponsored=bool(it.get("highlighted")),
                    created=it.get("publishDate"))

    # --- ad --------------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        aid = self.ad_id(url)
        props, final = self._props(url, ad_id=aid)
        a = find_ad(props, aid)
        if a is None:
            if final and aid and aid not in final and props.get("adListPagination") is not None:
                raise Gone(url, f"soft: redirect to list {final[:100]}")   # liveness waits for a 2nd signal
            raise Blocked("no-ad", site=self.id, url=url)
        return self.parse_ad(url, a, props)

    def parse_ad(self, url: str, a: dict, props: dict | None = None) -> RawAd:
        at = {x.get("type"): x for x in a.get("attributes") or [] if isinstance(x, dict)}
        val = lambda k: (at.get(k) or {}).get("value")              # noqa: E731
        fmt = lambda k: (at.get(k) or {}).get("valueFormatted")     # noqa: E731
        price, taxes = _cash(a.get("price"))
        st = _seller_type(a.get("sellerType"))
        au, loc = a.get("author") or {}, a.get("location") or {}
        schema = (a.get("schema") or {}).get("schema") or {}
        city, prov = (loc.get("city") or {}).get("name"), (loc.get("province") or {}).get("name")
        year = num(val("year"))
        hp = num(val("hp"))
        cm = a.get("contactMethods") or {}
        return RawAd(
            url=url, site=self.id, site_ref=str(a.get("id") or self.ad_id(url)), title=a.get("title"), price=price,
            price_is_net=(st == "dealer" and taxes is False) or None, make=schema.get("brand"),
            model=schema.get("model"), year=year, first_registration=str(year) if year else None,
            km=num(val("kilometers")), fuel=fmt("fuel") or val("fuel"), power_hp=hp,
            power_kw=round(hp * 0.7355) if hp else None, gearbox=str(val("transmission") or "").lower() or None,
            color=val("color"), seats=num(fmt("seats")), doors=num(val("doors")), description=a.get("description"),
            photos=[u for u in map(_https, a.get("images") or []) if u],
            seller=Seller(type=st, name=au.get("userName"), id=str(au["id"]) if au.get("id") else None,
                          city=city or (au.get("location") or {}).get("city"),
                          region=prov or (au.get("location") or {}).get("province"), country="ES"),
            location=", ".join(x for x in (city, prov) if x) or None, country="ES",
            created=a.get("publicationDate"), status="reserved" if a.get("isReserved") is True else None,
            contact={k: bool(v) for k, v in cm.items() if k in ("chat", "phone", "form", "whatsapp")},
            extra={"warranty": val("warranty"), "environmental_label": val("environmentalLabel"),
                   "updated": a.get("updateDate"), "engine": schema.get("vehicleEngine")},
            raw={"ad": a})

    # --- phone -----------------------------------------------------------------
    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        if not reveal:
            return list(ad.phones)
        if ad.contact and not ad.contact.get("phone"):
            return []          # no 'Llamar' button: the seller takes messages only
        raise Unsupported("milanuncios.com: 'Llamar' needs the logged-in account on a Spanish IP (browsers + contact "
                          "modules); ≤3 reveals per sticky session, ≤9/day, slot taken before the click")
