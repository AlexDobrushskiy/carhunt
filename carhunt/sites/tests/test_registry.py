"""Registry, site.yaml schema for every site, the fake site."""
import json
from pathlib import Path

import jsonschema
import pytest

from carhunt.sites import base
from carhunt.sites.model import SearchQuery

ROOT = Path(base.__file__).parent
SCHEMA = json.loads((ROOT / "site.schema.json").read_text())


@pytest.mark.parametrize("pkg", sorted(p.parent.name for p in ROOT.glob("*/site.yaml")))
def test_site_yaml_schema(pkg):
    meta = dict(base.load_meta(pkg))
    jsonschema.validate(meta, SCHEMA)
    assert base.pkg_of(meta["site"]) == pkg, "package name = site id with dots → _"
    assert (ROOT / pkg / "plugin.py").exists()
    assert (ROOT / pkg / "README.md").exists() or pkg == "fake"


def test_fake_hidden_without_env(monkeypatch):
    monkeypatch.delenv(base.FAKE_ENV, raising=False)
    assert "fake" not in base.ids()
    with pytest.raises(KeyError):
        base.get("fake")


def test_fake_site_roundtrip():
    with base.fake_sites():
        assert "fake" in base.ids()
        s = base.get("fake")
        cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4")))
        assert {c.site_ref for c in cards} == {"fk1001", "fk1004", "fk1005"}
        assert [c.site_ref for c in s.search(SearchQuery(seller="dealer", country="ES"))] == ["fk1002"]
        ad = s.ad(cards[0].url)
        assert ad.vin.startswith("SYN") and ad.phones and ad.seller.type == "private"
        assert base.for_url(cards[0].url).id == "fake"
        assert s.is_live(s.url("fk1003")).state == "removed"
        soft = s.is_live(s.url("fk1004"))
        assert soft.state == "removed" and soft.soft
        assert s.is_live(s.url("fk1001")).state == "live"
        with pytest.raises(base.Gone):
            s.ad(s.url("fk1003"))


def test_fake_block_knob(monkeypatch):
    monkeypatch.setenv("CARHUNT_FAKE_SITES_BLOCK", "search")
    with base.fake_sites():
        with pytest.raises(base.Blocked):
            list(base.get("fake").search(SearchQuery()))


def test_config_overrides_merge(monkeypatch):
    monkeypatch.setattr(base, "overrides", lambda sid: {"country_ip": "FR", "pace": {"min_gap_s": 20}, "wall": "x"})
    meta = base.with_overrides(base.load_meta("autoscout24"))
    assert meta["country_ip"] == "FR" and meta["pace"]["min_gap_s"] == 20
    assert meta["pace"]["max_loads_per_run"] == 120 and meta["wall"] != "x"   # one level deep; wall not overridable


def test_wall_signatures():
    from carhunt.sites._net import Response, raise_for
    for text, sig in (("<h1>Access is temporarily restricted</h1>", "datadome-hard-block"),
                      ("<script src=https://geo.captcha-delivery.com/x>", "datadome"),
                      ("<title>Just a moment...</title>", "cloudflare"),
                      ("Pardon Our Interruption", "imperva")):
        with pytest.raises(base.Blocked) as e:
            raise_for("t", Response(200, "https://t.example.invalid/", text))
        assert e.value.signature == sig
