"""Transport for site plugins: pace gate → HTTP (urllib) or one browser tab (carhunt.access.session) → block/gone check.

Plugins never open sockets or tabs themselves: they call `net.get` / `net.json` / `net.browser_get`, so tests swap
in `carhunt.sites.testing.FakeNet` and the pacing rules live in one place.

Rules (each from the EV run):
- Every load goes through the pace gate (`access.pace.acquire(site, kind)`, shared ledger across agents) — parallel
  agents on one IP got sites banned (coches.net 11-03, leboncoin 10-30).
- Stop on a block signal: 401/403/429/5xx or a bot page → `Blocked`; 404/410 → `Gone` (skip that ad, keep going) —
  two runs stopped leboncoin on a 410 and left 200 ads undone (11-04/05).
- A country route (site.yaml `country_ip`) goes through `access.proxy`, fail-closed: no proxy → no request.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any

from carhunt.access.errors import Blocked, PaceExceeded, ProxyUnavailable

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/156.0.0.0 Safari/537.36")
HTML = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON = "application/json, text/plain, */*"
BOT = re.compile(r"eres un bot|pardon our interruption|captcha-delivery|geo\.captcha|zugriff verweigert|access denied|"
                 r"request blocked|just a moment|verify you are human|are you a robot|ich bin kein roboter|"
                 r"access (is )?temporarily restricted", re.I)
BLOCK_STATUS = {401, 403, 429}
GONE_STATUS = {404, 410}
MAX_PACE_WAIT_S = 180   # wait for a pace slot up to this long, else raise PaceExceeded (caller stops the site)


@dataclass
class Response:
    status: int
    url: str
    text: str = ""
    location: str | None = None         # redirect target when redirects were not followed
    final_url: str | None = None        # after redirects (followed)
    headers: dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.text)


# wall signature by page text (first match wins); names feed the browsers skill's escalation ladder
SIGNATURES = [
    ("datadome-hard-block", re.compile(r"access (is )?temporarily restricted", re.I)),
    ("datadome", re.compile(r"captcha-delivery|geo\.captcha", re.I)),
    ("cloudflare", re.compile(r"just a moment|verify you are human", re.I)),
    ("imperva", re.compile(r"pardon our interruption|eres un bot|request blocked", re.I)),
    ("akamai", re.compile(r"zugriff verweigert|access denied", re.I)),
]


def bot_page(text: str, ad_id: str | None = None) -> bool:
    """A challenge/bot page; a page that carries the ad id is content, not a wall (some ads quote 'captcha')."""
    return bool(BOT.search(text[:20000])) and not (ad_id and ad_id in text)


def bot_signature(text: str) -> str:
    head = text[:20000]
    return next((name for name, rx in SIGNATURES if rx.search(head)), "bot-page")


def raise_for(site: str, r: Response, *, ad_id: str | None = None, ok: tuple[int, ...] = (200,)) -> Response:
    """Block/gone classification of one answer. Returns r when it is content."""
    if r.status in BLOCK_STATUS or r.status >= 500:
        raise Blocked(f"http-{r.status}", site=site, url=r.url)
    if r.status in GONE_STATUS:
        from carhunt.sites.base import Gone
        raise Gone(r.url, f"http-{r.status}")
    if r.status == 0:
        raise Blocked("network", site=site, url=r.url, detail=r.text[:120])
    if r.text and bot_page(r.text, ad_id):
        raise Blocked(bot_signature(r.text), site=site, url=r.url)
    if r.status not in ok and not (300 <= r.status < 400):
        raise Blocked(f"http-{r.status}", site=site, url=r.url)
    return r


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _decode(body: bytes, enc: str | None) -> str:
    try:
        if enc == "gzip":
            body = gzip.decompress(body)
        elif enc == "deflate":
            body = zlib.decompress(body)
    except Exception:
        pass
    return body.decode("utf-8", "replace")


def http(url: str, *, headers: dict[str, str] | None = None, follow: bool = True, proxy: str | None = None,
         data: bytes | None = None, method: str | None = None, timeout: float = 30) -> Response:
    """One plain HTTP request. Never raises on HTTP status; status 0 = network error (text = error)."""
    handlers: list = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if not follow:
        handlers.append(_NoRedirect())
    opener = urllib.request.build_opener(*handlers)
    h = {"User-Agent": UA, "Accept": HTML, "Accept-Encoding": "gzip", "Accept-Language": "en-US,en;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    try:
        r = opener.open(req, timeout=timeout)
        status, hdr, body, final = r.status, r.headers, r.read(), r.geturl()
    except urllib.error.HTTPError as e:
        status, hdr, final = e.code, e.headers, url
        body = e.read() if not 300 <= e.code < 400 else b""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return Response(0, url, text=repr(e))
    loc = hdr.get("Location")
    if loc and loc.startswith("/"):
        loc = "/".join(url.split("/")[:3]) + loc
    return Response(status, url, _decode(body, hdr.get("Content-Encoding")), location=loc,
                    final_url=final if final != url else None,
                    # repeated Set-Cookie headers joined: a dict keeps only the last (DataDome rotates its cookie)
                    headers={k.lower(): v for k, v in hdr.items()}
                    | {"set-cookie": "\n".join(hdr.get_all("Set-Cookie") or [])})


TAB_FETCH_JS = """async ([u, opts]) => { try {
  const r = await fetch(u, Object.assign({credentials: 'include', redirect: 'follow'}, opts || {}));
  return {status: r.status, url: r.url, text: await r.text()};
} catch (e) { return {status: 0, url: u, text: String(e)}; } }"""


class Net:
    """Real transport for one site. `close()` releases the browser tab, if one was opened."""

    def __init__(self, site: str, meta: dict):
        self.site, self.meta = site, meta
        pace = meta.get("pace") or {}
        self.min_gap_s = float(pace.get("min_gap_s") or 6)
        self.max_loads = pace.get("max_loads_per_run")
        self.per_hour = pace.get("max_loads_per_hour")
        self._hour: list[float] = []
        self.loads = 0
        self._last = 0.0
        self._stack: contextlib.ExitStack | None = None
        self._page: Any = None
        self.fresh_every = pace.get("fresh_profile_every")   # Akamai counts bursts per browser profile (mobile.de)
        self._tab_loads = 0

    # --- pacing ------------------------------------------------------------
    def gate(self, kind: str = "load", *, country: str | None = None) -> None:
        """Take a slot before the request (a 403 still costs the slot: the site counted it).
        A country route has its own exit IP, so it is paced on its own ledger key (`<site>@<CC>`)."""
        home = country is None or country == self.meta.get("country_ip")   # the site's normal read route
        key = self.site if home else f"{self.site}@{country}"
        if kind == "load" and home and self.max_loads and self.loads >= int(self.max_loads):
            raise PaceExceeded(self.site, kind, reason=f"max_loads_per_run={self.max_loads}")
        try:
            from carhunt.access import pace as shared
        except ImportError:
            shared = None
        if shared is not None:
            deadline = time.monotonic() + MAX_PACE_WAIT_S
            while True:
                try:
                    shared.acquire(key, kind)
                    break
                except PaceExceeded as e:
                    if e.retry_at is None:
                        raise
                    from carhunt.access import _core
                    wait = (e.retry_at - _core.now()).total_seconds()
                    if time.monotonic() + wait > deadline:
                        raise
                    time.sleep(max(wait, 0.5))
        else:   # browsers' pace ledger not installed: in-process gap + hourly cap only
            if kind == "load" and home and self.per_hour:
                t = time.monotonic()
                self._hour = [x for x in self._hour if t - x < 3600]
                if len(self._hour) >= int(self.per_hour):
                    raise PaceExceeded(self.site, kind, reason=f"max_loads_per_hour={self.per_hour} (in-process)")
                self._hour.append(t)
            wait = self._last + self.min_gap_s - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        self._last = time.monotonic()
        if kind == "load" and home:
            self.loads += 1

    def _proxy(self, country: str | None) -> str | None:
        if not country:
            return None
        try:
            from carhunt.access import proxy
        except ImportError as e:
            raise ProxyUnavailable(f"{self.site}: {country} route needs carhunt.access.proxy") from e
        return proxy.get(country, sticky_minutes=int((self.meta.get("proxy") or {}).get("sticky_minutes", 10)))

    # --- HTTP route --------------------------------------------------------
    def get(self, url: str, *, kind: str = "load", accept: str = HTML, follow: bool = True, ad_id: str | None = None,
            headers: dict[str, str] | None = None, country: str | None = None, data: bytes | None = None,
            method: str | None = None, check: bool = True) -> Response:
        if country is None:   # reads of a country_ip site always leave through that country
            country = self.meta.get("country_ip")
        proxy = self._proxy(country)   # fail closed before taking a pace slot
        self.gate(kind, country=country)
        h = {"Accept": accept, "Accept-Language": self.meta.get("accept_language", "en-US,en;q=0.8")}
        h.update(headers or {})
        r = http(url, headers=h, follow=follow, proxy=proxy, data=data, method=method)
        return raise_for(self.site, r, ad_id=ad_id) if check else r

    def json(self, url: str, **kw) -> Any:
        return self.get(url, accept=JSON, **kw).json()

    # --- browser route -----------------------------------------------------
    def _tab(self) -> Any:
        if self._page is None:
            from carhunt.access import session  # browsers module: agent Chrome lanes / plain-chrome
            self._stack = contextlib.ExitStack()
            route = self.meta.get("route", "plain-chrome")
            kw = {"fresh": True} if self.fresh_every else {}   # throwaway profile per batch
            self._page = self._stack.enter_context(
                session.tab(route, site=self.site, country=self.meta.get("country_ip"), **kw))
            self._tab_loads = 0
            home = self.meta.get("tab_home")
            if home:
                self.gate("load")
                self._page.goto(home, wait_until="domcontentloaded")
        return self._page

    def browser_get(self, url: str, *, mode: str = "fetch", kind: str = "load", ad_id: str | None = None,
                    opts: dict | None = None, check: bool = True) -> Response:
        """One read in the site's browser tab. mode `fetch` = same-origin fetch from the tab (the site's own JSON API,
        cookies included); `goto` = a real navigation (cross-origin pages, e.g. mobile.de ads)."""
        if self.fresh_every and self._tab_loads >= int(self.fresh_every):
            self.close()   # next read opens a fresh profile
        page = self._tab()
        self.gate(kind)
        self._tab_loads += 1
        if mode == "goto":
            try:
                resp = page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                r = Response(resp.status if resp else 0, url, page.content(),
                             final_url=page.url if page.url != url else None)
            except Exception as e:  # navigation error = unknown, never "gone"
                r = Response(0, url, text=repr(e))
        else:
            d = page.evaluate(TAB_FETCH_JS, [url, opts or {}])
            r = Response(int(d.get("status") or 0), url, d.get("text") or "",
                         final_url=d.get("url") if d.get("url") not in (None, url) else None)
        return raise_for(self.site, r, ad_id=ad_id) if check else r

    def close(self) -> None:
        if self._stack is not None:
            self._stack.close()
        self._stack, self._page = None, None
