"""wallapop.com: query builder, API parsers (synthetic fixtures), hash-id lookup, liveness incl. the sold flag."""
import json
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://es.wallapop.com/item/volkswagen-id-4-pro-performance-1300000001"
API = "https://api.wallapop.com/api/v3"


def fx(name):
    return json.loads(fixture(__file__, f"wallapop_com/{name}"))


def site(routes=None):
    return base.get("wallapop.com", net=FakeNet("wallapop.com", routes))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", country="ES", year_min=2023, km_max=50000,
                                 price_max=42000, seller="private"))
    p = urllib.parse.urlparse(u)
    assert f"{p.scheme}://{p.netloc}{p.path}" == f"{API}/search"
    assert dict(urllib.parse.parse_qsl(p.query)) == {
        "category_id": "100", "keywords": "ID.4", "latitude": "40.4168", "longitude": "-3.7038", "order_by": "newest",
        "source": "search_box", "seller_type": "private", "min_year": "2023", "max_km": "50000",
        "max_sale_price": "42000"}
    d = s.search_url(SearchQuery(make="Tesla", model="Model Y", seller="dealer", sort="price"))
    assert "keywords=Tesla+Model+Y" in d and "seller_type=professional" in d and "order_by=price_low_to_high" in d
    assert s.search_url(SearchQuery(), next_page="tok") == f"{API}/search?next_page=tok"
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(country="PT"))


def test_search_cards_and_token_paging():
    net = FakeNet("wallapop.com", {r"next_page=": fx("search_last.json"), r"/search\?": fx("search.json")})
    s = base.get("wallapop.com", net=net)
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=5)))
    assert [c[2] for c in net.calls] == [s.search_url(SearchQuery(make="Volkswagen", model="ID.4")),
                                         f"{API}/search?next_page=c3ludGhldGljLXRva2Vu"]
    assert len(cards) == 2
    c = cards[0]
    assert c.url == AD and c.site_ref == "1300000001" == s.ad_id(AD)
    assert (c.price, c.km, c.year, c.first_registration, c.make, c.model) == (29990, 44600, 2023, "2023",
                                                                              "Volkswagen", "ID.4")
    assert (c.location, c.country, c.thumb, c.sponsored) == ("28001 Madrid", "ES", "https://img.example.invalid/m.jpg",
                                                            False)
    assert c.created.startswith("2025-11-07T") and c.seller_type == "unknown"
    assert cards[1].sponsored, "bumped row is never a cursor"


def test_search_respects_max_pages():
    net = FakeNet("wallapop.com", {r"/search": fx("search.json")})
    list(base.get("wallapop.com", net=net).search(SearchQuery(model="ID.4", max_pages=1)))
    assert len(net.calls) == 1


def test_ad_private_uses_cached_hash():
    net = FakeNet("wallapop.com", {r"/search": fx("search_last.json") | fx("search.json") | {"meta": {}},
                                   r"/items/synhash0001$": fx("item.json"),
                                   r"/users/synuser0001$": fx("user_private.json")})
    s = base.get("wallapop.com", net=net)
    list(s.search(SearchQuery(model="ID.4")))
    ad = s.ad(AD)
    assert not any("es.wallapop.com/item" in c[2] for c in net.calls), "hash id came from the search row"
    assert ad.site_ref == "1300000001" and ad.title == "Volkswagen ID.4 Pro Performance" and ad.price == 29990
    assert (ad.year, ad.first_registration, ad.km, ad.power_hp) == (2023, "2023", 44600, 204)
    assert ad.fuel == "electric" and ad.extra["engine"] == "electric_hybrid"
    assert (ad.gearbox, ad.body, ad.seats, ad.doors) == ("automatic", "suv", 5, 5)
    assert ad.photos == ["https://img.example.invalid/1.jpg", "https://img.example.invalid/2.jpg"]
    assert ad.seller.type == "private" and ad.phones == [] and s.phone(ad, reveal=True) == []
    assert ad.contact == {"chat": True, "phone": False} and ad.status is None
    assert "raw" not in ad.to_dict()


def test_ad_pro_reads_hash_from_page():
    item = fx("item.json") | {"user": {"id": "synuser0002"}, "flags": {"sold": True}}
    net = FakeNet("wallapop.com", {r"es\.wallapop\.com/item/": fixture(__file__, "wallapop_com/item_page.html"),
                                   r"/items/synhash0001$": item, r"/users/synuser0002$": fx("user_pro.json")})
    ad = base.get("wallapop.com", net=net).ad(AD)
    assert [c[2] for c in net.calls][0] == AD
    assert ad.seller.type == "dealer" and ad.phones == ["+34 555 000 101"] and ad.contact["phone"]
    assert ad.status == "sold", "informational only: not Gone, liveness decides"


def test_blocked_and_gone():
    with pytest.raises(base.Gone):
        site({r"es\.wallapop\.com/item/": Response(404, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({r"es\.wallapop\.com/item/": fixture(__file__, "wallapop_com/item_page.html"),
              r"/items/": Response(404, f"{API}/items/synhash0001")}).ad(AD)
    with pytest.raises(base.Blocked):   # item page without the hash id = changed page/wall, never "gone"
        site({r"es\.wallapop\.com/item/": "<html>1300000001</html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"/search": Response(403, f"{API}/search")}).search(SearchQuery(model="ID.4")))
    with pytest.raises(base.Blocked):
        list(site({r"/search": {"data": {}}}).search(SearchQuery(model="ID.4")))
    # deleted seller profile: item still parses
    ad = site({r"es\.wallapop\.com/item/": fixture(__file__, "wallapop_com/item_page.html"),
               r"/items/": fx("item.json"), r"/users/": Response(404, "u")}).ad(AD)
    assert ad.seller.type == "unknown" and ad.seller.id == "synuser0001"


def test_liveness():
    page = fixture(__file__, "wallapop_com/item_page.html")
    assert site({"1300000001": Response(404, AD)}).is_live(AD).state == "removed"
    assert site({"1300000001": Response(200, AD, page)}).is_live(AD).state == "live"
    sold = page.replace('"sold":false', '"sold":true')
    lv = site({"1300000001": Response(200, AD, sold)}).is_live(AD)
    assert lv.state == "removed" and "sold" in lv.evidence
    with pytest.raises(base.Blocked):
        site({"1300000001": Response(403, AD)}).is_live(AD)
