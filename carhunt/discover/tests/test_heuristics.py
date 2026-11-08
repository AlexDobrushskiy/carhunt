"""heuristics: the vag_meb plug-in fills battery / drive / text options; never claims photo evidence."""
import pytest

from carhunt.discover import heuristics as h, normalize as n
from carhunt.sites.model import RawAd, Seller


def lst(title, desc="", reg="2024-03", power=None, make="Volkswagen", model=None):
    return n.from_ad(RawAd(url="https://x.example.invalid/ad/1", site="x", site_ref="1", make=make, model=model,
                           title=title, description=desc, first_registration=reg, power_kw=power, country="DE",
                           seller=Seller(type="dealer")))


@pytest.mark.parametrize("title,make,reg,power,battery,drive", [
    ("ID.4 Pro", "Volkswagen", "2024-03", 210, 77, "rwd"),
    ("ID.4 Pure", "Volkswagen", "2022-03", None, 52, None),
    ("ID.4 GTX", "Volkswagen", "2023-03", None, 77, "awd"),
    ("ID.4 Pro 4MOTION", "Volkswagen", "2023-03", None, 77, "awd"),
    ("Q4 Sportback 40 e-tron", "Audi", "2025-05", None, 63, "rwd"),
    ("Q4 40 e-tron", "Audi", "2022-05", None, 77, "rwd"),
    ("Q4 35 e-tron", "Audi", "2022-05", None, 52, "rwd"),
    ("Enyaq 85x", "Skoda", "2024-05", None, 77, "awd"),
])
def test_variants_and_drive(title, make, reg, power, battery, drive):
    x = lst(title, reg=reg, power=power, make=make)
    fam = h.apply(x, {})
    assert fam is not None
    assert x.battery_net_kwh == battery
    assert x.drive == drive


def test_stated_power_beats_year_guess():
    x = lst("ID.4 Pro", reg="2024-01", power=150)
    h.apply(x, {})
    assert x.battery_net_kwh == 77 and "battery_basis" in x.facts


def test_text_cues_and_fallback_ask():
    cfg = {"search": {"options_wanted": {"heat_pump": 3, "electric_seats": 2}}}
    x = lst("ID.4 Pro", desc="Wärmepumpe. Navi.")
    h.apply(x, cfg)
    assert x.options["heat_pump"] == ("yes", "ad_text")
    assert any("option-sticker" in a for a in x.asks)
    assert all(src != "photo" for _, src in x.options.values())


def test_unknown_family_untouched():
    x = lst("Model Y Long Range", make="Tesla")
    assert h.apply(x, {}) is None and x.battery_net_kwh is None


def test_decode_pr():
    assert h.decode_pr(["3fu", "4E6", "ZZZ"], "vag_meb") == {
        "pano": {"value": "yes", "code": "3FU", "conf": "confirmed"},
        "power_tailgate": {"value": "yes", "code": "4E6", "conf": "confirmed"}}


def test_plugin_yaml_regexes_compile():
    import re
    for name in h.names():
        p = h.load(name)
        for f in p["families"].values():
            re.compile(f["match"])
        for r in p.get("variants", []) + p.get("drive_rules", []) + p.get("option_cues", []):
            for k in ("match", "unless"):
                if r.get(k):
                    re.compile(r[k])
