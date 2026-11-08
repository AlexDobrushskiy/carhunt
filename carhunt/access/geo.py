"""One leased browser per country exit: plain-chrome on its own profile `profiles/geo-<cc>`, all traffic through a
verified residential exit in that country.

    from carhunt.access import geo
    with geo.lease("fr", holder="outreach") as g:      # waits for the lease, verifies the exit, launches
        with g.open_tab("https://www.example.invalid/") as (browser, page):
            ...

Rules:
- Exclusive lease (flock + lease file): one holder at a time.
- The geo profile never joins the cookie-synced identity pool or the trust jar: an account created on a foreign IP
  must live on that IP forever, and the home IP must never log into it.
- Exit verified before the first site load (fail closed); one sticky session per lease (rotating per load triggers
  DataDome sliders). Chrome gets TZ + locale of the country and WebRTC forced through the proxy.
- Images off by default (residential = paid per GB); pass media=True where clicks need media (milanuncios modal).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from carhunt.access import _core, proxy
from carhunt.access import settings as _settings
from carhunt.access.errors import LeaseBusy, ProxyUnavailable

# country → (tz, locale). Override/extend via config net.geo.<cc>: {tz, locale}.
COUNTRY: dict[str, tuple[str, str]] = {
    "at": ("Europe/Vienna", "de-AT"), "be": ("Europe/Brussels", "fr-BE"), "ch": ("Europe/Zurich", "de-CH"),
    "cz": ("Europe/Prague", "cs-CZ"), "de": ("Europe/Berlin", "de-DE"), "dk": ("Europe/Copenhagen", "da-DK"),
    "es": ("Europe/Madrid", "es-ES"), "fr": ("Europe/Paris", "fr-FR"), "gb": ("Europe/London", "en-GB"),
    "ie": ("Europe/Dublin", "en-IE"), "it": ("Europe/Rome", "it-IT"), "lu": ("Europe/Luxembourg", "fr-LU"),
    "nl": ("Europe/Amsterdam", "nl-NL"), "pl": ("Europe/Warsaw", "pl-PL"), "pt": ("Europe/Lisbon", "pt-PT"),
    "se": ("Europe/Stockholm", "sv-SE"), "us": ("America/New_York", "en-US"),
}
MAX_LEASE_S = 7200   # older lease = stale, taken over
WAIT_S = 600

# launcher(profile, extra_args, env) -> (debug_port, pid); closer(profile)
Launcher = Callable[[Path, list[str], dict[str, str]], tuple[int, int]]
Closer = Callable[[Path], Any]


def locale_for(country: str) -> tuple[str, str]:
    cc = country.lower()
    over = (_core.section("net").get("geo") or {}).get(cc) or {}
    tz, loc = COUNTRY.get(cc, ("UTC", "en-US"))
    return str(over.get("tz") or tz), str(over.get("locale") or loc)


def profile_dir(country: str) -> Path:
    return _settings.load().profile_dir(f"geo-{country.lower()}")


def chrome_flags(proxy_server: str, country: str, *, media: bool = False) -> tuple[list[str], dict[str, str]]:
    tz, loc = locale_for(country)
    lang = loc.split("-")[0]
    args = proxy.chrome_args(proxy_server) + [f"--lang={loc}", f"--accept-lang={loc},{lang},en"]
    if not media:
        args.append("--blink-settings=imagesEnabled=false")
    return args, {"TZ": tz}


# ---------- lease ----------

def _lease_file(cc: str) -> Path:
    return _settings.load().leases_dir / f"geo-{cc}.json"


@contextlib.contextmanager
def _locked(cc: str) -> Iterator[None]:
    with open(_settings.load().leases_dir / f"geo-{cc}.lock", "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def held(country: str) -> dict | None:
    """Current live lease {holder, pid, since} or None."""
    f = _lease_file(country.lower())
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    if time.time() - d.get("since", 0) > MAX_LEASE_S or not _pid_alive(int(d.get("pid", 0))):
        return None  # stale: holder gone or lease too old
    return d


def take(country: str, holder: str) -> bool:
    cc = country.lower()
    with _locked(cc):
        cur = held(cc)
        if cur and cur["holder"] != holder:
            return False
        tmp = _lease_file(cc).with_suffix(".tmp")
        tmp.write_text(json.dumps({"holder": holder, "pid": os.getpid(), "since": time.time(),
                                   "profile": str(profile_dir(cc))}))  # reaper: leased = keep
        tmp.replace(_lease_file(cc))
        return True


def give_back(country: str, holder: str, *, force: bool = False) -> bool:
    cc = country.lower()
    with _locked(cc):
        cur = held(cc)
        if cur and cur["holder"] != holder and not force:
            return False  # not ours: never tear down someone else's step
        _lease_file(cc).unlink(missing_ok=True)
        return True


# ---------- launch ----------

def _default_launcher(profile: Path, extra_args: list[str], env: dict[str, str]) -> tuple[int, int]:
    from carhunt.access import plainchrome
    # jar=False: a geo profile never imports/exports trust cookies (its cookies belong to one exit IP)
    return plainchrome.ensure_running(profile, None, extra_args=extra_args, env=env, jar=False, kind="geo")


def _default_closer(profile: Path) -> Any:
    from carhunt.access import plainchrome
    return plainchrome.close(profile, force=True)


def _debug_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2):
            return True
    except OSError:
        return False


@dataclass
class GeoLease:
    country: str
    holder: str
    profile: Path
    port: int
    pid: int
    exit_ip: str
    proxy_server: str
    _alive: Callable[[int], bool] = field(default=_debug_alive, repr=False)

    @contextlib.contextmanager
    def open_tab(self, url: str, **kw) -> Iterator[tuple[Any, Any]]:
        """plain-chrome tab in this lease's browser. Refuses if that browser died: a relaunch outside the lease
        would go out on the home IP."""
        if not self._alive(self.port):
            raise ProxyUnavailable(f"geo-{self.country} browser is gone; take a new lease")
        from carhunt.access import plainchrome
        with plainchrome.open_tab(url, profile=self.profile, **kw) as bp:
            yield bp


@contextlib.contextmanager
def lease(country: str, holder: str | None = None, *, wait_s: float = WAIT_S, sticky_minutes: int = 30,
          media: bool = False, prov: proxy.Provider | None = None, launcher: Launcher | None = None,
          closer: Closer | None = None, verify: Callable[[str, str], str] | None = None,
          alive: Callable[[int], bool] | None = None, sleep=time.sleep) -> Iterator[GeoLease]:
    """Hold the country's browser for one step; everything is torn down and released on exit, on failure too."""
    cc = country.lower()
    holder = holder or os.environ.get("AGTERM_SESSION_ID") or f"pid{os.getpid()}"
    deadline = time.monotonic() + wait_s
    while not take(cc, holder):
        if time.monotonic() >= deadline:
            cur = held(cc) or {}
            raise LeaseBusy(f"geo-{cc} held by {cur.get('holder', '?')}")
        sleep(5)
    launcher, closer = launcher or _default_launcher, closer or _default_closer
    verify = verify or (lambda url, c: proxy.verify_exit(url, c))
    fwd: proxy.Forwarder | None = None
    launched = False
    profile = profile_dir(cc)
    try:
        fwd = proxy.Forwarder(proxy.get(cc, sticky_minutes, prov=prov)).start()
        ip = verify(fwd.url, cc)  # through the forwarder = exactly what Chrome will use
        args, env = chrome_flags(fwd.url, cc, media=media)
        launched = True
        port, pid = launcher(profile, args, env)
        yield GeoLease(cc, holder, profile, port, pid, ip, fwd.url, alive or _debug_alive)
    finally:
        try:
            if launched:
                with contextlib.suppress(Exception):
                    closer(profile)
        finally:
            if fwd:
                fwd.stop()
            give_back(cc, holder)


def _cmd_status(a) -> int:
    for f in sorted(_settings.load().leases_dir.glob("geo-*.json")):
        cc = f.stem.removeprefix("geo-")
        cur = held(cc)
        print(json.dumps({"country": cc, "holder": cur["holder"] if cur else None}))
    return 0


def _cmd_release(a) -> int:
    ok = give_back(a.country, a.holder or "", force=a.force)
    print("released" if ok else "held by someone else (use --force only if that holder is dead)")
    return 0 if ok else 3


def register_cli(sub) -> None:
    p = sub.add_parser("geo", help="country-exit browser leases (one profile per exit country)")
    p.set_defaults(_parser=p)
    s = p.add_subparsers(dest="geo_cmd", metavar="<cmd>")
    s.add_parser("status", help="leases and holders (JSON lines)").set_defaults(func=_cmd_status)
    x = s.add_parser("release", help="drop a lease (owner override for a dead holder)")
    x.add_argument("country")
    x.add_argument("--holder")
    x.add_argument("--force", action="store_true")
    x.set_defaults(func=_cmd_release)
