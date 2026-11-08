"""kleinanzeigen.de: plain HTTP (Chrome UA) gets 200 past Akamai on reads. List and ad pages are server-rendered
HTML with no JSON blob: cards come from the `<article data-adid>` rows, ad facts from the analytics `dimensions`
object (`ad_attributes` = `ez_i:2023|km_i:41000|…`). Private sellers have no phone reveal: only numbers typed into
the description."""
from __future__ import annotations

import html
import json
import re
import urllib.parse
from collections.abc import Iterator

from carhunt.sites.base import BaseSite, Blocked, Gone, Unsupported
from carhunt.sites.extract import num, year_month, year_of
from carhunt.sites.model import Card, RawAd, SearchQuery, Seller

ORIGIN = "https://www.kleinanzeigen.de"
ARTICLE = re.compile(r'<article[^>]*data-adid="(\d+)"[^>]*data-href="([^"]+)"(.*?)</article>', re.S)
DIMS = re.compile(r"dimensions: (\{.*?\}),\s*extraDimensions", re.S)
DETAIL = re.compile(r'<li class="addetailslist--detail">\s*([^<]+?)\s*'
                    r'<span class="addetailslist--detail--value"[^>]*>\s*([^<]+?)\s*</span>')
SELLER = re.compile(r'class="[^"]*userprofile-vip">\s*'
                    r'<a href="(/s-bestandsliste\.html\?userId=(\d+))">\s*([^<]+?)\s*</a>')
# German mobiles typed into the text (015x/016x/017x); landlines are too ambiguous against prices/km
PHONE = re.compile(r"(?:\+49|0049|\b0)[\s/()-]*1[5-7]\d(?:[\s/-]*\d){6,9}")


def text(fragment: str) -> str:
    """HTML → text, one ' | ' between elements (the card parser splits on it)."""
    t = re.sub(r"<script.*?</script>|<svg.*?</svg>|<style.*?</style>", "", fragment, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", " | ", t)
    t = html.unescape(re.sub(r"(\s*\|\s*)+", " | ", t))
    return "\n".join(line.strip() for line in t.splitlines()).strip(" |\n")


def prose(fragment: str | None) -> str | None:
    if fragment is None:
        return None
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip() or None


def de_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return "+" + d
    if d.startswith("00"):
        return "+" + d[2:]
    return "+49" + d[1:] if d.startswith("0") else "+" + d


def de_date(s: str | None) -> str | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


class Plugin(BaseSite):
    pkg = "kleinanzeigen_de"

    # --- query ------------------------------------------------------------
    def search_url(self, q: SearchQuery, page: int = 1) -> str:
        attrs: dict[str, str] = {}
        keyword = None
        make = None
        if q.make:
            make = self.code("makes", q.make, slug=False)
            make = _slug(q.make) if make is None else make
            if make:
                attrs["marke_s"] = make
        if q.model:
            model = self.code("models", q.make, q.model, slug=False)
            if model and make:
                attrs["model_s"] = model
            else:
                keyword = self.code("keywords", q.make, q.model, slug=False) or q.model
        if q.fuel and self.code("fuel", q.fuel, slug=False):
            attrs["fuel_s"] = self.code("fuel", q.fuel, slug=False)
        if q.year_min or q.year_max:
            attrs["ez_i"] = f"{q.year_min or ''},{q.year_max or ''}"
        if q.km_max:
            attrs["km_i"] = f",{q.km_max}"
        attrs.update({k.removeprefix("autos."): v for k, v in q.extra.items()})
        segs = ["s-autos"]
        if keyword:
            segs.append(urllib.parse.quote(keyword.replace(" ", "-")))
        elif make:
            segs.append(make)
        if q.seller != "any":
            segs.append("anbieter:" + self.need_code("seller", q.seller))
        if q.price_min or q.price_max:
            segs.append(f"preis:{q.price_min or ''}:{q.price_max or ''}")
        if page > 1:
            segs.append(f"seite:{page}")
        if q.sort not in self.codes["sort"]:
            raise Unsupported(f"kleinanzeigen.de: no sort code for {q.sort!r}")
        cat = ("k0" if keyword else "") + self.codes["category"]
        cat += "".join(f"+autos.{k}:{urllib.parse.quote(v, safe='')}" for k, v in sorted(attrs.items()))
        return f"{ORIGIN}/{'/'.join(segs)}/{cat}"

    # --- search -------------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        size = int(self.codes.get("page_size", 27))
        stype = q.seller if q.seller != "any" else "unknown"
        for page in range(1, max(q.max_pages, 1) + 1):
            url = self.search_url(q, page)
            rows, total = self.parse_search(self.net.get(url).text, url)
            for row in rows:
                row.seller_type = stype   # list rows carry no seller type: only the anbieter filter tells
                yield row
            if not rows or (total is not None and page * size >= total):
                break

    def parse_search(self, page: str, url: str = "") -> tuple[list[Card], int | None]:
        arts = ARTICLE.findall(page)
        if not arts and "Gebrauchtwagen" not in page and "Ergebnis" not in page:
            raise Blocked("no-data", site=self.id, url=url)
        cards = [self.card(adid, href, body) for adid, href, body in arts]
        m = re.search(r"von\s+([\d.]+)\s+Ergebnis", page) or re.search(r"von ([\d.]+)", page)
        return cards, (int(m.group(1).replace(".", "")) if m else None)

    def card(self, adid: str, href: str, body: str) -> Card:
        c = Card(url=urllib.parse.urljoin(ORIGIN, href), site=self.id, site_ref=adid, country="DE")
        ld = re.search(r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', body, re.S)
        if ld:
            try:
                j = json.loads(ld.group(1))
                c.title, c.thumb = j.get("title"), j.get("contentUrl")
            except json.JSONDecodeError:
                pass
        for p in (p.strip() for p in text(body).split(" | ")):
            if "€" in p and c.price is None:
                c.price = num(p.split("€")[0])
            elif re.fullmatch(r"[\d.]+ km", p):
                c.km = num(p)
            elif p.startswith("EZ "):
                c.first_registration = year_month(p[3:])
                c.year = year_of(c.first_registration)
            elif re.match(r"\d{5} ", p) and c.location is None:
                c.location = p
            elif re.fullmatch(r"\d\d\.\d\d\.\d{4}", p) and c.created is None:
                c.created = de_date(p)
        return c

    # --- ad -----------------------------------------------------------------
    def ad(self, url: str) -> RawAd:
        r = self.net.get(url, ad_id=self.ad_id(url))
        return self.parse_ad(url, r.text)

    def parse_ad(self, url: str, page: str) -> RawAd:
        m = DIMS.search(page)
        if not m:
            gone = (self.meta.get("liveness") or {}).get("gone_text")
            if gone and re.search(gone, page, re.I):
                raise Gone(url, "200 gone marker")
            raise Blocked("no-data", site=self.id, url=url)
        d = json.loads(m.group(1))
        a = dict(kv.split(":", 1) for kv in str(d.get("ad_attributes") or "").split("|") if ":" in kv)

        def by_id(i: str, until: str) -> str | None:
            mm = re.search(rf'id="{i}"[^>]*>(.*?){until}', page, re.S)
            return mm.group(1) if mm else None

        desc = prose(by_id("viewad-description-text", r"</p>"))
        details = {k.strip(): html.unescape(v.strip()) for k, v in DETAIL.findall(page)}
        seller = SELLER.search(page)
        reg = f"{a['ez_i']}-{int(a.get('ezm_i') or 1):02d}" if a.get("ez_i") else None
        hp = num(a.get("power_i"))
        photos: dict[str, str] = {}
        for u in re.findall(r'data-imgsrc="([^"]+)"', page):   # each image twice (two sizes): first one wins
            photos.setdefault(u.split("?")[0], html.unescape(u))
        phones = sorted({de_phone(p) for p in PHONE.findall(desc or "")})
        stype = str(d.get("ad_seller_type") or "").lower()
        stype = "private" if stype.startswith("priv") else "dealer" if stype in ("trade", "commercial") else "unknown"
        city = d.get("l2_location_name") or None
        extra = re.search(r'id="viewad-extra-info".*?<span>([^<]*)</span>', page, re.S)
        acc = a.get("schaden_s")
        return RawAd(
            url=url, site=self.id, site_ref=str(d.get("ad_id") or self.ad_id(url)),
            title=prose(by_id("viewad-title", r"</h1>")), price=num(d.get("ad_price")),
            make=details.get("Marke") or a.get("marke_s"), model=details.get("Modell") or a.get("model_s"),
            year=year_of(reg), first_registration=reg,
            km=num(a.get("km_i")), fuel=a.get("fuel_s"), power_hp=hp, power_kw=round(hp * 0.7355) if hp else None,
            gearbox=a.get("shift_s"), body=a.get("typ_s"), color=a.get("aussenfarbe_s"),
            doors=num(str(a.get("anzahl_tueren_s") or "").split("_")[-1]),
            accident_free=True if acc == "f" else False if acc == "t" else None,
            service_history=True if a.get("full_service_history_b") == "t" else None,
            description=desc, equipment=sorted(k[:-2] for k, v in a.items() if k.endswith("_b") and v == "t"),
            photos=list(photos.values()), phones=phones,
            seller=Seller(type=stype, name=html.unescape(seller.group(3)) if seller else None,
                          id=seller.group(2) if seller else None, city=city, postcode=d.get("postal_code") or None,
                          region=d.get("l1_location_name") or None, country="DE",
                          url=urllib.parse.urljoin(ORIGIN, html.unescape(seller.group(1))) if seller else None),
            location=" ".join(x for x in (d.get("postal_code"), city) if x) or None, country="DE",
            created=de_date(extra.group(1)) if extra else None, contact={"chat": True, "phone": bool(phones)},
            extra={"price_type": d.get("ad_price_type"), "details": details,
                   "image_count": num(d.get("ad_image_count")), "phone_source": "text" if phones else None},
            raw={"dimensions": d, "attributes": a})

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        return list(ad.phones)   # no reveal button: only numbers the seller typed into the description
