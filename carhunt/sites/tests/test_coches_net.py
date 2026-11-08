"""coches.net: query builders (page URL + gateway body), gateway + __INITIAL_PROPS__ parsers (synthetic fixtures),
ProxyUnavailable fallback, page budget, phone reveal, Blocked/Gone, liveness."""
import json
import os
import urllib.parse
from pathlib import Path

import pytest

from carhunt.access.errors import PaceExceeded, ProxyUnavailable
from carhunt.sites import _net, base
from carhunt.sites._net import Response
from carhunt.sites.model import RawAd, SearchQuery
from carhunt.sites.testing import FakeNet, fixture

AD = "https://www.coches.net/volkswagen-id4-gtx-5p-electrico-hibrido-2024-en-alicante-900000002-covo.aspx"
AD_PRIV = "https://www.coches.net/volkswagen-id4-pro-5p-electrico-hibrido-2023-en-valencia-900000001-covo.aspx"
GW_AD = "https://www.coches.net/kia-ev6-air-5p-electrico-hibrido-2023-en-madrid-900000101-covo.aspx"
Q = SearchQuery(make="Volkswagen", model="ID.4", year_min=2022, km_max=80000, price_max=40000, fuel="bev",
                seller="private", max_pages=3)


class NoProxyNet(FakeNet):
    """No Spanish exit configured: every country route fails closed, like Net._proxy."""

    def get(self, url, *, country=None, **kw):
        if country:
            raise ProxyUnavailable(f"{self.site}: no {country} proxy")
        return super().get(url, **kw)


class RecNet(FakeNet):
    """Records country + body of every request."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.sent = []

    def get(self, url, *, country=None, data=None, method=None, **kw):
        self.sent.append({"url": url, "country": country, "method": method,
                          "body": json.loads(data) if data else None, "kind": kw.get("kind", "load")})
        return super().get(url, **kw)


def site(routes=None, net_cls=FakeNet):
    return base.get("coches.net", net=net_cls("coches.net", routes))


def test_registry_and_ids():
    s = site()
    assert s.id == "coches.net" and base.for_url(AD).id == "coches.net"
    assert s.ad_id(AD) == "900000002"
    assert s.ad_id("https://www.coches.net/km-0/kia/ev6/madrid/air-electrico-de-demostracion-900000004-kovn.aspx") \
        == "900000004"


def test_page_query_builder():
    u = site().search_url(SearchQuery(make="Audi", model="Q4 e-tron", year_min=2023, price_max=42000, km_max=50000,
                                      fuel="bev", seller="private", sort="price"), page=2)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.coches.net" and p.path == "/segunda-mano/"
    assert urllib.parse.parse_qsl(p.query) == [
        ("MakeIds[0]", "4"), ("ModelIds[0]", "1368"), ("MakeIds[1]", "4"), ("ModelIds[1]", "1376"),
        ("Fueltype2List", "3"), ("MinYear", "2023"), ("MaxKms", "50000"), ("MaxPrice", "42000"), ("st", "2"),
        ("fi", "Price"), ("or", "1"), ("pg", "2")]
    newest = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(site().search_url(Q)).query))
    assert "fi" not in newest and "pg" not in newest     # default order, page 1 has no pg
    with pytest.raises(base.Unsupported):
        site().search_url(SearchQuery(make="Volkswagen", model="Golf"))   # numeric ids must be listed


def test_gateway_body():
    b = site().search_body(Q, page=2)
    f = b["filters"]
    assert b["pagination"] == {"page": 2, "size": 30} and b["sort"] == {"term": "relevance", "order": "desc"}
    assert f["vehicles"] == [{"make": "VOLKSWAGEN", "makeId": 47, "model": "ID.4", "modelId": 1334}]
    assert (f["fuelTypeIds"], f["sellerTypeId"], f["km"], f["price"], f["year"]) == (
        [3], 2, {"from": None, "to": 80000}, {"from": None, "to": 40000}, {"from": 2022, "to": None})
    assert f["categories"] == {"category1Ids": [2500]} and f["offerTypeIds"] == [0, 2, 3, 4, 5]
    make_only = site().search_body(SearchQuery(make="BYD", extra={"provinceIds": "[28]"}))["filters"]
    assert make_only["vehicles"] == [{"make": "BYD", "makeId": 1352, "model": None, "modelId": 0}]
    assert make_only["provinceIds"] == [28] and make_only["sellerTypeId"] == 0


def test_search_gateway_pages():
    pages = iter([fixture(__file__, "coches_net/search_api_1.json"), fixture(__file__, "coches_net/search_api_2.json")])
    net = RecNet("coches.net", {r"/search/listing": lambda u: next(pages)})
    s = base.get("coches.net", net=net)
    cards = list(s.search(Q))
    assert [c.site_ref for c in cards] == ["900000101", "900000102", "900000109", "900000103"]
    assert [x["body"]["pagination"]["page"] for x in net.sent] == [1, 2]
    assert {(x["country"], x["method"], x["kind"]) for x in net.sent} == {("ES", "POST", "api")}
    c = cards[0]
    assert c.url == GW_AD and (c.price, c.price_is_net, c.km, c.year, c.first_registration) == (
        30001, True, 20001, 2023, "2023")
    assert c.seller_type == "dealer" and c.power_kw == 168 and c.phones == ["+34555000301"] and not c.sponsored
    assert c.thumb == "https://img.example.invalid/cn/k1.jpg" and c.location == "Madrid, Madrid"
    assert cards[1].seller_type == "private" and cards[1].price_is_net is None
    assert cards[2].sponsored                                   # paidItems


def test_search_falls_back_to_page_route_without_es_proxy():
    s = site({r"/segunda-mano/\?": fixture(__file__, "coches_net/search.html")}, net_cls=NoProxyNet)
    cards = list(s.search(Q))
    assert [c.site_ref for c in cards] == ["900000001", "900000002", "900000003"]
    a, b, c = cards
    assert a.url == AD_PRIV and a.seller_type == "private" and a.phones == ["+34555000101"] and a.power_kw == 150
    assert (a.price, a.km, a.year, a.location) == (29990, 41000, 2023, "Valencia, Valencia")
    assert a.thumb == "https://img.example.invalid/cn/a1.jpg" and a.created == "2026-11-02T10:00:00Z"
    assert b.sponsored and b.seller_type == "dealer" and b.price_is_net is True     # isTop, dealer without VAT
    assert c.phones == [] and c.thumb == "https://img.example.invalid/cn/c1.jpg"    # hidePhone
    assert s.net.loads == 1     # totalPages 1 → one load


def test_page_budget_two_per_hour_shared_ledger(monkeypatch):
    """Real Net + pace ledger, no ES proxy (page route): the 3rd page load in an hour is refused, also when another
    agent's plugin instance asks — the budget belongs to the IP, not to one run (11-03)."""
    html = fixture(__file__, "coches_net/search.html")
    monkeypatch.setattr(_net, "http", lambda url, **kw: Response(200, url, html))
    home = Path(os.environ["CARHUNT_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text("owner: {tz: UTC}\nsites:\n  overrides:\n    coches.net: {pace: {min_gap_s: 0}}\n")
    for _ in range(2):
        list(base.get("coches.net").search(SearchQuery(make="Volkswagen", model="ID.4")))
    with pytest.raises(PaceExceeded) as e:
        list(base.get("coches.net").search(SearchQuery(make="Volkswagen", model="ID.4")))
    assert "2/rolling hour" in e.value.reason


def test_gateway_ad_dealer_and_private():
    s = site({r"/details/900000101$": fixture(__file__, "coches_net/details_dealer.json"),
              r"/details/900000102$": fixture(__file__, "coches_net/details_private.json")})
    ad = s.ad(GW_AD)
    assert (ad.site_ref, ad.price, ad.price_is_net, ad.km, ad.year, ad.first_registration) == (
        "900000101", 30001, True, 20001, 2023, "2023")
    assert (ad.power_hp, ad.power_kw, ad.drive, ad.gearbox, ad.fuel, ad.battery_kwh) == (
        229, 168, "rear", "automatic", "Eléctrico", 77.4)
    assert ad.vin == "SYN0000000000CN01" and ad.equipment == ["Bomba de calor", "Techo panorámico"]
    assert ad.seller.type == "dealer" and ad.seller.name == "Synthetic Dealer" and ad.seller.postcode == "28001"
    assert ad.phones == ["+34555000301"] and ad.whatsapp == "+34555000301" and ad.status == "active"
    assert ad.photos == ["https://img.example.invalid/cn/d1.jpg", "https://img.example.invalid/cn/d2.jpg"]
    assert "raw" not in ad.to_dict()
    p = s.ad(GW_AD.replace("900000101", "900000102"))
    assert p.seller.type == "private" and p.phones == [] and p.first_registration == "2023-03"
    assert p.price_is_net is None          # a private sale has no VAT: not a net price


def test_page_ad_dealer_and_private():
    s = site({"900000002": fixture(__file__, "coches_net/ad.html"),
              "900000001": fixture(__file__, "coches_net/ad_private.html")}, net_cls=NoProxyNet)
    ad = s.ad(AD)
    assert (ad.site_ref, ad.price, ad.price_is_net, ad.first_registration, ad.km) == (
        "900000002", 31000, True, "2023-03", 12000)
    assert (ad.power_kw, ad.power_hp, ad.drive, ad.gearbox, ad.color, ad.battery_kwh) == (
        220, 299, "all", "automatic", "white", 77.0)
    assert ad.vin == "SYN0000000000CN02" and ad.equipment == ["Bomba de calor"]
    assert ad.seller.type == "dealer" and ad.seller.city == "Elche" and ad.phones == ["+34555000202"]
    p = s.ad(AD_PRIV)
    assert p.seller.type == "private" and p.phones == [] and p.drive == "rear" and p.power_kw == 150


def test_phone_reveal():
    priv = RawAd(url=AD_PRIV, site="coches.net", site_ref="900000001")
    net = RecNet("coches.net", {r"/details/900000001/phone": {"phone": "555000909"}})
    s = base.get("coches.net", net=net)
    assert s.phone(priv) == []                                   # no reveal without reveal=True
    assert net.calls == []
    assert s.phone(priv, reveal=True) == ["+34555000909"]
    assert net.sent[-1]["country"] == "ES" and net.sent[-1]["kind"] == "phone"
    hidden = site({r"/phone": Response(204, "x")})
    assert hidden.phone(priv, reveal=True) == []
    with pytest.raises(base.Blocked):
        site({r"/phone": Response(403, "x", "<html>Pardon Our Interruption</html>")}).phone(priv, reveal=True)
    with pytest.raises(ProxyUnavailable):                        # fail closed: never from a non-ES IP
        site({}, net_cls=NoProxyNet).phone(priv, reveal=True)


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({r"/details/": Response(403, GW_AD, "Pardon Our Interruption")}).ad(GW_AD)
    with pytest.raises(base.Gone):
        site({r"/details/": Response(404, GW_AD)}).ad(GW_AD)
    with pytest.raises(base.Blocked):     # 200 bot page on the page route (Imperva answers 200 on navigations)
        site({"900000002": "<html>Ups! Parece que algo no va bien... eres un bot</html>"}, NoProxyNet).ad(AD)
    with pytest.raises(base.Blocked):     # page without data = wall/changed page, never gone
        site({"900000002": "<html>nothing</html>"}, NoProxyNet).ad(AD)
    gone = site({"900000002": Response(302, AD, location="https://www.coches.net/volkswagen/id4/segunda-mano/"),
                 r"/volkswagen/id4/segunda-mano/": fixture(__file__, "coches_net/list_ad_gone.html")}, NoProxyNet)
    with pytest.raises(base.Gone):
        gone.ad(AD)


def test_liveness():
    assert site({"900000002": Response(200, AD, "<html>900000002</html>")}).is_live(AD).state == "live"
    lv = site({"900000002": Response(302, AD, location="https://www.coches.net/volkswagen/id4/segunda-mano/")}) \
        .is_live(AD)
    assert lv.state == "removed" and not lv.soft                 # the site's own gone redirect
    assert site({"900000002": Response(410, AD)}).is_live(AD).state == "removed"
    assert site({"900000002": Response(200, AD, "<html>other</html>")}).is_live(AD).state == "unknown"
    with pytest.raises(base.Blocked):
        site({"900000002": Response(200, AD, "<html>eres un bot</html>")}).is_live(AD)
