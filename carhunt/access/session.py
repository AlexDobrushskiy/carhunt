"""`tab(route)` — one page handle over any access route, closed on exit (success or failure).

    from carhunt.access import session
    with session.tab("http", site="autoscout24") as t:
        status = t.goto(url)             # pace.acquire(site, "load") first; Blocked on a bot wall
        data = t.content()
    with session.tab("plain-chrome", site="mobile.de", fresh=True) as t: ...   # throwaway profile
    with session.tab("http", country="es", site="coches.net") as t: ...       # proxied, exit verified first

Handle = a Playwright sync Page on browser routes: anything not defined here (locator, keyboard, context, url,
wait_for_timeout, on, …) goes to the page. Differences: `goto` returns the HTTP status (0 = no response; the first
plain-chrome load happens before Playwright attaches, so there is no Response object), paces and raises Blocked when
`site` is given; `goto(..., paced=False)` for callers that took the pace slot themselves (sites' Net).
The http route has goto/content/html/fetch/url/wait_for_timeout only.

Routes (pick the lowest that works; move up after ONE blocked hit — every blocked hit raises the bot score):
  http          urllib (curl_cffi Chrome impersonation when installed). Most sites ship full data in
                __NEXT_DATA__/RSC/JSON APIs: one request instead of ~50.
  lane          Agent Chrome headless on a temp profile, Playwright over CDP, real-Chrome UA (no "HeadlessChrome").
  plain-chrome  Chrome launched like a person, attach after the first load (Akamai/DataDome catch
                Playwright-launched browsers). `country` → the geo lease for that country.
  identity      plain-chrome on a free identity-pool copy (logged in); released on exit. Hold it for ONE step.
  camoufox      optional anti-detect Firefox.
When `site` is given: pace.acquire(site, "load") before every request; 403/429/challenge pages raise Blocked;
404/410 are NOT blocks, they mean "ad gone".
"""
from __future__ import annotations

import contextlib
import http.cookiejar
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from carhunt.access import pace, proxy
from carhunt.access.errors import Blocked

ROUTES = ("http", "lane", "identity", "plain-chrome", "camoufox")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/142.0.0.0 Safari/537.36")


@dataclass
class FetchResult:
    status: int
    headers: dict = field(default_factory=dict)
    text: str = ""


# ---------- bot-wall detection ----------

# Strong markers: only a challenge/block page carries them (safe on a 200).
_CHALLENGE = [
    ("datadome", re.compile(r"captcha-delivery\.com", re.I)),
    ("cloudflare", re.compile(r"<title>Just a moment\.\.\.</title>|challenges\.cloudflare\.com/cdn-cgi/challenge|"
                              r"cf_chl_opt|Attention Required! \| Cloudflare", re.I)),
    ("imperva", re.compile(r"_Incapsula_Resource|Incapsula incident ID|Pardon Our Interruption", re.I)),
    ("perimeterx", re.compile(r"px-captcha|_pxCaptcha", re.I)),
]
# Weak markers: vendor fingerprints also present on normal pages; they only name a 403/429/503.
_VENDOR = [
    ("datadome", re.compile(r"datadome", re.I)),
    ("imperva", re.compile(r"incapsula|imperva|reese84", re.I)),
    ("cloudflare", re.compile(r"cloudflare|cf-ray", re.I)),
    ("akamai", re.compile(r"errors\.edgesuite\.net|akamai|Reference&#32;&#35;|Zugriff verweigert", re.I)),
    ("cloudfront", re.compile(r"cloudfront|The request could not be satisfied", re.I)),
    ("perimeterx", re.compile(r"perimeterx|Press (&amp;|&) Hold", re.I)),
]


def detect_block(status: int, text: str = "", headers: dict | None = None) -> str | None:
    """Bot-wall signature for a response, or None. 404/410 = ad gone, never a block."""
    if status in (404, 410):
        return None
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    if h.get("cf-mitigated", "").lower() == "challenge":
        return "cloudflare-challenge"
    body = (text or "")[:200_000]
    for name, rx in _CHALLENGE:
        if rx.search(body):
            return name if status in (403, 429, 503) else f"{name}-challenge"
    if status in (403, 429):
        hay = body[:50_000] + " " + " ".join(f"{k}: {v}" for k, v in h.items())
        for name, rx in _VENDOR:
            if rx.search(hay):
                return f"{name}-{status}"
        return f"http-{status}"
    return None


_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


# ---------- Tab ----------

PACE_WAIT_S = 180  # wait this long for a gap/hourly slot, then PaceExceeded (day/run caps never wait)


class Tab:
    """Common page handle. `goto` returns the HTTP status (0 = no response) and raises only Blocked/PaceExceeded,
    and those only when `site` is given."""

    def __init__(self, route: str, *, site: str | None = None, country: str | None = None,
                 pace_wait_s: float = PACE_WAIT_S):
        self.route, self.site, self.country = route, site, country
        self.page: Any = None
        self.pace_wait_s = pace_wait_s
        self._closers: list[Callable[[], Any]] = []

    def _pace(self) -> pace.Ticket | None:
        if not self.site:
            return None
        return pace.acquire(self.site, "load", via=self.country, wait=self.pace_wait_s > 0,
                            max_wait_s=self.pace_wait_s)

    def _check(self, url: str, status: int, text: str, headers: dict | None = None) -> None:
        if self.site:
            sig = detect_block(status, text, headers)
            if sig:
                raise Blocked(sig, site=self.site, url=url, detail=f"HTTP {status}")

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: float | None = None,
             paced: bool = True) -> int:
        raise NotImplementedError

    def html(self) -> str:
        raise NotImplementedError

    def content(self) -> str:
        return self.html()

    def title(self) -> str:
        m = _TITLE.search(self.html() or "")
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""

    def evaluate(self, js: str, arg: Any = None) -> Any:
        raise NotImplementedError(f"evaluate() needs a browser route, not {self.route}")

    def fetch(self, url: str, *, method: str = "GET", headers: dict | None = None, body: str | bytes | None = None,
              paced: bool = True) -> FetchResult:
        raise NotImplementedError

    def on_close(self, fn: Callable[[], Any]) -> None:
        self._closers.append(fn)

    def close(self) -> None:
        while self._closers:
            fn = self._closers.pop()
            with contextlib.suppress(Exception):
                fn()


# ---------- http ----------

Transport = Callable[[str, str, dict, "bytes | None"], FetchResult]


def _http_transport(proxy_url: str | None) -> Transport:
    """curl_cffi with Chrome impersonation when installed (TLS/HTTP2 fingerprint), else urllib. Proxy-aware."""
    try:
        from curl_cffi import requests as cr  # type: ignore[import-not-found]
    except ImportError:
        cr = None
    if cr is not None:
        s = cr.Session(impersonate="chrome", proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None)

        def via_curl(method: str, url: str, headers: dict, body: bytes | None) -> FetchResult:
            try:
                r = s.request(method, url, headers=headers, data=body, timeout=45)
            except Exception:
                return FetchResult(0, {}, "")
            return FetchResult(r.status_code, dict(r.headers), r.text)
        return via_curl

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url} if proxy_url else {}),
        urllib.request.HTTPCookieProcessor(jar))

    def via_urllib(method: str, url: str, headers: dict, body: bytes | None) -> FetchResult:
        hdr = {"User-Agent": UA, "Accept-Language": "en;q=0.8", "Accept": "text/html,application/json,*/*", **headers}
        req = urllib.request.Request(url, data=body, headers=hdr, method=method)
        try:
            with opener.open(req, timeout=45) as r:
                raw, st, rh = r.read(), r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw, st, rh = e.read(), e.code, dict(e.headers or {})
        except (OSError, ValueError):
            return FetchResult(0, {}, "")
        return FetchResult(st, rh, raw.decode("utf-8", "replace"))
    return via_urllib


class HttpTab(Tab):
    def __init__(self, transport: Transport, **kw):
        super().__init__("http", **kw)
        self._t = transport
        self._last = FetchResult(0)
        self.url = "about:blank"

    def _request(self, method: str, url: str, headers: dict | None, body: str | bytes | None,
                 paced: bool) -> FetchResult:
        if paced:
            self._pace()
        data = body.encode() if isinstance(body, str) else body
        r = self._t(method, url, dict(headers or {}), data)
        self._check(url, r.status, r.text, r.headers)
        return r

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: float | None = None,
             paced: bool = True) -> int:
        self._last = self._request("GET", url, None, None, paced)
        self.url = url
        return self._last.status

    @staticmethod
    def wait_for_timeout(ms: float) -> None:
        time.sleep(ms / 1000)

    def html(self) -> str:
        return self._last.text

    def fetch(self, url: str, *, method: str = "GET", headers: dict | None = None, body: str | bytes | None = None,
              paced: bool = True) -> FetchResult:
        return self._request(method, url, headers, body, paced)


# ---------- browsers (Playwright page) ----------

_FETCH_JS = """async ([url, method, headers, body]) => {
  const r = await fetch(url, {method, headers, body: body ?? undefined, credentials: 'include'});
  const h = {}; r.headers.forEach((v, k) => { h[k] = v; });
  return {status: r.status, headers: h, text: await r.text()};
}"""


class BrowserTab(Tab):
    """Tab over a Playwright Page. `opener(url) -> page` (plain-chrome/identity) defers the browser until the first
    goto, because plain-chrome must launch ON the first URL and attach only after it loaded."""

    def __init__(self, route: str, *, page: Any = None, opener: Callable[[str], Any] | None = None, **kw):
        super().__init__(route, **kw)
        self.page, self._opener = page, opener

    def __getattr__(self, name: str) -> Any:
        """Everything else is the Playwright page's (locator, keyboard, context, url, wait_for_timeout, …)."""
        if name.startswith("_"):
            raise AttributeError(name)
        page = self.__dict__.get("page")
        if page is None:
            raise RuntimeError(f"tab.{name}: goto() first (this route opens the browser on the first URL)")
        return getattr(page, name)

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: float | None = None,
             paced: bool = True) -> int:
        ticket = self._pace() if paced else None
        status = 0
        if self.page is None:
            if self._opener is None:
                raise RuntimeError("tab has no page")
            try:
                self.page = self._opener(url)
            except BaseException:
                if ticket:
                    pace.refund(ticket)  # the browser never came up, so the site saw nothing
                raise
            with contextlib.suppress(Exception):  # first load happened before we attached: ask the page
                status = int(self.page.evaluate(
                    "() => (performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0"))
        else:
            try:
                kw = {"timeout": timeout} if timeout is not None else {}
                resp = self.page.goto(url, wait_until=wait_until, **kw)
                status = resp.status if resp else 0
            except Exception:
                status = 0
        self._check(url, status, self.html() if self.site else "")
        return status

    def html(self) -> str:
        if self.page is None:
            return ""
        try:
            return self.page.content()
        except Exception:
            return ""

    def title(self) -> str:
        try:
            return self.page.title() if self.page is not None else ""
        except Exception:
            return super().title()

    def evaluate(self, js: str, arg: Any = None) -> Any:
        if self.page is None:
            raise RuntimeError("goto() first: the browser opens on the first URL")
        return self.page.evaluate(js, arg) if arg is not None else self.page.evaluate(js)

    def fetch(self, url: str, *, method: str = "GET", headers: dict | None = None, body: str | bytes | None = None,
              paced: bool = True) -> FetchResult:
        """In-page fetch (the site's own JSON API from inside a real tab: olx.pt 403s any plain HTTP)."""
        if self.page is None:
            raise RuntimeError("goto() first: in-page fetch needs a loaded page of the site")
        if paced:
            self._pace()
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        try:
            d = self.page.evaluate(_FETCH_JS, [url, method, headers or {}, body])
            r = FetchResult(int(d["status"]), d.get("headers") or {}, d.get("text") or "")
        except Exception:
            r = FetchResult(0)
        self._check(url, r.status, r.text, r.headers)
        return r


# ---------- route builders ----------

def _holder() -> str:
    return os.environ.get("AGTERM_SESSION_ID") or f"session-pid{os.getpid()}"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_debug(port: int, proc: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Agent Chrome exited ({proc.returncode}) before its debug port opened")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Agent Chrome debug port {port} did not open")


def real_chrome_identity(page: Any) -> None:
    """Send what headed Chrome sends: UA without "HeadlessChrome" plus matching client hints, via CDP.
    Playwright's user_agent derives wrong hints and Chrome's --user-agent blanks them."""
    cdp = page.context.new_cdp_session(page)
    ua = cdp.send("Browser.getVersion")["userAgent"].replace("HeadlessChrome/", "Chrome/")
    url = "https://ua-probe.invalid/"  # userAgentData needs a secure context: a fulfilled https page, no network

    def serve(route):
        route.fulfill(content_type="text/html", body="")
    page.route(url, serve)
    try:
        page.goto(url)
        meta = page.evaluate("""async () => {
          const h = await navigator.userAgentData.getHighEntropyValues(["architecture", "bitness", "model",
            "platformVersion", "fullVersionList", "wow64", "formFactors"]);
          const {brands, fullVersionList, platform, platformVersion, architecture, model, mobile, bitness, wow64,
            formFactors} = h;
          return {brands, fullVersionList, platform, platformVersion, architecture, model, mobile, bitness, wow64,
            formFactors};
        }""")
        page.goto("about:blank")
    finally:
        page.unroute(url, serve)
    for k in ("brands", "fullVersionList"):
        for b in meta.get(k) or []:
            if b.get("brand") == "HeadlessChrome":
                b["brand"] = "Google Chrome"
    cdp.send("Emulation.setUserAgentOverride", {"userAgent": ua, "userAgentMetadata": meta})


def _open_lane(t: BrowserTab, proxy_server: str | None) -> None:
    from carhunt.access import chrome
    from playwright.sync_api import sync_playwright
    tmp = Path(tempfile.mkdtemp(prefix="carhunt-lane-"))
    t.on_close(lambda: shutil.rmtree(tmp, ignore_errors=True))
    port = _free_port()
    extra = ["--window-size=1360,900"] + (proxy.chrome_args(proxy_server) if proxy_server else [])
    args = chrome.launch_args(tmp, port, headless=True, extra=extra)
    proc = subprocess.Popen([str(chrome.agent_chrome_path()), *args, "about:blank"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    chrome.write_pid_record(proc.pid, "lane", profile=tmp, debug_port=port, owner=_holder())

    def stop_chrome() -> None:
        with contextlib.suppress(Exception):
            proc.terminate()
            proc.wait(10)
        if proc.poll() is None:
            proc.kill()
            proc.wait(5)
        chrome.drop_pid_record(proc.pid)
    t.on_close(stop_chrome)
    _wait_debug(port, proc)
    pw = sync_playwright().start()
    t.on_close(pw.stop)
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    real_chrome_identity(page)
    t.page = page


def _plain_opener(t: BrowserTab, stack: contextlib.ExitStack, profile: Path | str | None,
                  open_tab: Callable[..., Any] | None = None, *, fresh: bool = False) -> Callable[[str], Any]:
    def opener(url: str) -> Any:
        if open_tab is None:
            from carhunt.access import plainchrome
            fn = lambda u: plainchrome.open_tab(u, profile=profile, fresh=fresh)  # noqa: E731
        else:
            fn = open_tab
        _browser, page = stack.enter_context(fn(url))
        return page
    return opener


def _open_camoufox(t: BrowserTab, stack: contextlib.ExitStack, proxy_url: str | None, country: str | None) -> None:
    try:
        from camoufox.sync_api import Camoufox  # type: ignore[import-not-found]
    except ImportError:
        raise RuntimeError("camoufox not installed: uv pip install --python .venv/bin/python 'camoufox[geoip]' "
                           "&& .venv/bin/python -m camoufox fetch") from None
    import urllib.parse
    # os=macos: a random Windows identity turns on canvas noise. main_world_eval: an "mw:"-prefixed
    # evaluate runs in the page's own JS world (coches.net's XHR timeout patch must reach the site's code).
    kw: dict[str, Any] = {"headless": True, "os": "macos", "main_world_eval": True}
    if proxy_url:
        u = urllib.parse.urlsplit(proxy_url)
        kw["proxy"] = {"server": f"{u.scheme}://{u.hostname}:{u.port}",
                       "username": urllib.parse.unquote(u.username or ""),
                       "password": urllib.parse.unquote(u.password or "")}
    if country:
        from carhunt.access import geo
        kw["locale"] = geo.locale_for(country)[1]  # set explicitly: geoip alone produces "es-PT"
    browser = stack.enter_context(Camoufox(**kw))
    t.page = browser.new_page()


@contextlib.contextmanager
def tab(route: str, *, country: str | None = None, site: str | None = None,
        profile: Path | str | None = None, fresh: bool = False, pace_wait_s: float = PACE_WAIT_S) -> Iterator[Tab]:
    """One page handle on `route`; everything opened here is closed on exit, on failure too.

    country → residential exit in that country, verified (fail closed) before the first site request:
    http/lane/camoufox use the proxy directly; plain-chrome uses the country's geo lease; identity refuses.
    fresh → throwaway browser profile (Akamai counts bursts per profile, e.g. mobile.de). Lane, camoufox and http
    are fresh anyway; identity and geo profiles are persistent by design, so fresh refuses there.
    """
    if route not in ROUTES:
        raise ValueError(f"route must be one of {ROUTES}, got {route!r}")
    if country and route == "identity":
        # identity profiles live on the home IP; a foreign-IP login there would mix IPs on one account
        raise ValueError("identity + country is not allowed: use route plain-chrome with country (geo lease)")
    if fresh and (route == "identity" or (route == "plain-chrome" and (country or profile))):
        raise ValueError("fresh=True needs a route whose profile is throwaway (plain-chrome without country/profile, "
                         "lane, camoufox, http)")
    country = country.lower() if country else None
    kw = {"site": site, "pace_wait_s": pace_wait_s}
    with contextlib.ExitStack() as stack:
        t: Tab
        if route == "http":
            purl = None
            if country:
                purl = proxy.get(country)
                proxy.verify_exit(purl, country)
            t = HttpTab(_http_transport(purl), country=country, **kw)
        elif route == "lane":
            server = None
            if country:
                fwd = stack.enter_context(proxy.Forwarder(proxy.get(country)))
                proxy.verify_exit(fwd.url, country)  # through the forwarder = what Chrome will use
                server = fwd.url
            t = BrowserTab("lane", country=country, **kw)
            stack.callback(t.close)  # Chrome stops before the forwarder
            _open_lane(t, server)
        elif route == "plain-chrome":
            t = BrowserTab("plain-chrome", country=country, **kw)
            stack.callback(t.close)
            if country:
                from carhunt.access import geo
                g = stack.enter_context(geo.lease(country, _holder()))
                t._opener = _plain_opener(t, stack, g.profile, g.open_tab)
            else:
                t._opener = _plain_opener(t, stack, profile, fresh=fresh)
        elif route == "identity":
            from carhunt.access import identity
            holder = _holder()
            lease = identity.acquire(holder, any_=True)
            stack.callback(identity.release, holder, lease.name)
            from carhunt.access import plainchrome
            # clean browser close before the release: cookies flush and sync back to the pool (a kill loses ~30 s)
            stack.callback(plainchrome.close, lease.profile)
            t = BrowserTab("identity", **kw)
            stack.callback(t.close)
            t._opener = _plain_opener(t, stack, lease.profile)
        else:  # camoufox
            t = BrowserTab("camoufox", country=country, **kw)
            stack.callback(t.close)
            purl = None
            if country:
                purl = proxy.get(country)
                proxy.verify_exit(purl, country)
            _open_camoufox(t, stack, purl, country)
        if route == "http":
            stack.callback(t.close)
        yield t

