"""AutoScout24: query builder, __NEXT_DATA__ parsers (synthetic fixtures), liveness."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

U1 = "11111111-aaaa-4bbb-8ccc-000000000001"
AD = f"https://www.autoscout24.de/angebote/volkswagen-id-4-pro-elektro-weiss-{U1}"


def site(routes=None):
    return base.get("autoscout24", net=FakeNet("autoscout24", routes))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", country="DE", year_min=2022, km_max=80000,
                                 price_max=40000, fuel="bev", seller="private"), page=2)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.autoscout24.de" and p.path == "/lst/volkswagen/id.4"
    q = dict(urllib.parse.parse_qsl(p.query))
    assert q == {"atype": "C", "cy": "D", "fregfrom": "2022", "kmto": "80000", "priceto": "40000", "fuel": "E",
                 "custtype": "P", "sort": "age", "desc": "1", "page": "2"}
    be = s.search_url(SearchQuery(make="Audi", model="Q4 e-tron", country="BE"))
    assert be.startswith("https://www.autoscout24.be/nl/lst/audi/q4-e-tron?") and "cy=B" in be


def test_search_parses_cards():
    s = site({r"/lst/": fixture(__file__, "autoscout24/search.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", country="DE")))
    assert len(cards) == 2
    c = cards[0]
    assert (c.site_ref, c.price, c.km, c.first_registration, c.year) == (U1, 32990, 41000, "2022-05", 2022)
    assert c.url == AD and c.power_kw == 150 and c.seller_type == "private" and not c.sponsored
    assert c.phones == ["+49 555 0000101"] and c.country == "DE"
    assert cards[1].sponsored and cards[1].seller_type == "dealer"


def test_ad_parses_details():
    s = site({U1: fixture(__file__, "autoscout24/ad.html")})
    ad = s.ad(AD)
    assert ad.site_ref == U1 and ad.price == 27723 and ad.price_is_net is True
    assert (ad.first_registration, ad.km, ad.power_kw, ad.drive, ad.owners) == ("2022-05", 41000, 150, "Rear", 1)
    assert ad.accident_free is True and ad.service_history is True
    assert ad.seller.type == "dealer" and ad.seller.name == "Synthetic Autohaus"
    assert ad.phones == ["+49 555 0000202"] and "heat_pump" in ad.equipment
    assert ad.photos == ["https://img.example.invalid/a.jpg", "https://img.example.invalid/b.jpg"]
    assert "raw" not in ad.to_dict()


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({U1: Response(403, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({U1: Response(410, AD)}).ad(AD)
    with pytest.raises(base.Blocked):   # 200 without page data = wall/changed page, never "gone"
        site({U1: "<html>nothing</html>"}).ad(AD)


def test_liveness():
    assert site({U1: Response(410, AD)}).is_live(AD).state == "removed"
    assert site({U1: Response(200, AD, f"<html>{U1}</html>")}).is_live(AD).state == "live"
    moved = AD.replace("pro-elektro", "pro-x-elektro")
    s = site({"pro-x-elektro": Response(200, moved, f"<html>{U1}</html>"),
              "pro-elektro": Response(308, AD, location=moved)})
    lv = s.is_live(AD)
    assert lv.state == "live" and lv.moved_to == moved
    with pytest.raises(base.Blocked):
        site({U1: Response(429, AD)}).is_live(AD)
