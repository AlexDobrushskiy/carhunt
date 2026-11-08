import contextlib
import json
import os
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from carhunt.access import pace, session
from carhunt.access.errors import Blocked, PaceExceeded

FIXTURES = Path(__file__).parent / "fixtures" / "access-sites"

PAGES = {
    "/": (200, "text/html", "<html><head><title>Fixture Home</title></head><body>"
                            "<script src='https://js.datadome.co/tags.js'></script>hello</body></html>"),
    "/dd": (403, "text/html", "<html><body><script src='https://geo.captcha-delivery.com/captcha/?x=1'>"
                              "</script></body></html>"),
    "/plain403": (403, "text/html", "<html><body>Forbidden</body></html>"),
    "/gone": (404, "text/html", "<html><title>Not found</title></html>"),
    "/api": (200, "application/json", json.dumps({"ok": True, "n": 3})),
}


@pytest.fixture
def server():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append((self.path, self.headers.get("User-Agent", "")))
            st, ctype, body = PAGES.get(self.path, (500, "text/plain", "?"))
            raw = body.encode()
            self.send_response(st)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.base = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.hits = hits
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def env(carhunt_home, monkeypatch):
    monkeypatch.setenv("CARHUNT_SITES_DIR", str(FIXTURES))
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    return carhunt_home


def test_http_goto_title_fetch(env, server):
    with session.tab("http", site="sessfix") as t:
        assert t.route == "http" and t.page is None
        assert t.goto(server.base + "/") == 200  # a DataDome JS tag on a normal page is not a block
        assert t.title() == "Fixture Home"
        assert "hello" in t.html()
        r = t.fetch(server.base + "/api")
        assert r.status == 200 and json.loads(r.text)["n"] == 3
    assert pace.check("sessfix", "load").used_hour == 2  # goto + fetch both paced


def test_http_blocked_on_datadome_403(env, server):
    with session.tab("http", site="sessfix") as t:
        with pytest.raises(Blocked) as e:
            t.goto(server.base + "/dd")
    assert e.value.signature == "datadome" and e.value.site == "sessfix"
    with session.tab("http", site="sessfix") as t, pytest.raises(Blocked) as e:
        t.goto(server.base + "/plain403")
    assert e.value.signature == "http-403"


def test_404_is_ad_gone_not_a_block(env, server):
    with session.tab("http", site="sessfix") as t:
        assert t.goto(server.base + "/gone") == 404


def test_no_site_means_no_pace_and_no_raise(env, server):
    with session.tab("http") as t:
        assert t.goto(server.base + "/dd") == 403
    assert pace.status() == []


def test_pace_is_consulted_before_the_request(env, server):
    with session.tab("http", site="sesscap") as t:
        t.goto(server.base + "/")
        with pytest.raises(PaceExceeded):
            t.goto(server.base + "/")
    assert len(server.hits) == 1


@pytest.mark.parametrize("status,body,headers,want", [
    (200, "<title>Just a moment...</title>", {}, "cloudflare-challenge"),
    (403, "<title>Just a moment...</title>", {}, "cloudflare"),
    (200, "ok", {"cf-mitigated": "challenge"}, "cloudflare-challenge"),
    (403, "<a href='https://errors.edgesuite.net/x'>Reference&#32;&#35;18</a>", {}, "akamai-403"),
    (200, "<div id='px-captcha'></div>", {}, "perimeterx-challenge"),
    (200, "<script src='/_Incapsula_Resource?x'></script>", {}, "imperva-challenge"),
    (429, "slow down", {}, "http-429"),
    (403, "", {"Server": "CloudFront"}, "cloudfront-403"),
    (410, "<title>Just a moment...</title>", {}, None),
    (200, "<script src='https://js.datadome.co/tags.js'></script><script>reese84</script>", {}, None),
    (500, "oops", {}, None),
])
def test_detect_block(status, body, headers, want):
    assert session.detect_block(status, body, headers) == want


class FakePage:
    def __init__(self, html="<title>T</title>"):
        self._html, self.urls = html, []

    def evaluate(self, js, arg=None):
        if "responseStatus" in js:
            return 200
        return {"status": 200, "headers": {}, "text": "{}"} if arg else 42

    def goto(self, url, wait_until=None):
        self.urls.append(url)
        return types.SimpleNamespace(status=410)

    def content(self):
        return self._html

    def title(self):
        return "T"


def test_plain_chrome_opens_on_first_goto_and_releases(env, monkeypatch):
    import carhunt.access.plainchrome as pc
    events = []

    @contextlib.contextmanager
    def open_tab(url, *, profile=None, **kw):
        events.append(("open", url, profile))
        try:
            yield object(), FakePage()
        finally:
            events.append(("release",))
    monkeypatch.setattr(pc, "open_tab", open_tab)
    with pytest.raises(RuntimeError, match="boom"):
        with session.tab("plain-chrome", site="sessfix") as t:
            assert t.page is None  # nothing launched before the first URL
            assert t.goto("https://sessfix.example.invalid/a") == 200
            assert t.goto("https://sessfix.example.invalid/b") == 410
            assert t.evaluate("1+1") == 42
            raise RuntimeError("boom")
    assert events == [("open", "https://sessfix.example.invalid/a", None), ("release",)]
    assert pace.check("sessfix", "load").used_hour == 2


def test_failed_launch_refunds_the_pace_slot(env, monkeypatch):
    import carhunt.access.plainchrome as pc

    def open_tab(url, **kw):
        raise RuntimeError("Chrome did not start")
    monkeypatch.setattr(pc, "open_tab", open_tab)
    with pytest.raises(RuntimeError), session.tab("plain-chrome", site="sesscap") as t:
        t.goto("https://sesscap.example.invalid/")
    assert pace.check("sesscap", "load").allowed


def test_identity_route_leases_and_always_releases(env, monkeypatch):
    import carhunt.access.plainchrome as pc
    log = []
    fake = types.ModuleType("carhunt.access.identity")
    fake.acquire = lambda holder, name=None, *, any_=False: log.append(("acquire", any_)) or types.SimpleNamespace(
        name="identity-b", profile=Path("/tmp/fake-identity-b"), mcp_port=1, debug_port=2)
    fake.release = lambda holder, name: log.append(("release", name))
    monkeypatch.setitem(sys.modules, "carhunt.access.identity", fake)

    @contextlib.contextmanager
    def open_tab(url, *, profile=None, **kw):
        log.append(("open", str(profile)))
        yield object(), FakePage()
    monkeypatch.setattr(pc, "open_tab", open_tab)
    with pytest.raises(KeyError), session.tab("identity") as t:
        t.goto("https://example.invalid/")
        raise KeyError("fail mid-step")
    assert log == [("acquire", True), ("open", "/tmp/fake-identity-b"), ("release", "identity-b")]


def test_identity_with_country_is_refused(env):
    with pytest.raises(ValueError, match="geo"), session.tab("identity", country="fr"):
        pass


def test_camoufox_missing_has_fix_line(env, monkeypatch):
    monkeypatch.setitem(sys.modules, "camoufox", None)
    monkeypatch.setitem(sys.modules, "camoufox.sync_api", None)
    with pytest.raises(RuntimeError, match="camoufox not installed"), session.tab("camoufox"):
        pass


@pytest.mark.chrome
@pytest.mark.skipif(os.environ.get("CARHUNT_TEST_CHROME") != "1", reason="real Chrome: set CARHUNT_TEST_CHROME=1")
def test_lane_real_chrome_smoke(env, server):
    from carhunt.access import chrome
    with session.tab("lane", site="sessfix") as t:
        assert t.goto(server.base + "/") == 200
        assert t.title() == "Fixture Home"
        assert "HeadlessChrome" not in t.evaluate("navigator.userAgent")
        assert t.fetch(server.base + "/api").status == 200
        assert len(chrome.read_pid_records()) == 1
    assert chrome.read_pid_records() == []  # closed and record dropped
    assert all("HeadlessChrome" not in ua for _, ua in server.hits)
