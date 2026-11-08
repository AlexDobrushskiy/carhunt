"""subito.it: query builder, __NEXT_DATA__ list + RSC ad parsers (synthetic fixtures), phone reveal, liveness."""
import json
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

ID = "999000001"
AD = f"https://www.subito.it/auto/volkswagen-id-4-synthetic-synthville-{ID}.htm"
URN = "id:ad:00000000-0000-4000-8000-000000000001:list:999000001"


def site(routes=None):
    return base.get("subito.it", net=FakeNet("subito.it", routes))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000, price_max=42000,
                                 fuel="bev", seller="private"), page=2)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.subito.it" and p.path == "/annunci-italia/vendita/auto/"
    assert dict(urllib.parse.parse_qsl(p.query)) == {"cb": "000101", "fl": "4", "ys": "2023", "pe": "42000",
                                                     "me": "11", "advt": "0", "o": "2"}
    assert "q=Tesla" in s.search_url(SearchQuery(make="Tesla"))   # no brand code → text search (the BYD route)
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(make="Kia", sort="price"))
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(make="Kia", country="ES"))


def test_search_parses_cards_and_matches_model():
    s = site({r"/vendita/auto/": fixture(__file__, "subito_it/search.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=3)))
    assert [c.site_ref for c in cards] == [ID, "999000003"]   # ID.3 row dropped, non-AdItem row skipped
    assert len(s.net.calls) == 1   # totalPages = 1
    c = cards[0]
    assert (c.price, c.km, c.first_registration, c.power_kw, c.model) == (32990, 41000, "2023-05", 150, "ID.4")
    assert c.url == AD and c.seller_type == "private" and c.location == "Synthville (MI)"
    assert c.version is None   # "Altro allestimento" (level 0!) is a placeholder trim, never the make
    assert c.make == "VOLKSWAGEN" and cards[1].seller_type == "dealer"
    assert c.created == "2026-11-04T10:12:33"
    by_name = list(site({r"/vendita/auto/": fixture(__file__, "subito_it/search.html")}).search(
        SearchQuery(make="Volkswagen", model="ID.3")))   # no group code in codes.yaml → matched by name
    assert [c.site_ref for c in by_name] == ["999000002"]


def test_ad_parses_details():
    ad = site({ID: fixture(__file__, "subito_it/ad.html")}).ad(AD)
    assert ad.site_ref == ID and ad.price == 32990 and ad.km == 41000 and ad.first_registration == "2023-05"
    assert (ad.power_kw, ad.power_hp, ad.doors, ad.seats, ad.gearbox) == (150, 204, 5, 5, "Automatico")
    assert ad.description.startswith("Auto in perfette condizioni — unico")   # "$4a" text record, UTF-8 length
    assert ad.description.endswith("Prezzo trattabile.")
    assert ad.extra["urn"] == URN and ad.extra["has_phone"] and ad.phones == []
    assert ad.seller.type == "private" and ad.seller.region == "Lombardia" and len(ad.photos) == 2
    assert "raw" not in ad.to_dict()


def test_phone_reveal():
    # the contacts route goes first: the urn contains the ad id
    s = site({r"/hades/v1/contacts/ads/": json.loads(fixture(__file__, "subito_it/phone.json")),
              ID: fixture(__file__, "subito_it/ad.html")})
    gates: list[str] = []
    gate = s.net.gate
    s.net.gate = lambda kind="load", **kw: (gates.append(kind), gate(kind, **kw))[1]
    ad = s.ad(AD)
    assert s.phone(ad) == [] and gates == ["load"]   # no reveal without reveal=True
    assert s.phone(ad, reveal=True) == ["+390555501234"]   # national number → +39
    assert gates == ["load", "phone"] and s.net.calls[-1][2].endswith(URN)
    hidden = site({r"/contacts/ads/": Response(404, "x"), ID: fixture(__file__, "subito_it/ad.html")})
    assert hidden.phone(hidden.ad(AD), reveal=True) == []
    with pytest.raises(base.Blocked):
        blocked = site({r"/contacts/ads/": Response(403, "x"), ID: fixture(__file__, "subito_it/ad.html")})
        blocked.phone(blocked.ad(AD), reveal=True)


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({ID: Response(403, AD)}).ad(AD)
    with pytest.raises(base.Blocked):   # 200 without the ad JSON = wall/changed page, never "gone"
        site({ID: "<html><title>Subito</title></html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"/vendita/auto/": "<html>captcha-delivery</html>"}).search(SearchQuery(make="Kia")))
    with pytest.raises(base.Gone):
        site({ID: Response(410, AD)}).ad(AD)


def test_liveness():
    assert site({ID: Response(410, AD)}).is_live(AD).state == "removed"
    assert site({ID: Response(200, AD, fixture(__file__, "subito_it/ad.html"))}).is_live(AD).state == "live"
    assert site({ID: Response(200, AD, "<html>no id</html>")}).is_live(AD).state == "unknown"
    with pytest.raises(base.Blocked):
        site({ID: Response(403, AD)}).is_live(AD)
