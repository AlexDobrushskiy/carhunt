"""CustoJusto: URL builder, __NEXT_DATA__ parsers (synthetic fixtures), row filters, gone redirect, liveness."""
import urllib.parse

import pytest

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://www.custojusto.pt/aveiro/veiculos/carros-usados/suv-tt/vw-id-4-pro-40000001"
GONE = "https://www.custojusto.pt/aveiro/veiculos/carros-usados?gone=40000001"
LIST = r"/portugal/veiculos/carros-usados/vw/id-4$"
LIST2 = r"/portugal/veiculos/carros-usados/vw/id-4\?o=2$"


def site(routes=None):
    return base.get("custojusto.pt", net=FakeNet("custojusto.pt", routes))


def test_query_builder():
    s = site()
    assert s.search_url(SearchQuery(make="Volkswagen", model="ID.4")) == \
        "https://www.custojusto.pt/portugal/veiculos/carros-usados/vw/id-4"
    u = s.search_url(SearchQuery(make="Audi", model="Q4 e-tron", price_max=42000), page=3)
    assert urllib.parse.urlparse(u).path == "/portugal/veiculos/carros-usados/audi/q4-e-tron"
    assert dict(urllib.parse.parse_qsl(urllib.parse.urlparse(u).query)) == {"o": "3"}   # filters run on rows
    assert s.ad_id(AD) == "40000001"


def test_search_parses_cards_pages_and_row_filters():
    s = site({LIST: fixture(__file__, "custojusto_pt/search.html"),
              LIST2: fixture(__file__, "custojusto_pt/search_last.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=5)))
    assert len(cards) == 41 and len(s.net.calls) == 2          # 40 rows → next page; 1 row → last
    assert all(via == "tab" for via, _, _ in s.net.calls)
    assert "39999999" not in {c.site_ref for c in cards}        # promoted gallery strip skipped
    c = cards[0]
    assert (c.site_ref, c.price, c.year, c.fuel, c.seller_type) == ("40000001", 30100, 2023, "Eléctrico", "private")
    assert c.url == AD and c.km is None and c.location == "Ílhavo, Aveiro" and c.created == "2026-11-02T10:00:00Z"
    s = site({LIST: fixture(__file__, "custojusto_pt/search.html")})
    kept = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", fuel="bev", price_max=42000, year_min=2023,
                                     seller="dealer")))
    assert kept and all(k.seller_type == "dealer" and k.price <= 42000 and k.fuel == "Eléctrico" for k in kept)
    assert "40000039" not in {k.site_ref for k in kept} and "40000040" not in {k.site_ref for k in kept}


def test_ad_parses_details():
    ad = site({"40000001$": fixture(__file__, "custojusto_pt/ad.html")}).ad(AD)
    assert (ad.site_ref, ad.price, ad.make, ad.model, ad.first_registration) == ("40000001", 30100, "VW", "ID.4",
                                                                                "2023-03")
    assert ad.km is None and (ad.extra["km_min"], ad.extra["km_max"]) == (40000, 49999)
    assert (ad.power_hp, ad.power_kw, ad.fuel, ad.color) == (204, 150, "Eléctrico", "Cinzento")
    assert ad.photos == ["https://img.example.invalid/cj/play/a.jpg", "https://img.example.invalid/cj/play/b.jpg"]
    assert ad.seller.type == "private" and ad.seller.city == "Ílhavo" and ad.extra["seller_ads"] == 1
    assert ad.extra["dealer_ref"] == "SYN-STOCK-1" and ad.extra["old_price"] == 31000
    assert ad.whatsapp is None and ad.extra["whatsapp_same_as_phone"] is True
    assert ad.contact == {"form": True, "phone": True, "chat": False}


def test_phone_is_form_only():
    s = site({"40000001$": fixture(__file__, "custojusto_pt/ad.html")})
    ad = s.ad(AD)
    assert s.phone(ad) == []
    with pytest.raises(base.Unsupported):
        s.phone(ad, reveal=True)


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({"40000001$": Response(403, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({"40000001$": Response(404, AD)}).ad(AD)
    with pytest.raises(base.Gone):          # the site's own marker: redirect to the list with ?gone=<id>
        site({"40000001$": Response(200, AD, fixture(__file__, "custojusto_pt/search_last.html"),
                                    final_url=GONE)}).ad(AD)
    with pytest.raises(base.Blocked):       # 200 without page data = wall/changed page, never "gone"
        site({"40000001$": "<html>nothing</html>"}).ad(AD)
    with pytest.raises(base.Blocked):
        list(site({LIST: Response(403, "x", "")}).search(SearchQuery(make="Volkswagen", model="ID.4")))


def test_liveness():
    gone = site({"40000001$": Response(200, AD, "<html>list</html>", final_url=GONE)}).is_live(AD)
    assert gone.state == "removed" and not gone.soft
    soft = site({"40000001$": Response(200, AD, "<html>list</html>",
                                       final_url="https://www.custojusto.pt/aveiro/veiculos")}).is_live(AD)
    assert soft.state == "removed" and soft.soft
    assert site({"40000001$": Response(200, AD, "<html>40000001</html>")}).is_live(AD).state == "live"
    with pytest.raises(base.Blocked):
        site({"40000001$": Response(403, AD)}).is_live(AD)
