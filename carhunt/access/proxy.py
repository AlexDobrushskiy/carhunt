"""Residential proxy: provider adapters, fail-closed exit check, and a local auth-injecting forwarder for Chrome.

    from carhunt.access import proxy
    url = proxy.get("es")                    # one sticky session (= one exit IP) per run and country
    ip = proxy.verify_exit(url, "es")        # raises ProxyUnavailable unless the exit really is in ES
    with proxy.Forwarder(url) as fwd: ...    # Chrome: --proxy-server=fwd.url (Chrome can't take proxy creds by flag)

Lessons:
- Fail closed: verify the exit before the first site request, abort on any doubt. A dead OpenVPN left a SOCKS
  server serving the home IP (11-02).
- One sticky session per run: a new IP on every load got a DataDome slider on the 3rd load (11-06).
- Free/public VPNs are useless on serious walls: VPN Gate IPs got the Imperva bot page on the first load,
  a datacenter VPN IP later got a messaging soft block (11-02, 11-05). Use residential.
- Residential is paid per GB: turn images/media off where the site allows (whole coches/milanuncios campaign: 66 MB).
Credentials are read from core secrets by name and never logged; `redact()` anything you print.
"""
from __future__ import annotations

import argparse
import base64
import json
import secrets as _rand
import select
import socket
import socketserver
import string
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from carhunt.access import _core
from carhunt.access.errors import ProxyUnavailable

DEFAULT_ECHO = "https://ipinfo.io/json"


def _secret_name(ref: Any) -> str | None:
    """`secret:NAME` (string or core SecretRef) → NAME."""
    if ref is None:
        return None
    name = getattr(ref, "name", None) or str(ref)
    return name.removeprefix("secret:") or None


def redact(url: str) -> str:
    """Proxy URL with user and password masked (safe for logs)."""
    u = urllib.parse.urlsplit(url)
    if not (u.username or u.password):
        return url
    host = u.hostname or ""
    return urllib.parse.urlunsplit((u.scheme, f"***:***@{host}" + (f":{u.port}" if u.port else ""), u.path, "", ""))


class Provider:
    name = "base"
    echo_url = DEFAULT_ECHO

    def url(self, country: str, session_id: str, sticky_minutes: int) -> str:
        raise NotImplementedError


class NoneProvider(Provider):
    name = "none"

    def url(self, country: str, session_id: str, sticky_minutes: int) -> str:
        raise ProxyUnavailable("no proxy provider configured: set net.proxy.provider (decodo) in config.yaml and "
                               "`carhunt secret set proxy_credentials` (USER:PASS)")


class DecodoProvider(Provider):
    """Decodo residential gateway: country + sticky session encoded in the username."""
    name = "decodo"
    echo_url = "https://ip.decodo.com/json"
    MAX_STICKY = 30  # a sticky session past ~30 min gets rotated by the gateway anyway; plan runs within it

    def __init__(self, credentials: str = "proxy_credentials", gateway: str = "gate.decodo.com:7000"):
        self.credentials, self.gateway = credentials, gateway

    def __repr__(self) -> str:
        return f"DecodoProvider(gateway={self.gateway!r})"

    def url(self, country: str, session_id: str, sticky_minutes: int) -> str:
        raw = _core.secret(self.credentials)
        if not raw or ":" not in raw:
            raise ProxyUnavailable(f"secret {self.credentials} missing or not USER:PASS "
                                   f"(carhunt secret set {self.credentials})")
        acct, pw = raw.split(":", 1)
        minutes = max(1, min(int(sticky_minutes), self.MAX_STICKY))
        user = f"user-{acct}-country-{country.lower()}-session-{session_id}-sessionduration-{minutes}"
        q = urllib.parse.quote
        return f"http://{q(user, safe='')}:{q(pw, safe='')}@{self.gateway}"


PROVIDERS: dict[str, type[Provider]] = {"none": NoneProvider, "decodo": DecodoProvider}


def provider() -> Provider:
    """The configured provider (config `net.proxy.provider`, default none)."""
    cfg = (_core.section("net").get("proxy") or {})
    kind = str(cfg.get("provider") or "none").lower()
    if kind not in PROVIDERS:
        raise ProxyUnavailable(f"unknown net.proxy.provider {kind!r} (one of {', '.join(PROVIDERS)})")
    if kind == "decodo":
        p = DecodoProvider(_secret_name(cfg.get("credentials")) or "proxy_credentials",
                           str(cfg.get("gateway") or "gate.decodo.com:7000"))
    else:
        p = PROVIDERS[kind]()
    if cfg.get("echo_url"):
        p.echo_url = str(cfg["echo_url"])
    return p


_RUN_SESSIONS: dict[str, str] = {}


def run_session(country: str) -> str:
    """This process's sticky session id for `country` (same id ⇒ same exit IP for the run)."""
    cc = country.lower()
    if cc not in _RUN_SESSIONS:
        _RUN_SESSIONS[cc] = "ch" + "".join(_rand.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    return _RUN_SESSIONS[cc]


def get(country: str, sticky_minutes: int = 30, *, session: str | None = None, prov: Provider | None = None) -> str:
    """Proxy URL (with credentials: never print it, use redact()) for an exit in `country`."""
    return (prov or provider()).url(country, session or run_session(country), sticky_minutes)


# ---------- exit verification ----------

Fetch = Callable[[str, "str | None"], dict]


def _fetch_json(url: str, proxy_url: str | None) -> dict:
    handlers = [urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url} if proxy_url else {})]
    opener = urllib.request.build_opener(*handlers)
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "curl/8"}), timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_echo(d: dict) -> tuple[str | None, str | None]:
    """(ip, country code) from common IP-echo shapes: ipinfo, ip-api, ipapi, Decodo's nested one."""
    ip = d.get("ip") or d.get("query") or (d.get("proxy") or {}).get("ip")
    c = d.get("country_code") or d.get("countryCode") or d.get("country")
    if isinstance(c, dict):
        c = c.get("code")
    return ip, (str(c).upper() if c else None)


def verify_exit(proxy_url: str, country: str, *, fetch: Fetch | None = None, echo_url: str | None = None,
                home_check: bool = True) -> str:
    """Exit IP of `proxy_url` if it is in `country`; else raise ProxyUnavailable. Send no site request before this.

    home_check: also refuse when the exit equals the direct (home) IP — a dead tunnel can quietly go direct (11-02).
    """
    fetch = fetch or _fetch_json
    if echo_url is None:
        try:
            echo_url = provider().echo_url
        except ProxyUnavailable:
            echo_url = DEFAULT_ECHO
    url = echo_url
    try:
        ip, cc = parse_echo(fetch(url, proxy_url))
    except ProxyUnavailable:
        raise
    except Exception as e:  # network, auth, JSON: all mean "not verified"
        raise ProxyUnavailable(f"exit check through {redact(proxy_url)} failed: {type(e).__name__}") from None
    if not ip or cc != country.upper():
        raise ProxyUnavailable(f"exit country {cc or '?'} != {country.upper()} via {redact(proxy_url)}; aborting")
    if home_check:
        try:
            home_ip, _ = parse_echo(fetch(url, None))
        except Exception:
            home_ip = None  # can't tell; the country check above already passed
        if home_ip and home_ip == ip:
            raise ProxyUnavailable("proxy exit equals the direct IP (tunnel down?); aborting")
    return ip


# ---------- authfwd: local no-auth forwarder (Chrome can't pass proxy creds by flag) ----------

class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: _Server = self.server  # type: ignore[assignment]
        client = self.request
        client.settimeout(60)
        try:
            head = b""
            while b"\r\n\r\n" not in head:
                chunk = client.recv(65536)
                if not chunk:
                    return
                head += chunk
                if len(head) > 1 << 20:
                    return
            head, rest = head.split(b"\r\n\r\n", 1)
            lines = [ln for ln in head.split(b"\r\n") if not ln.lower().startswith(b"proxy-authorization:")]
            if not lines[0].upper().startswith(b"CONNECT "):
                # one request per connection, so every request carries the auth header
                lines = [ln for ln in lines if not ln.lower().startswith((b"connection:", b"proxy-connection:"))]
                lines.append(b"Connection: close")
            lines.insert(1, b"Proxy-Authorization: Basic " + srv.auth)
            try:
                up = socket.create_connection(srv.upstream, timeout=30)
            except OSError:
                return  # fail closed: upstream down → drop the client, never go direct
            with up:
                up.sendall(b"\r\n".join(lines) + b"\r\n\r\n" + rest)
                _pipe(client, up)
        except OSError:
            return
        finally:
            try:
                client.close()
            except OSError:
                pass


def _pipe(a: socket.socket, b: socket.socket) -> None:
    socks = [a, b]
    while True:
        r, _, x = select.select(socks, [], socks, 120)
        if x or not r:
            return
        for s in r:
            data = s.recv(65536)
            if not data:
                return
            (b if s is a else a).sendall(data)


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    upstream: tuple[str, int]
    auth: bytes


class Forwarder:
    """127.0.0.1 proxy without auth that forwards everything to `upstream_url` adding Proxy-Authorization.

    Fails closed: when the upstream is unreachable the client connection is dropped; nothing is sent direct.
    """

    def __init__(self, upstream_url: str, port: int = 0):
        u = urllib.parse.urlsplit(upstream_url)
        if not u.hostname or not u.port:
            raise ProxyUnavailable(f"bad upstream proxy URL {redact(upstream_url)}")
        cred = f"{urllib.parse.unquote(u.username or '')}:{urllib.parse.unquote(u.password or '')}"
        self._upstream = (u.hostname, u.port)
        self._auth = base64.b64encode(cred.encode())
        self._port = port
        self._srv: _Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if not self._srv:
            raise RuntimeError("forwarder not started")
        return self._srv.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> Forwarder:
        srv = _Server(("127.0.0.1", self._port), _Handler)
        srv.upstream, srv.auth = self._upstream, self._auth
        self._srv = srv
        self._thread = threading.Thread(target=srv.serve_forever, name="carhunt-authfwd", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

    def __enter__(self) -> Forwarder:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def chrome_args(proxy_server: str) -> list[str]:
    """Chrome flags that keep every byte on the proxy: DNS through it, WebRTC only via the proxy (no UDP leak)."""
    return [f"--proxy-server={proxy_server}",
            "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp"]


# ---------- CLI: carhunt proxy test COUNTRY ----------

def _cmd_test(a) -> int:
    try:
        prov = provider()
        if isinstance(prov, NoneProvider):
            print("no proxy provider configured. To set one up:\n"
                  "  config.yaml:  net: {proxy: {provider: decodo, credentials: secret:proxy_credentials}}\n"
                  "  secret:       carhunt secret set proxy_credentials   (value USER:PASS, typed at the prompt)\n"
                  "Residential only: free/public VPN exits are flagged by DataDome/Imperva.")
            return 2
        url = get(a.country, a.minutes, prov=prov)
        ip = verify_exit(url, a.country, echo_url=prov.echo_url)
    except ProxyUnavailable as e:
        print(f"FAIL: {e}")
        return 1
    print(json.dumps({"ok": True, "provider": prov.name, "country": a.country.upper(), "exit_ip": ip}))
    return 0


def register_cli(sub) -> None:
    p = sub.add_parser("proxy", help="residential proxy (verify-only test)")
    p.set_defaults(_parser=p)
    s = p.add_subparsers(dest="proxy_cmd", metavar="<cmd>")
    x = s.add_parser("test", help="check the exit IP for COUNTRY (one echo request, no site traffic)")
    x.add_argument("country")
    x.add_argument("--minutes", type=int, default=30)
    x.set_defaults(func=_cmd_test)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="proxy")
    register_cli(ap.add_subparsers(dest="group"))
    a = ap.parse_args(["proxy", *(argv or [])])
    return int(a.func(a)) if hasattr(a, "func") else 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
