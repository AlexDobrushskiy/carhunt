"""kleinanzeigen.de: path query builder, server-rendered HTML parsers (synthetic fixtures), blocks, liveness."""
import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

ID = "9990000001"
AD = f"https://www.kleinanzeigen.de/s-anzeige/vw-id-4-pro-synthetic/{ID}-216-9999"


def site(routes=None):
    return base.get("kleinanzeigen.de", net=FakeNet("kleinanzeigen.de", routes))


def test_query_builder():
    s = site()
    u = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000, price_max=42000,
                                 fuel="bev", seller="private"), page=2)
    assert u == ("https://www.kleinanzeigen.de/s-autos/volkswagen/anbieter:privat/preis::42000/seite:2/c216"
                 "+autos.ez_i:2023%2C+autos.fuel_s:elektro+autos.km_i:%2C50000+autos.marke_s:volkswagen"
                 "+autos.model_s:id_4")
    # no model_s slug known → the runners' keyword search, make still filtered
    assert s.search_url(SearchQuery(make="Audi", model="Q4 e-tron", fuel="bev")) == (
        "https://www.kleinanzeigen.de/s-autos/Q4-e-tron/k0c216+autos.fuel_s:elektro+autos.marke_s:audi")
    assert s.search_url(SearchQuery(make="Xpeng", model="G6")) == "https://www.kleinanzeigen.de/s-autos/Xpeng-G6/k0c216"
    assert "/anbieter:gewerblich/" in s.search_url(SearchQuery(make="Mercedes-Benz", seller="dealer"))
    assert "autos.marke_s:mercedes_benz" in s.search_url(SearchQuery(make="Mercedes-Benz"))
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(make="Kia", sort="price"))


def test_search_parses_cards():
    s = site({r"/s-autos/": fixture(__file__, "kleinanzeigen_de/search.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", seller="private", max_pages=3)))
    assert len(cards) == 2 and len(s.net.calls) == 1   # "von 2 Ergebnissen": no page 2
    c = cards[0]
    assert (c.site_ref, c.price, c.km, c.first_registration, c.year) == (ID, 32990, 41000, "2023-05", 2023)
    assert c.url == AD and c.title == "VW ID.4 Pro Synthetic" and c.location == "50667 Köln"
    assert c.seller_type == "private" and c.created == "2026-10-27" and c.thumb.startswith("https://img.example.invalid/")
    assert cards[1].created is None and cards[1].price == 29500   # "Heute, 09:15" has no date


def test_ad_parses_details():
    ad = site({ID: fixture(__file__, "kleinanzeigen_de/ad.html")}).ad(AD)
    assert ad.site_ref == ID and ad.price == 32990 and ad.extra["price_type"] == "NEGOTIABLE"
    assert (ad.first_registration, ad.km, ad.power_hp, ad.power_kw) == ("2023-05", 41000, 204, 150)
    assert ad.accident_free is True and ad.service_history is True and ad.doors == 5
    assert ad.make == "Volkswagen" and ad.fuel == "elektro" and "seat_heating" in ad.equipment
    assert ad.title == "VW ID.4 Pro Synthetic & Wärmepumpe"
    assert ad.phones == ["+491555550102", "+4915555550101"]   # typed in the text → E.164
    assert ad.photos == ["https://img.example.invalid/api/v1/prod-ads/images/aa/0001?rule=$_59.AUTO",
                         "https://img.example.invalid/api/v1/prod-ads/images/cc/0003?rule=$_59.AUTO"]
    assert ad.seller.type == "private" and ad.seller.name == "Synthetic Seller" and ad.seller.postcode == "50667"
    assert ad.created == "2026-10-27" and ad.contact == {"chat": True, "phone": True}
    assert "raw" not in ad.to_dict()


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({ID: Response(403, AD)}).ad(AD)
    with pytest.raises(base.Blocked):   # 200 without the dimensions object = wall/changed page, never "gone"
        site({ID: "<html><title>kleinanzeigen.de</title></html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"/s-autos/": "<html>nothing</html>"}).search(SearchQuery(make="Kia")))
    with pytest.raises(base.Gone):
        site({ID: Response(404, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({ID: "<html><h1>Die Anzeige ist nicht mehr verfügbar.</h1></html>"}).ad(AD)


def test_liveness():
    assert site({ID: Response(410, AD)}).is_live(AD).state == "removed"
    assert site({ID: Response(200, AD, fixture(__file__, "kleinanzeigen_de/ad.html"))}).is_live(AD).state == "live"
    marker = f"<p>{ID}</p> Die Anzeige ist nicht mehr verfügbar"
    assert site({ID: Response(200, AD, marker)}).is_live(AD).state == "removed"
    soft = site({ID: Response(301, AD, location="https://www.kleinanzeigen.de/s-autos/c216")}).is_live(AD)
    assert soft.state == "removed" and soft.soft
    with pytest.raises(base.Blocked):
        site({ID: Response(429, AD)}).is_live(AD)
