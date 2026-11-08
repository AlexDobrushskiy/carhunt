"""Transport rules: country routing fails closed, hourly cap, per-run cap, fresh browser profile per batch."""
import contextlib
import sys
import types

import pytest

from carhunt.access.errors import PaceExceeded, ProxyUnavailable
from carhunt.sites import _net


@pytest.fixture(autouse=True)
def no_shared_pace(monkeypatch):
    """In-process pacing only (no ledger), no real sleeps, no sockets."""
    monkeypatch.setitem(sys.modules, "carhunt.access.pace", None)
    monkeypatch.setattr(_net.time, "sleep", lambda s: None)
    calls = []

    def fake_http(url, **kw):
        calls.append((url, kw.get("proxy")))
        return _net.Response(200, url, "ok")
    monkeypatch.setattr(_net, "http", fake_http)
    return calls


def net(**pace):
    return _net.Net("t", {"site": "t", "pace": {"min_gap_s": 0, **pace}})


def test_country_route_fails_closed_before_pacing(monkeypatch, no_shared_pace):
    monkeypatch.setitem(sys.modules, "carhunt.access.proxy", None)
    n = net()
    with pytest.raises(ProxyUnavailable):
        n.get("https://t.example.invalid/a", country="ES")
    assert n.loads == 0 and no_shared_pace == []


def test_country_ip_site_reads_through_proxy(monkeypatch, no_shared_pace):
    proxy = types.SimpleNamespace(get=lambda cc, sticky_minutes: f"http://proxy-{cc}.example.invalid:1")
    monkeypatch.setitem(sys.modules, "carhunt.access.proxy", proxy)
    monkeypatch.setattr(sys.modules["carhunt.access"], "proxy", proxy, raising=False)
    n = _net.Net("t", {"site": "t", "country_ip": "FR", "pace": {"min_gap_s": 0, "max_loads_per_run": 1}})
    n.get("https://t.example.invalid/a")
    assert no_shared_pace == [("https://t.example.invalid/a", "http://proxy-FR.example.invalid:1")]
    with pytest.raises(PaceExceeded):   # the site's own country route counts toward its per-run cap
        n.get("https://t.example.invalid/b")


def test_hourly_cap_without_ledger():
    n = net(max_loads_per_hour=2)
    n.get("https://t.example.invalid/1")
    n.get("https://t.example.invalid/2")
    with pytest.raises(PaceExceeded) as e:
        n.get("https://t.example.invalid/3")
    assert "max_loads_per_hour" in e.value.reason


def test_fresh_profile_every_n_browser_loads(monkeypatch):
    opened = []

    class Page:
        def evaluate(self, js, arg):
            return {"status": 200, "url": arg[0], "text": "ok"}

    @contextlib.contextmanager
    def tab(route, *, site=None, country=None, fresh=False):
        opened.append(fresh)
        yield Page()

    monkeypatch.setitem(sys.modules, "carhunt.access.session", types.SimpleNamespace(tab=tab))
    monkeypatch.setattr(sys.modules["carhunt.access"], "session", sys.modules["carhunt.access.session"], raising=False)
    n = _net.Net("t", {"site": "t", "route": "plain-chrome", "pace": {"min_gap_s": 0, "fresh_profile_every": 2}})
    for i in range(5):
        n.browser_get(f"https://t.example.invalid/{i}")
    assert opened == [True, True, True]   # 2 + 2 + 1 loads, each batch on a throwaway profile
