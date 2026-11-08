"""milanuncios.com: query builder, __INITIAL_PROPS__ parsers (synthetic fixtures), in-tab fetch transport,
Blocked/Gone, phone (no reveal reader), liveness."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://www.milanuncios.com/volkswagen-de-segunda-mano/volkswagen-id-4-pro-performance-900000002.htm"
AD_PRIV = AD.replace("900000002", "900000001")


def site(routes=None):
    return base.get("milanuncios.com", net=FakeNet("milanuncios.com", routes))


def qs(u):
    p = urllib.parse.urlparse(u)
    return p.path, dict(urllib.parse.parse_qsl(p.query))


def test_registry_and_ids():
    s = site()
    assert s.id == "milanuncios.com" and base.for_url(AD).id == "milanuncios.com"
    assert s.ad_id(AD) == "900000002" and s.meta["route"] == "plain-chrome" and s.meta["caps"]["phone_per_day"] == 9


def test_query_builder():
    s = site()
    path, p = qs(s.search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000,
                                          price_max=42000, fuel="bev", seller="private"), page=3))
    assert path == "/volkswagen-de-segunda-mano/"
    assert p == {"s": "id.4", "orden": "date", "anod": "2023", "kilometersTo": "50000", "hasta": "42000",
                 "fuels": "electrico", "vendedor": "part", "pagina": "3"}
    path, p = qs(s.search_url(SearchQuery(make="Mercedes-Benz", model="EQB", seller="dealer", sort="relevance")))
    assert path == "/mercedes-benz-de-segunda-mano/" and p == {"s": "eqb", "vendedor": "prof", "pagina": "1"}
    path, p = qs(s.search_url(SearchQuery(make="XPeng", model="G6")))   # no make category on the site
    assert path == "/coches-de-segunda-mano/" and p["s"] == "xpeng g6"
    path, p = qs(s.search_url(SearchQuery(make="Polestar", model="Polestar 2", fuel="petrol")))
    assert path == "/polestar-de-segunda-mano/" and p["s"] == "polestar 2" and "fuels" not in p


def test_search_parses_cards_and_pages():
    s = site({r"pagina=1": fixture(__file__, "milanuncios_com/search_1.html"),
              r"pagina=2": fixture(__file__, "milanuncios_com/search_2.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=5)))
    assert [c.site_ref for c in cards] == ["900000001", "900000002", "900000003"]
    assert [v for v, _, _ in s.net.calls] == ["tab", "tab"]          # in-tab fetches, stops at totalPages
    a, b = cards[:2]
    assert a.url == AD_PRIV and (a.price, a.km, a.year, a.first_registration) == (29900, 41000, 2023, "2023")
    assert a.seller_type == "private" and a.make == "Volkswagen" and a.location == "Valencia, Valencia"
    assert a.thumb == "https://images.example.invalid/api/v1/ma-ad-media-pro/images/syn-1-a" and a.country == "ES"
    assert a.price_is_net is None and a.created == "2026-11-01T10:00:00Z" and a.fuel == "eléctrico"
    assert b.seller_type == "dealer" and b.price_is_net is True and b.sponsored and b.km == 5500


def test_ad_parses_details():
    ad = site({"900000002": fixture(__file__, "milanuncios_com/ad.html")}).ad(AD)
    assert (ad.site_ref, ad.price, ad.price_is_net, ad.km, ad.year, ad.first_registration) == (
        "900000002", 31500, True, 5500, 2024, "2024")
    assert (ad.make, ad.model, ad.power_hp, ad.power_kw, ad.gearbox, ad.seats, ad.doors, ad.color) == (
        "Volkswagen", "ID.4", 204, 150, "automatic", 5, 5, "blanco")
    assert ad.contact == {"chat": False, "phone": True, "form": True, "whatsapp": True}
    assert ad.seller.type == "dealer" and ad.seller.name == "Synthetic Dealer" and ad.location == "Gandia, Valencia"
    assert ad.photos[0].startswith("https://images.example.invalid/") and ad.phones == [] and ad.status is None
    assert "raw" not in ad.to_dict()


def test_ad_found_by_id_anywhere_in_props():
    ad = site({"900000001": fixture(__file__, "milanuncios_com/ad_private_nested.html")}).ad(AD_PRIV)
    assert ad.site_ref == "900000001" and ad.seller.type == "private" and ad.status == "reserved"
    assert ad.price_is_net is None and ad.contact["chat"] and not ad.contact["phone"]


def test_phone():
    s = site({"900000002": fixture(__file__, "milanuncios_com/ad.html"),
              "900000001": fixture(__file__, "milanuncios_com/ad_private_nested.html")})
    ad, priv = s.ad(AD), s.ad(AD_PRIV)
    assert s.phone(ad) == []                                  # never in the page data
    with pytest.raises(base.Unsupported):                     # login + ES IP: browsers/contact modules
        s.phone(ad, reveal=True)
    assert s.phone(priv, reveal=True) == []                   # messages only: no 'Llamar' button


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({"900000002": Response(403, AD)}).ad(AD)
    with pytest.raises(base.Blocked):                         # Imperva challenge page (curl gets this)
        site({"900000002": "<html><title>Pardon Our Interruption</title></html>"}).ad(AD)
    with pytest.raises(base.Blocked):                         # no page data = wall/changed page, never gone
        site({"900000002": "<html>nothing</html>"}).ad(AD)
    with pytest.raises(base.Gone):
        site({"900000002": Response(404, AD)}).ad(AD)
    lst = "https://www.milanuncios.com/coches-de-segunda-mano/?marca=47"
    redirected = Response(200, AD, fixture(__file__, "milanuncios_com/search_2.html"), final_url=lst)
    with pytest.raises(base.Gone, match="soft"):
        site({"900000002": redirected}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({r"pagina=": "<html>Pardon Our Interruption</html>"}).search(SearchQuery(make="Volkswagen")))


def test_liveness():
    s = site({"900000002": Response(200, AD, "<html>900000002</html>")})
    assert s.is_live(AD).state == "live" and s.net.calls[0][0] == "tab"
    lst = "https://www.milanuncios.com/coches-de-segunda-mano/?marca=47"
    soft = site({"900000002": Response(200, AD, "<html>list</html>", final_url=lst)}).is_live(AD)
    assert soft.state == "removed" and soft.soft                       # redirect to a list page = soft gone
    assert site({"900000002": Response(404, AD)}).is_live(AD).state == "removed"
    with pytest.raises(base.Blocked):
        site({"900000002": Response(200, AD, "<html>Pardon Our Interruption</html>")}).is_live(AD)
