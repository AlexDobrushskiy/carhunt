"""mobile.de: query builder, RSC flight parsers (synthetic fixtures), blocks, liveness."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

ID = "99900000000002"
AD = f"https://suchen.mobile.de/fahrzeuge/details.html?id={ID}"
MIRROR = "https://suchen.mobile.de/fahrzeuge/details.html?id=99900000000003"


def site(routes=None):
    return base.get("mobile.de", net=FakeNet("mobile.de", routes))


def test_query_builder():
    s = site()
    q = SearchQuery(make="Audi", model="Q4 e-tron", year_min=2023, km_max=50000, price_max=42000, fuel="bev",
                    seller="private")
    assert len(s.targets(q)) == 2   # Q4 is filed under two model codes: both searched
    p = urllib.parse.urlparse(s.search_url(q, page=2, target=1))
    assert p.netloc == "suchen.mobile.de" and p.path == "/fahrzeuge/search.html"
    assert dict(urllib.parse.parse_qsl(p.query)) == {
        "isSearchRequest": "true", "s": "Car", "vc": "Car", "ms": "1900;57;;", "adLimitation": "ONLY_FSBO_ADS",
        "ft": "ELECTRICITY", "fr": "2023:", "ml": ":50000", "p": ":42000", "cn": "DE", "sb": "doc", "od": "down",
        "pageNumber": "2"}
    dealer = s.search_url(SearchQuery(make="Volkswagen", model="ID.4", seller="dealer", sort="price"))
    assert "ms=25200;82;;" in dealer and "adLimitation=ONLY_DEALER_ADS" in dealer and "sb=p&od=up" in dealer
    assert s.search_url(SearchQuery(make="BYD", model="Seal U")).startswith("https://suchen.mobile.de/auto/byd-seal-u.html?")
    with pytest.raises(base.Unsupported):   # numeric-code site: unknown models must be added to codes.yaml
        s.search_url(SearchQuery(make="Volkswagen", model="ID.7"))


def test_search_parses_cards():
    s = site({r"search\.html": fixture(__file__, "mobile_de/search.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=3)))
    assert len(cards) == 3 and len(s.net.calls) == 1   # numResultsTotal reached: no page 2
    top, priv, short = cards
    assert top.sponsored and top.seller_type == "dealer"
    assert (priv.site_ref, priv.price, priv.km, priv.first_registration) == (ID, 28991, 41000, "2023-05")
    assert priv.power_kw == 210
    assert priv.url == AD and priv.seller_type == "private" and not priv.sponsored and priv.phones == ["+495550000302"]
    assert priv.location == "50667 Köln" and priv.country == "DE"
    assert short.site_ref == "400000002" and not short.sponsored   # old 9-digit id width; eyecatcher = organic
    assert s.net.calls[0][0] == "tab"   # browser route, never plain HTTP


def test_ad_parses_details():
    s = site({ID: fixture(__file__, "mobile_de/ad.html")})
    ad = s.ad(AD)
    assert ad.site_ref == ID and ad.price == 28991 and ad.price_is_net is False   # gross, rounded, never ×100
    assert ad.extra["price_net"] == 24362 and ad.extra["vat_rate"] == 19
    assert (ad.first_registration, ad.km, ad.power_kw, ad.power_hp, ad.owners) == ("2023-05", 41000, 210, 286, 1)
    assert ad.accident_free is True and ad.service_history is True and ad.drive == "Heckantrieb"
    assert ad.battery_kwh == 77.0 and ad.doors == 5 and ad.seats == 5
    assert ad.description.startswith("Synthetic description\nWärmepumpe")   # RSC "$1f" text record resolved
    assert ad.phones == ["+495550000302"] and ad.seller.type == "private" and ad.seller.city == "Köln"
    assert ad.photos[0] == "https://img.example.invalid/api/v1/mo-prod/images/aa/0001?rule=mo-1024.jpg"
    assert ad.created.startswith("2026-11-04") and "raw" not in ad.to_dict()
    assert s.phone(ad) == ad.phones


def test_mirror_ad():
    ad = site({"99900000000003": fixture(__file__, "mobile_de/ad_mirror.html")}).ad(MIRROR)
    assert ad.extra["mirror"] is True and ad.extra["partner_url"].startswith("https://www.kleinanzeigen.de/")
    assert "call-tracking" in ad.extra["phone_note"] and ad.description == "Inline text"


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({ID: Response(403, AD, "<title>Zugriff verweigert / Access denied</title>")}).ad(AD)
    with pytest.raises(base.Blocked):   # Akamai sometimes answers 200 with the denial page
        site({ID: Response(200, AD, "<html><title>Zugriff verweigert / Access denied</title></html>")}).ad(AD)
    with pytest.raises(base.Blocked):   # a page without flight data is never "gone"
        site({ID: "<html><title>mobile.de</title></html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"search\.html": "<html>nothing</html>"}).search(SearchQuery(make="Kia", model="EV6")))
    with pytest.raises(base.Gone):
        site({ID: Response(404, AD, fixture(__file__, "mobile_de/gone.html"))}).ad(AD)
    with pytest.raises(base.Gone):
        site({ID: Response(200, AD, fixture(__file__, "mobile_de/gone.html"))}).ad(AD)


def test_liveness():
    gone = fixture(__file__, "mobile_de/gone.html")
    assert site({ID: Response(404, AD, gone)}).is_live(AD).state == "removed"
    assert site({ID: Response(200, AD, gone)}).is_live(AD).state == "removed"   # gone title on a 200
    live = site({ID: Response(200, AD, fixture(__file__, "mobile_de/ad.html"))})
    assert live.is_live(AD).state == "live"   # i18n copy of the gone phrase in a live page is not a marker
    assert live.net.calls == [("tab", "load", AD)]
    with pytest.raises(base.Blocked):
        site({ID: Response(403, AD, "Zugriff verweigert")}).is_live(AD)
