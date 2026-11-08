"""Standvirtual: query builder, __NEXT_DATA__ parsers, offline phone/VIN decode (synthetic cipher), liveness."""
import base64
import hashlib
import json
import os
import urllib.parse

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from carhunt.sites import base
from carhunt.sites._net import Response
from carhunt.sites.model import SearchQuery
from carhunt.sites.standvirtual_com import cipher
from carhunt.sites.testing import FakeNet, fixture

SALT = "5a1f0000-0000-4000-8000-00000000c0de"          # synthetic, not the site's
UUID = "00000000-0000-4000-8000-0000000000aa"
STAND = "700001"
AD = "https://www.standvirtual.com/carros/anuncio/volkswagen-id-4-pro-synthetic-ID0SYN01x.html"
CHUNK = "https://www.standvirtual.com/_next/static/chunks/pages/ad-0000synthetic.js"
RUNTIME = "https://www.standvirtual.com/_next/static/chunks/webpack-0000synthetic.js"
VIN = "SYNTHETICVIN00001"  # privacy-check: allow


def encrypt(plain: str, key_source: str, salt: str = SALT, ver: str = "1") -> str:
    """The site's scheme, written independently of the plugin: b64(ct+tag).ver.b64(iv)."""
    pw = hashlib.sha256(key_source.encode()).digest()[:16].hex().encode()
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt.encode(), 10000 if ver == "0" else 10).derive(pw)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plain.encode(), None)
    return f"{base64.b64encode(ct).decode()}.{ver}.{base64.b64encode(iv).decode()}"


def bundle(salt: str = SALT) -> str:
    return ('(self.webpackChunk=self.webpackChunk||[]).push([[1],{1:function(e,t,n){const r="not-the-salt-0000";'
            f'async function d(e,t){{const n=new TextEncoder,a=await crypto.subtle.importKey("raw",n.encode(t),'
            f'"PBKDF2",!1,["deriveKey"]);return crypto.subtle.deriveKey({{name:"PBKDF2",salt:n.encode("{salt}"),'
            'iterations:"0"===e?1e4:10,hash:"SHA-256"},a,{name:"AES-GCM",length:256},!1,["decrypt"])}}}]);')


def advert(phone_key: str = STAND, **kw) -> dict:
    a = json.loads(fixture(__file__, "standvirtual_com/advert.json"))
    a["phoneNumbers"] = [encrypt("+351 555 000 101", phone_key)]
    a["parametersDict"]["vin"]["values"][0]["value"] = encrypt(VIN, a["id"])
    a.update(kw)
    return a


def page(a: dict) -> str:
    nd = json.dumps({"props": {"pageProps": {"advert": a}}})
    return (f'<html><head><script src="{RUNTIME}" defer></script><script src="/_next/static/chunks/pages/'
            f'ad-0000synthetic.js" defer></script></head><body><script id="__NEXT_DATA__" type="application/json">'
            f'{nd}</script></body></html>')


def site(routes=None, **kw):
    return base.get("standvirtual.com", net=FakeNet("standvirtual.com", routes), **kw)


def test_query_builder():
    u = site().search_url(SearchQuery(make="Volkswagen", model="ID.4", year_min=2023, km_max=50000, price_max=42000,
                                      fuel="bev", seller="private"), page=2)
    p = urllib.parse.urlparse(u)
    assert p.netloc == "www.standvirtual.com" and p.path == "/carros/vw/id-4"
    assert dict(urllib.parse.parse_qsl(p.query)) == {
        "search[filter_float_first_registration_year:from]": "2023", "search[filter_float_price:to]": "42000",
        "search[filter_float_mileage:to]": "50000", "search[filter_enum_fuel_type]": "electric",
        "search[private_business]": "private", "search[order]": "created_at:desc", "page": "2"}
    assert site().search_url(SearchQuery(make="Audi", model="Q4 e-tron", sort="relevance")) == \
        "https://www.standvirtual.com/carros/audi/q4-e-tron"
    with pytest.raises(base.Unsupported):
        site().search_url(SearchQuery(make="Kia", model="EV6", sort="price"))


def test_search_parses_cards_and_pages():
    s = site({r"/carros/vw/id-4": fixture(__file__, "standvirtual_com/search.html")})
    cards = list(s.search(SearchQuery(make="Volkswagen", model="ID.4", max_pages=3)))
    assert len(cards) == 4 and len(s.net.calls) == 2          # totalCount 34, 32/page → stops after page 2
    c = cards[0]
    assert (c.site_ref, c.price, c.km, c.year, c.first_registration) == ("8000000001", 31900, 42000, 2023, "2023")
    assert (c.make, c.model, c.fuel, c.power_kw, c.seller_type) == ("VW", "ID.4", "electric", 150, "private")
    assert c.url.endswith("-ID0SYN01x.html") and c.price_is_net is False and not c.sponsored
    assert c.created == "2026-11-01T10:00:00Z" and c.location == "Aveiro, Aveiro"
    assert cards[1].sponsored and cards[1].seller_type == "dealer"
    assert s.ad_id(c.url) == "ID0SYN01x"


def test_cipher_roundtrip_and_salt_discovery():
    t = encrypt("+351 555 000 102", UUID)
    assert cipher.decrypt(t, UUID, SALT) == "+351 555 000 102"
    assert cipher.decrypt(encrypt("x", UUID, ver="0"), UUID, SALT) == "x"
    with pytest.raises(cipher.CipherError):
        cipher.decrypt(t, UUID, "wrong-salt-000000")
    assert cipher.decode(t, [None, "other", UUID], SALT) == "+351 555 000 102"
    cands = cipher.salt_candidates(bundle())
    assert cands[0] == SALT and "not-the-salt-0000" in cands
    urls = cipher.script_urls(page({}), "https://www.standvirtual.com")
    assert urls == [CHUNK, RUNTIME]      # app chunks before the webpack runtime


def test_ad_decodes_phone_and_vin_offline():
    s = site({"ID0SYN01x": page(advert()), r"/pages/ad-": bundle(), r"/webpack-": "/* runtime */"})
    ad = s.ad(AD)
    assert ad.phones == ["+351 555 000 101"] and ad.vin == VIN      # stand seller: key = standId
    assert [u for _, _, u in s.net.calls] == [AD, CHUNK]             # one bundle read, no reveal call
    assert ad.site_ref == "8000000001" and ad.extra["url_id"] == "ID0SYN01x"
    assert (ad.make, ad.model, ad.version, ad.first_registration, ad.km) == ("VW", "ID.4", "Pro Performance",
                                                                            "2023-03", 42000)
    assert (ad.power_hp, ad.power_kw, ad.battery_kwh, ad.drive, ad.owners) == (204, 150, 77.0, "rear-wheel-drive", 1)
    assert ad.service_history is True and ad.price == 31900 and ad.price_is_net is False
    assert ad.seller.type == "dealer" and ad.seller.postcode == "3800-000" and ad.extra["seller_active_ads"] == 12
    assert ad.description == "Carro sintético para testes." and "heat_pump" in ad.equipment
    assert ad.photos == ["https://img.example.invalid/sv/a.jpg", "https://img.example.invalid/sv/b.jpg"]
    assert s.phone(ad) == ["+351 555 000 101"]
    # salt cached on disk: a fresh instance decodes the next ad without reading any bundle
    s2 = site({"ID0SYN01x": page(advert(phone_key=UUID))})
    assert s2.ad(AD).phones == ["+351 555 000 101"] and len(s2.net.calls) == 1


def test_undecodable_phone_is_dropped_with_a_note():
    a = advert()
    a["phoneNumbers"].append(encrypt("+351 555 000 999", "someone-else"))
    ad = site({"ID0SYN01x": page(a), r"/pages/ad-": bundle(), r"/webpack-": ""}).ad(AD)
    assert ad.phones == ["+351 555 000 101"]                   # the good one only, never a raw token
    assert ad.extra["phones_undecoded"] == 1 and "decode" in ad.extra


def test_no_salt_found_yields_no_phone():
    a = advert()
    ad = site({"ID0SYN01x": page(a), r"/pages/ad-": bundle("other-salt-0000000"), r"/webpack-": ""}).ad(AD)
    assert ad.phones == [] and ad.vin is None
    assert ad.extra["phones_undecoded"] == 1 and ad.extra["vin_undecoded"] is True
    assert "salt not found" in ad.extra["decode"]
    assert site(salt=SALT).phone(ad) == ["+351 555 000 101"]  # explicit salt override, no network


def test_blocked_and_gone():
    with pytest.raises(base.Blocked):
        site({"ID0SYN01x": Response(403, AD)}).ad(AD)
    with pytest.raises(base.Gone):
        site({"ID0SYN01x": Response(410, AD)}).ad(AD)
    with pytest.raises(base.Blocked):
        site({"ID0SYN01x": "<html>no data</html>"}).ad(AD)
    with pytest.raises(base.Blocked):     # salt discovery stops on a blocked bundle too
        site({"ID0SYN01x": page(advert()), r"/pages/ad-": Response(403, CHUNK)}).ad(AD)


def test_liveness():
    assert site({"ID0SYN01x": Response(410, AD)}).is_live(AD).state == "removed"
    assert site({"ID0SYN01x": Response(200, AD, page(advert()) + AD)}).is_live(AD).state == "live"
    lv = site({"ID0SYN01x": Response(301, AD, location="https://www.standvirtual.com/carros/vw")}).is_live(AD)
    assert lv.state == "removed" and lv.soft
    with pytest.raises(base.Blocked):
        site({"ID0SYN01x": Response(429, AD)}).is_live(AD)
