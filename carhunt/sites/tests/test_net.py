"""Transport rules through the real pace ledger (temp $CARHUNT_HOME): country routing fails closed, hourly cap,
per-run cap, proxied reads paced on their exit, api kind, fresh browser profile per batch."""
import contextlib
import sys
import types

import pytest
import yaml

from carhunt.access import pace
from carhunt.access.errors import PaceExceeded, ProxyUnavailable
from carhunt.sites import _net


@pytest.fixture(autouse=True)
def calls(monkeypatch, tmp_path):
    """Site `t` described by a temp site.yaml; no sockets."""
    monkeypatch.setenv("CARHUNT_SITES_DIR", str(tmp_path / "sites"))
    sent = []

    def fake_http(url, **kw):
        sent.append((url, kw.get("proxy")))
        return _net.Response(200, url, "ok")
    monkeypatch.setattr(_net, "http", fake_http)
    return sent


def site(tmp_path, **pace_keys) -> dict:
    meta = {"site": "t", "hosts": [r"^t\.example\.invalid$"], "pace": {"min_gap_s": 0, **pace_keys}}
    d = tmp_path / "sites" / "t"
    d.mkdir(parents=True, exist_ok=True)
    (d / "site.yaml").write_text(yaml.safe_dump(meta))
    return meta


def fake_proxy(monkeypatch):
    proxy = types.SimpleNamespace(get=lambda cc, sticky_minutes: f"http://proxy-{cc}.example.invalid:1")
    monkeypatch.setitem(sys.modules, "carhunt.access.proxy", proxy)
    monkeypatch.setattr(sys.modules["carhunt.access"], "proxy", proxy, raising=False)


def test_country_route_fails_closed_before_pacing(tmp_path, calls):
    n = _net.Net("t", site(tmp_path))   # no proxy provider configured → ProxyUnavailable
    with pytest.raises(ProxyUnavailable):
        n.get("https://t.example.invalid/a", country="ES")
    assert n.loads == 0 and calls == [] and pace.check("t", "load", via="es").used_hour == 0


def test_country_ip_site_reads_through_proxy(monkeypatch, tmp_path, calls):
    fake_proxy(monkeypatch)
    n = _net.Net("t", {**site(tmp_path), "country_ip": "FR", "pace": {"min_gap_s": 0, "max_loads_per_run": 1}})
    n.get("https://t.example.invalid/a")
    assert calls == [("https://t.example.invalid/a", "http://proxy-FR.example.invalid:1")]
    assert pace.check("t", "load", via="fr").used_hour == 1 and pace.check("t", "load").used_hour == 0
    with pytest.raises(PaceExceeded):   # the site's own country route counts toward its per-run cap
        n.get("https://t.example.invalid/b")


def test_hourly_cap_from_site_yaml_in_shared_ledger(tmp_path):
    meta = site(tmp_path, max_loads_per_hour=2)
    _net.Net("t", meta).get("https://t.example.invalid/1")
    _net.Net("t", meta).get("https://t.example.invalid/2")   # another run/agent: same budget
    with pytest.raises(PaceExceeded) as e:
        _net.Net("t", meta).get("https://t.example.invalid/3")
    assert "2/rolling hour" in e.value.reason


def test_ledger_key_is_the_site_id_whatever_the_spelling(tmp_path):
    site(tmp_path, max_loads_per_hour=1)
    _net.Net("t", {}).get("https://t.example.invalid/1")
    with pytest.raises(PaceExceeded):
        pace.acquire("t.example.invalid", "load")   # host spelling → same ledger key


def test_api_kind_has_its_own_budget(monkeypatch, tmp_path):
    fake_proxy(monkeypatch)
    meta = site(tmp_path, max_loads_per_hour=1)
    n = _net.Net("t", meta)
    n.get("https://t.example.invalid/page")
    for i in range(3):   # page budget used up; api reads are not page loads
        n.get(f"https://t.example.invalid/api/{i}", kind="api", country="ES")
    assert pace.check("t", "api", via="es").used_hour == 3 and n.loads == 1


def test_fresh_profile_every_n_browser_loads(monkeypatch, tmp_path):
    opened, gotos = [], []

    class Page:
        url = "about:blank"

        def evaluate(self, js, arg):
            return {"status": 200, "url": arg[0], "text": "ok"}

        def goto(self, url, *, wait_until=None, timeout=None, paced=True):
            gotos.append(paced)
            return 200

    @contextlib.contextmanager
    def tab(route, *, site=None, country=None, fresh=False):
        opened.append(fresh)
        yield Page()

    monkeypatch.setitem(sys.modules, "carhunt.access.session", types.SimpleNamespace(tab=tab))
    monkeypatch.setattr(sys.modules["carhunt.access"], "session", sys.modules["carhunt.access.session"], raising=False)
    meta = {**site(tmp_path), "route": "plain-chrome", "tab_home": "https://t.example.invalid/",
            "pace": {"min_gap_s": 0, "fresh_profile_every": 2}}
    n = _net.Net("t", meta)
    for i in range(5):
        n.browser_get(f"https://t.example.invalid/{i}")
    assert opened == [True, True, True]   # 2 + 2 + 1 loads, each batch on a throwaway profile
    assert gotos == [False, False, False]  # tab_home per batch; Net took the slot, the tab must not pace again
    assert pace.check("t", "load").used_hour == 8
