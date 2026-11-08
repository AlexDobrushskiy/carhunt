"""marktplaats.nl / 2dehands.be / 2ememain.be: query builder, API + __CONFIG__ parsers (synthetic), liveness."""
import json
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://www.marktplaats.nl/v/auto-s/volkswagen/m2000000001-volkswagen-id-4-pro-77-kwh"
AD_BE = "https://www.2dehands.be/v/auto-s/skoda/m2000000003-skoda-enyaq-iv-80"


def site(routes=None):
    return base.get("marktplaats.nl", net=FakeNet("marktplaats.nl", routes))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", country="NL", year_min=2023, km_max=50000,
                                 price_max=42000, fuel="bev", seller="private"), page=3)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.marktplaats.nl" and p.path == "/lrp/api/search"
    q = urllib.parse.parse_qsl(p.query)
    assert q == [("l1CategoryId", "91"), ("limit", "30"), ("offset", "60"), ("query", "ID.4"),
                 ("attributesById[]", "10898"), ("attributesById[]", "11756"),
                 ("attributeRanges[]", "constructionYear:2023:null"), ("attributeRanges[]", "mileage:null:50000"),
                 ("attributeRanges[]", "PriceCents:null:4200000"), ("sortBy", "SORT_INDEX"),
                 ("sortOrder", "DECREASING")]
    be = s.search_url(SearchQuery(make="BYD", model="Seal U", country="BE", seller="dealer", sort="relevance"))
    assert be.startswith("https://www.2dehands.be/lrp/api/search?") and "query=BYD+Seal+U" in be
    assert "attributesById%5B%5D=10899" in be and "sortBy" not in be
    fr = s.search_url(SearchQuery(make="Tesla", model="Model Y", country="BE", extra={"lang": "fr"}))
    assert fr.startswith("https://www.2ememain.be/") and "query=Tesla+Model+Y" in fr and "lang" not in fr
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(country="DE"))


def test_search_parses_cards_and_stops_on_short_page():
    net = FakeNet("marktplaats.nl", {r"/lrp/api/search": fixture(__file__, "marktplaats_nl/search.json")})
    s = base.get("marktplaats.nl", net=net)
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", country="NL", seller="private", max_pages=5)))
    assert len(net.calls) == 1, "short page (<30 rows) = last page"
    assert len(cards) == 2
    c = cards[0]
    assert c.url == AD and c.site_ref == "m2000000001" and s.ad_id(c.url) == c.site_ref
    assert (c.price, c.km, c.year, c.first_registration) == (32495, 41200, 2023, "2023")
    assert (c.make, c.model, c.fuel, c.seller_type, c.location, c.country) == (
        "Volkswagen", "ID.4", "Elektrisch", "private", "Utrecht", "NL")
    assert cards[1].price is None and cards[1].km == 60500 and cards[1].country == "NL"


def test_search_pages_until_max_allowed():
    page = json.loads(fixture(__file__, "marktplaats_nl/search.json"))
    page["listings"] = page["listings"] * 15     # 30 rows: a full page
    page["maxAllowedPageNumber"] = 2
    net = FakeNet("marktplaats.nl", {r"/lrp/api/search": page})
    cards = list(base.get("marktplaats.nl", net=net).search(SearchQuery(model="ID.4", max_pages=9)))
    assert len(net.calls) == 2 and len(cards) == 60
    assert [c.seller_type for c in cards[:1]] == ["unknown"]


def test_ad_dealer():
    s = site({"m2000000001": fixture(__file__, "marktplaats_nl/ad_dealer.html")})
    ad = s.ad(AD)
    assert ad.site_ref == "m2000000001" and ad.price == 32495 and ad.title == "Volkswagen ID.4 Pro 77 kWh"
    assert (ad.make, ad.model, ad.version, ad.year, ad.first_registration) == (
        "Volkswagen", "ID.4", "Pro 77 kWh", 2023, "2023")
    assert (ad.km, ad.power_hp, ad.power_kw, ad.drive, ad.battery_kwh) == (41200, 204, None, "Achterwiel", 77.0)
    assert (ad.seats, ad.doors, ad.owners, ad.plate) == (5, 5, 1, "SYN-01-X")
    assert ad.phones == ["+31555000101"] and s.phone(ad) == ["+31555000101"]
    assert ad.seller.type == "dealer" and ad.seller.name == "Synthetic Dealer"
    assert ad.seller.url == "https://www.marktplaats.nl/smb-profile/profile/900001/"
    assert ad.contact == {"chat": True, "phone": True, "website": True}
    assert ad.description == "Synthetic ad.\nWarmtepomp & trekhaak."
    assert "Warmtepomp" in ad.equipment
    assert ad.photos == ["https://img.example.invalid/api/v1/listing/images/a1?rule=ecg_mp_eps$_85.jpg",
                         "https://img.example.invalid/api/v1/listing/images/a2?rule=ecg_mp_eps$_85.jpg"]
    assert ad.created == "2026-11-06T14:00:00Z" and ad.extra["service_history"] == "Dealer onderhouden"
    assert "raw" not in ad.to_dict()


def test_ad_private_hidden_phone():
    s = site({"m2000000003": fixture(__file__, "marktplaats_nl/ad_private.html")})
    ad = s.ad(AD_BE)
    assert ad.seller.type == "private" and ad.phones == [] and ad.country == "BE"
    assert ad.contact == {"chat": True, "phone": False, "website": False}
    assert (ad.power_kw, ad.km, ad.first_registration, ad.status) == (150, 58000, "2022", "reserved")
    assert s.phone(ad) == []
    with pytest.raises(base.Unsupported):
        s.phone(ad, reveal=True)


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({"m2000000001": Response(403, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({"m2000000001": Response(410, AD)}).ad(AD)
    with pytest.raises(base.Blocked):   # 200 without __CONFIG__ = wall/changed page, never "gone"
        site({"m2000000001": "<html>m2000000001 nothing</html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"/lrp/api/search": Response(403, "x")}).search(SearchQuery(model="ID.4")))
    with pytest.raises(base.Blocked):
        list(site({r"/lrp/api/search": {"error": "x"}}).search(SearchQuery(model="ID.4")))


def test_liveness():
    assert site({"m2000000001": Response(410, AD)}).is_live(AD).state == "removed"
    assert site({"m2000000001": Response(200, AD, "<html>m2000000001</html>")}).is_live(AD).state == "live"
    assert site({"m2000000001": Response(200, AD, "<html>other</html>")}).is_live(AD).state == "unknown"
    with pytest.raises(base.Blocked):
        site({"m2000000001": Response(403, AD)}).is_live(AD)


def test_owns_all_hosts():
    s = site()
    assert all(s.owns(u) for u in (AD, AD_BE, AD_BE.replace("2dehands", "2ememain")))
    assert base.for_url(AD_BE, net=FakeNet("marktplaats.nl")).id == "marktplaats.nl"
