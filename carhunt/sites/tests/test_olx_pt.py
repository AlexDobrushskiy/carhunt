"""OLX.pt: API query builder, offer parsers (synthetic API JSON), Blocked/Gone, liveness."""
import json
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://www.olx.pt/d/anuncio/vw-id-4-pro-IDsyn002.html"
SEARCH = r"/api/v1/offers/\?offset=0&"
SEARCH2 = r"/api/v1/offers/\?offset=40&"
OFFER = r"/api/v1/offers/900000002/$"


def fx(name):
    return json.loads(fixture(__file__, f"olx_pt/{name}"))


def site(routes=None):
    return base.get("olx.pt", net=FakeNet("olx.pt", routes))


def test_query_builder():
    u = site().search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000, price_max=42000,
                                      seller="private"), page=2)
    p = urllib.parse.urlparse(u)
    assert (p.netloc, p.path) == ("www.olx.pt", "/api/v1/offers/")
    assert dict(urllib.parse.parse_qsl(p.query)) == {
        "offset": "40", "limit": "40", "category_id": "378", "query": "ID.4", "filter_float_year:from": "2023",
        "filter_float_price:to": "42000", "filter_float_quilometros:to": "50000", "owner_type": "private"}
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(
        site().search_url(SearchQuery(make="Lancia", model="Ypsilon"))).query))
    assert q["query"] == "Lancia Ypsilon"      # unknown model: free text of the names


def test_search_parses_cards_pages_and_filters():
    s = site({SEARCH: fx("search.json"), SEARCH2: fx("search_last.json")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", fuel="bev", max_pages=5)))
    assert [c.site_ref for c in cards] == ["900000002", "900000003", "900000004"]   # petrol row filtered out
    assert all(via == "tab" for via, _, _ in s.net.calls) and len(s.net.calls) == 2    # no links.next → stop
    c = cards[0]
    assert (c.price, c.km, c.year, c.first_registration, c.fuel, c.power_kw) == (31500, 42000, 2023, "2023-03",
                                                                                 "electrico", 150)
    assert c.seller_type == "private" and c.model == "ID.4" and c.location == "Aveiro, Aveiro"
    assert c.thumb == "https://img.example.invalid/olx/2a/image" and not c.sponsored
    assert cards[1].seller_type == "dealer"
    dealers = list(site({SEARCH: fx("search.json")}).search(SearchQuery(seller="dealer")))
    assert [(c.site_ref, c.sponsored) for c in dealers] == [("900000001", True), ("900000003", False)]


def test_ad_from_search_cache_needs_no_request():
    s = site({SEARCH: fx("search.json"), SEARCH2: fx("search_last.json")})
    list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=1)))
    n = len(s.net.calls)
    ad = s.ad(AD)
    assert len(s.net.calls) == n                     # the search row is the full offer
    assert ad.site_ref == "900000002" and ad.extra["url_id"] == "IDsyn002"
    assert (ad.price, ad.km, ad.power_hp, ad.power_kw, ad.gearbox, ad.seats) == (31500, 42000, 204, 150, "automatic", 5)
    assert ad.vin == "SYNOLXVIN00000001" and ad.description == "Carro sintético."
    assert ad.contact == {"chat": True, "phone": True} and ad.seller.type == "private"
    assert ad.photos == ["https://img.example.invalid/olx/2a/image", "https://img.example.invalid/olx/2b/image"]
    mirror = s.ad("https://www.olx.pt/d/anuncio/vw-id-4-pro-dealer-IDsyn003.html")
    assert mirror.extra["mirror_site"] == "standvirtual" and "standvirtual.com" in mirror.extra["mirror_of"]
    assert mirror.contact["phone"] is False and s.phone(mirror, reveal=True) == []   # chat-only: nothing to reveal


def test_ad_cold_resolves_id_from_page_then_api():
    s = site({"IDsyn002": fixture(__file__, "olx_pt/ad.html"), OFFER: fx("offer.json")})
    ad = s.ad(AD)
    assert ad.site_ref == "900000002" and [u for _, _, u in s.net.calls][0] == AD
    with pytest.raises(base.Unsupported):          # phone needs the logged-in Bearer token
        s.phone(ad, reveal=True)
    assert s.phone(ad) == []


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        list(site({SEARCH: Response(403, "x", "Request blocked")}).search(SearchQuery()))
    s = site({SEARCH: Response(404, "x", "")})
    with pytest.raises(base.Blocked):              # API 404 is retried once, then a block — never "gone"
        list(s.search(SearchQuery()))
    assert len(s.net.calls) == 2
    with pytest.raises(base.Gone):                 # the ad page itself 410 = gone
        site({"IDsyn002": Response(410, AD)}).ad(AD)
    with pytest.raises(base.Blocked):
        site({"IDsyn002": "<html>nothing</html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({SEARCH: "<html>not json</html>"}).search(SearchQuery()))


def test_liveness():
    assert site({"IDsyn002": Response(410, AD)}).is_live(AD).state == "removed"
    assert site({"IDsyn002": Response(200, AD, "<html>IDsyn002</html>")}).is_live(AD).state == "live"
    assert site({"IDsyn002": Response(200, AD, "<html>other</html>")}).is_live(AD).state == "unknown"
    with pytest.raises(base.Blocked):
        site({"IDsyn002": Response(403, AD, "Request blocked")}).is_live(AD)
