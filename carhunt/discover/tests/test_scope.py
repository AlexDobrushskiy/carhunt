"""scope: keep/drop with a reason code for every config `search` rule."""
import pytest

from carhunt.discover import heuristics, normalize as n, scope
from carhunt.sites.model import RawAd, Seller


def lst(**kw):
    base = dict(url="https://x.example.invalid/ad/1", site="x", site_ref="1", make="Volkswagen", model="ID.4",
                title="Volkswagen ID.4 Pro 77 kWh", price=30000, km=20000, first_registration="2023-04", fuel="bev",
                country="PT", seller=Seller(type="dealer", city="Testville"))
    seller = kw.pop("seller", None)
    base.update(kw)
    if seller:
        base["seller"] = seller
    out = n.from_ad(RawAd(**base))
    return out


def reason(cfg, **kw):
    x = lst(**kw)
    heuristics.apply(x, cfg)
    r = scope.check(x, cfg)
    return r.split(":")[0] if r else None


@pytest.mark.parametrize("kw,code", [
    ({}, None),
    ({"country": "PL"}, "country"),
    ({"seller": Seller(type="dealer", city="Funchal", postcode="9000-100")}, "region"),
    ({"model": "Golf", "title": "Volkswagen Golf GTE"}, "model"),
    ({"model": "ID.3", "title": "Volkswagen ID.3 Pro"}, "model"),
    ({"fuel": "Híbrido enchufable"}, "fuel"),
    ({"first_registration": "2019-05"}, "year"),
    ({"first_registration": None}, "reg"),
    ({"km": 95000}, "km"),
    ({"price": 450}, "price_sanity"),
    ({"price": 45000}, "price"),
    ({"description": "Leasingübernahme, Rate 399 €/Monat"}, "flag"),
    ({"description": "Hagelschaden"}, "flag"),
    ({"title": "Volkswagen ID.4 Pure 52 kWh"}, "hard_filter"),
])
def test_reasons(cfg, kw, code):
    assert reason(cfg, **kw) == code


def test_private_abroad_rule(cfg):
    cfg["search"]["private_sellers_abroad"] = False
    assert reason(cfg, country="ES", seller=Seller(type="private", city="Testciudad")) == "seller"
    assert reason(cfg, country="ES", seller=Seller(type="dealer", city="Testciudad")) is None
    assert reason(cfg, country="PT", seller=Seller(type="private", city="Testville")) is None


def test_model_match_uses_title_not_description(cfg):
    x = lst(model=None, title="Volkswagen ID.4 Pro", description="Also in stock: Skoda Enyaq, Audi Q4 e-tron")
    assert scope.check(x, cfg) is None and x.family == "Volkswagen ID.4" and x.tier == 1
    y = lst(make="Audi", model=None, title="Audi Q4 Sportback 45 e-tron")
    assert scope.check(y, cfg) is None and y.family == "Audi Q4 e-tron" and y.tier == 2


def test_partial_lets_unknowns_through(cfg):
    x = lst(first_registration=None, km=None, price=None)
    assert scope.check(x, cfg, partial=True) is None


def test_distance_limit(cfg):
    cfg["search"]["max_distance_km"] = 500
    x = lst()
    x.distance_est_km = 900
    assert scope.check(x, cfg).startswith("distance")
