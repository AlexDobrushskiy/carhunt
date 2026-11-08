"""leboncoin.fr: query builder, __NEXT_DATA__ parsers (synthetic fixtures), cookie handling, Blocked/Gone, liveness."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AID = "1000000001"
AD = f"https://www.leboncoin.fr/ad/voitures/{AID}"


def site(routes=None, cookie="synthetic-dd"):
    return base.get("leboncoin.fr", net=FakeNet("leboncoin.fr", routes), cookie=cookie)


def qs(url):
    p = urllib.parse.urlparse(url)
    return p, dict(urllib.parse.parse_qsl(p.query))


def test_query_builder():
    s = site()
    p, q = qs(s.search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000,
                                       price_max=42000, fuel="bev", seller="private"), page=2))
    assert p.netloc == "www.leboncoin.fr" and p.path == "/recherche"
    assert q == {"category": "2", "u_car_model": "VOLKSWAGEN_ID.4", "fuel": "4", "regdate": "2023-max",
                 "mileage": "min-50000", "price": "min-42000", "owner_type": "private", "sort": "time",
                 "order": "desc", "page": "2"}
    _, q = qs(s.search_url(SearchQuery(make="Skoda", model="Enyaq", seller="dealer", price_min=20000)))
    assert q["u_car_model"] == "SKODA_Enyaq,SKODA_Enyaq Coupé" and q["owner_type"] == "pro"
    assert q["price"] == "20000-max" and "page" not in q
    _, q = qs(s.search_url(SearchQuery(make="Polestar", model="2", sort="relevance")))   # not in codes → free text
    assert q["text"] == "Polestar 2" and "sort" not in q and "u_car_model" not in q
    _, q = qs(s.search_url(SearchQuery(make="Kia")))
    assert q["u_car_brand"] == "KIA"
    with pytest.raises(base.Unsupported):
        s.search_url(SearchQuery(make="Kia", model="EV6", country="ES"))


def test_owns_and_ad_id():
    s = site()
    assert s.owns(AD) and s.owns("https://leboncoin.fr/recherche?category=2")
    assert not s.owns("https://www.leboncoin.fr.example.invalid/x")
    assert s.ad_id(AD) == AID and s.ad_id("https://www.leboncoin.fr/voitures/1000000009.htm") == "1000000009"
    assert base.for_url(AD).id == "leboncoin.fr"


def test_search_paginates_and_parses_cards():
    s = site({r"page=2": fixture(__file__, "leboncoin_fr/search_p2.html"),
              r"/recherche\?": fixture(__file__, "leboncoin_fr/search_p1.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=5)))
    assert [c.site_ref for c in cards] == [AID, "1000000002", "1000000003"]
    assert s.net.loads == 2   # stopped at the site's max_pages
    c = cards[0]
    assert (c.url, c.price, c.km, c.first_registration, c.year) == (AD, 32990, 41000, "2022-05", 2022)
    assert (c.make, c.model, c.version, c.fuel, c.power_kw) == ("Volkswagen", "ID.4", "Pro Performance",
                                                                 "Électrique", 150)
    assert c.seller_type == "private" and c.location == "69003 Lyon" and c.country == "FR"
    assert c.thumb.startswith("https://img.example.invalid/") and c.created == "2026-10-20T09:15:00"
    assert cards[1].seller_type == "dealer"


def test_ad_parses_details():
    s = site({AID: fixture(__file__, "leboncoin_fr/ad.html")})
    ad = s.ad(AD)
    assert ad.site_ref == AID and ad.price == 32990 and ad.status == "active"
    assert (ad.first_registration, ad.km, ad.power_hp, ad.power_kw) == ("2022-05", 41000, 204, 150)
    assert (ad.gearbox, ad.seats, ad.doors, ad.color) == ("Automatique", 5, 5, "Blanc")
    assert ad.owners == 1 and ad.service_history is True
    assert ad.extra["battery_soh_pct"] == 96.5 and ad.extra["model_year"] == 2022
    assert ad.extra["inspection_valid"] is True and ad.extra["condition"] == "Bon état général"
    assert ad.seller.type == "private" and ad.seller.postcode == "69003"
    assert ad.phones == ["+33 5 55 00 01 01"] and ad.contact == {"chat": True, "phone": True}
    assert ad.photos == ["https://img.example.invalid/1000000001/1-large.jpg",
                         "https://img.example.invalid/1000000001/2-large.jpg"]
    assert "raw" not in ad.to_dict()
    assert s.phone(ad) == ["+33 5 55 00 01 01"]
    with pytest.raises(base.Unsupported):
        s.phone(ad, reveal=True)
    req = s.net.calls[0]
    assert req == ("http", "load", AD)


def test_cookie_is_sent_and_rotated():
    seen = []

    class Net(FakeNet):
        def get(self, url, **kw):
            seen.append(kw["headers"]["Cookie"])
            return super().get(url, **kw)

    page = fixture(__file__, "leboncoin_fr/ad.html")
    rotated = Response(200, AD, page, headers={"set-cookie": "datadome=rotated-1; Max-Age=31536000; Path=/"})
    s = base.get("leboncoin.fr", net=Net("leboncoin.fr", {AID: rotated}), cookie=lambda: "first")
    s.ad(AD)
    s.ad(AD)
    assert seen == ["datadome=first", "datadome=rotated-1"]


def test_no_cookie_means_no_request():
    s = site({AID: fixture(__file__, "leboncoin_fr/ad.html")}, cookie=lambda: None)
    with pytest.raises(base.Blocked) as e:
        s.ad(AD)
    assert e.value.signature == "datadome-no-cookie" and s.net.calls == []


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({AID: Response(403, AD, "<html>geo.captcha-delivery.com</html>")}).ad(AD)
    with pytest.raises(base.Blocked) as e:
        site({AID: "<html><h1>Access is temporarily restricted</h1></html>"}).ad(AD)
    assert e.value.signature == "datadome-hard-block"
    with pytest.raises(base.Blocked):   # 200 without page data = wall/changed page, never "gone"
        site({AID: "<html>nothing</html>"}).ad(AD)
    with pytest.raises(base.Blocked) as e:   # bounced to the login page
        site({AID: Response(302, AD, location="https://auth.leboncoin.fr/login"),
              "auth.leboncoin": "<html>login</html>"}).ad(AD)
    assert e.value.signature == "login-wall"
    for status in (404, 410):   # ad gone: skip it, the run continues
        with pytest.raises(base.Gone):
            site({AID: Response(status, AD, "<title>Annonce introuvable</title>")}).ad(AD)
    inactive = fixture(__file__, "leboncoin_fr/ad.html").replace('"status": "active"', '"status": "expired"')
    with pytest.raises(base.Gone):
        site({AID: inactive}).ad(AD)


def test_liveness():
    page = fixture(__file__, "leboncoin_fr/ad.html")
    assert site({AID: Response(200, AD, page)}).is_live(AD).state == "live"
    lv = site({AID: Response(410, AD, "<title>Annonce introuvable</title>")}).is_live(AD)
    assert lv.state == "removed" and not lv.soft
    lv = site({AID: Response(200, AD, "<html><title>Annonce introuvable</title></html>")}).is_live(AD)
    assert lv.state == "removed"
    expired = page.replace('"status": "active"', '"status": "expired"')
    assert site({AID: Response(200, AD, expired)}).is_live(AD).state == "removed"
    lv = site({AID: Response(302, AD, location="https://www.leboncoin.fr/recherche?category=2")}).is_live(AD)
    assert lv.state == "removed" and lv.soft
    # a page quoting the ad URL without the ad's data is not proof of life
    assert site({AID: Response(200, AD, f"<html>{AD}</html>")}).is_live(AD).state == "unknown"
    with pytest.raises(base.Blocked):
        site({AID: Response(429, AD)}).is_live(AD)
