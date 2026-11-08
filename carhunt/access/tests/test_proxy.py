import base64
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from carhunt.access import geo, pace, proxy, session
from carhunt.access.errors import LeaseBusy, ProxyUnavailable

FIXTURES = Path(__file__).parent / "fixtures" / "access-sites"
PW = "s3cret-pw"


class FakeProvider(proxy.Provider):
    name = "fake"

    def __init__(self):
        self.calls = []

    def url(self, country, session_id, sticky_minutes):
        self.calls.append((country, session_id, sticky_minutes))
        return f"http://user-x-{country}:{PW}@127.0.0.1:9"


def echo(country, home_ip="198.51.100.1", exit_ip="203.0.113.7"):
    calls = []

    def fetch(url, proxy_url):
        calls.append(proxy_url)
        if proxy_url is None:
            return {"ip": home_ip, "country": "PT"}
        return {"ip": exit_ip, "country": country}
    fetch.calls = calls
    return fetch


@pytest.fixture
def env(carhunt_home, monkeypatch):
    monkeypatch.setenv("CARHUNT_SITES_DIR", str(FIXTURES))
    return carhunt_home


def test_wrong_country_fails_closed_and_sends_no_site_request(env, monkeypatch):
    prov, site_calls = FakeProvider(), []
    monkeypatch.setattr(proxy, "provider", lambda: prov)
    monkeypatch.setattr(proxy, "_fetch_json", echo("DE"))
    monkeypatch.setattr(session, "_http_transport",
                        lambda purl: lambda *a: site_calls.append(a) or session.FetchResult(200, {}, "ok"))
    with pytest.raises(ProxyUnavailable) as e:
        with session.tab("http", country="fr", site="sessfix") as t:
            t.goto("https://sessfix.example.invalid/")
    assert site_calls == []
    assert PW not in str(e.value)
    assert pace.check("sessfix", "load", via="fr").used_hour == 0


def test_right_country_passes_and_uses_the_proxy(env, monkeypatch):
    prov, used = FakeProvider(), []
    monkeypatch.setattr(proxy, "provider", lambda: prov)
    monkeypatch.setattr(proxy, "_fetch_json", echo("FR"))

    def transport(purl):
        used.append(purl)
        return lambda *a: session.FetchResult(200, {}, "<title>ok</title>")
    monkeypatch.setattr(session, "_http_transport", transport)
    with session.tab("http", country="FR", site="sessfix") as t:
        assert t.goto("https://sessfix.example.invalid/") == 200
    assert used and used[0].startswith("http://user-x-fr:")
    assert pace.check("sessfix", "load", via="fr").used_hour == 1


def test_verify_exit_cases():
    url = f"http://u:{PW}@127.0.0.1:9"
    assert proxy.verify_exit(url, "fr", fetch=echo("FR"), echo_url="https://echo.invalid/") == "203.0.113.7"
    with pytest.raises(ProxyUnavailable, match="direct IP"):
        proxy.verify_exit(url, "fr", fetch=echo("FR", exit_ip="198.51.100.1"), echo_url="https://echo.invalid/")

    def boom(u, p):
        raise OSError(f"connect failed {p}")
    with pytest.raises(ProxyUnavailable) as e:
        proxy.verify_exit(url, "fr", fetch=boom, echo_url="https://echo.invalid/")
    assert PW not in str(e.value)
    nested = {"proxy": {"ip": "203.0.113.9"}, "country": {"code": "es"}}
    assert proxy.parse_echo(nested) == ("203.0.113.9", "ES")


def test_none_provider(env, capsys):
    assert isinstance(proxy.provider(), proxy.NoneProvider)  # nothing configured
    with pytest.raises(ProxyUnavailable, match="net.proxy.provider"):
        proxy.get("fr")
    assert proxy.main(["test", "fr"]) == 2
    assert "carhunt secret set proxy_credentials" in capsys.readouterr().out


def test_decodo_url_sticky_and_redacted(env, monkeypatch):
    (env / "config.yaml").write_text("owner: {tz: UTC}\nnet: {proxy: {provider: decodo, credentials: secret:proxy_credentials}}\n")
    monkeypatch.setenv("CARHUNT_SECRET_PROXY_CREDENTIALS", f"acct1:{PW}")
    p = proxy.provider()
    assert isinstance(p, proxy.DecodoProvider) and PW not in repr(p)
    url = proxy.get("FR", 60, prov=p)
    assert "user-acct1-country-fr-session-" in url and "sessionduration-30" in url  # clamped to ≤30
    assert url.endswith("@gate.decodo.com:7000")
    assert proxy.get("fr", prov=p).split("session-")[1] == url.split("session-")[1]  # one sticky id per run
    assert PW not in proxy.redact(url) and "gate.decodo.com" in proxy.redact(url)


# ---------- forwarder ----------

class _UpstreamProxy(threading.Thread):
    """Records the request head and answers 200."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.heads = []

    def run(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                buf = b""
                while b"\r\n\r\n" not in buf:
                    d = c.recv(4096)
                    if not d:
                        break
                    buf += d
                self.heads.append(buf.decode())
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")


def _through(proxy_url, url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url}))
    with opener.open(url, timeout=5) as r:
        return r.read()


def test_forwarder_injects_auth():
    up = _UpstreamProxy()
    up.start()
    with proxy.Forwarder(f"http://user-a:{PW}@127.0.0.1:{up.port}") as fwd:
        assert _through(fwd.url, "http://site.example.invalid/x") == b"ok"
    up.sock.close()
    head = up.heads[0]
    assert "Proxy-Authorization: Basic " + base64.b64encode(f"user-a:{PW}".encode()).decode() in head
    assert "Connection: close" in head


def test_forwarder_fails_closed_when_upstream_dead():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    target = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=target.serve_forever, daemon=True).start()
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()
    try:
        with proxy.Forwarder(f"http://u:p@127.0.0.1:{dead_port}") as fwd:
            with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
                _through(fwd.url, f"http://127.0.0.1:{target.server_address[1]}/direct")
    finally:
        target.shutdown()
    assert hits == []


# ---------- geo lease ----------

def test_geo_wrong_exit_never_launches_and_releases(env):
    launched = []

    def verify(url, cc):
        raise ProxyUnavailable("exit country DE != FR")
    with pytest.raises(ProxyUnavailable):
        with geo.lease("fr", "a", prov=FakeProvider(), verify=verify, launcher=lambda *a: launched.append(a),
                       closer=lambda p: None):
            pass
    assert launched == [] and geo.held("fr") is None


def test_geo_lease_exclusive_and_flags(env):
    seen, closed = [], []

    def launcher(profile, args, envv):
        seen.append((profile, args, envv))
        return 19999, 1
    kw = dict(prov=FakeProvider(), verify=lambda url, cc: "203.0.113.7", launcher=launcher,
              closer=closed.append, alive=lambda port: True)
    with geo.lease("fr", "a", **kw) as g:
        assert g.exit_ip == "203.0.113.7" and g.profile.name == "geo-fr"
        assert geo.held("fr")["holder"] == "a"
        with pytest.raises(LeaseBusy):
            with geo.lease("fr", "b", wait_s=0, **kw):
                pass
    profile, args, envv = seen[0]
    assert envv == {"TZ": "Europe/Paris"}
    assert "--lang=fr-FR" in args and "--blink-settings=imagesEnabled=false" in args
    assert any(a.startswith("--proxy-server=http://127.0.0.1:") for a in args)
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in args
    assert not any(PW in a for a in args)  # Chrome only sees the local forwarder
    assert closed == [profile] and geo.held("fr") is None
    assert "identity" not in str(profile)


def test_geo_profile_never_launches_without_proxy_flags(env):
    # plainchrome itself refuses a geo-* profile without the geo flags: no load from the home IP
    from carhunt.access import plainchrome
    with pytest.raises(RuntimeError, match="geo profiles launch only"):
        plainchrome.start("about:blank", env / "browsers" / "profiles" / "geo-es")
