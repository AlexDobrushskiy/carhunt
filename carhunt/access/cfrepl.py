"""cfrepl — a long-lived headed Camoufox (anti-detect Firefox) that runs Python snippets sent to it.

Explore or drive a site step by step without re-loading pages (every extra load raises the bot score).
Camoufox is optional: `uv pip install 'camoufox[geoip]' && python -m camoufox fetch`.

  python -m carhunt.access.cfrepl serve NAME --profile DIR [--proxy-country CC] [--locale ll-CC] [--no-media]
  python -m carhunt.access.cfrepl run NAME 'code using page / ctx / mw / net'   (prints its stdout; waits ≤300 s)
  python -m carhunt.access.cfrepl stop NAME
  python -m carhunt.access.cfrepl status

In snippets: `mw(js)` evaluates in the page's main world (reach React state); `net` lists finished/failed
requests (method, url, status) — read an API's real status there, not from a page hook (a 403 can surface
as net::ERR_FAILED in the page).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import time
import traceback
from pathlib import Path
from urllib.parse import unquote, urlsplit

from carhunt.access import settings as _settings

INSTALL_HINT = "camoufox not installed: uv pip install 'camoufox[geoip]' && python -m camoufox fetch"
# A fresh Firefox profile downloads Widevine + OpenH264 (~17 MB of paid proxy traffic).
NO_PLUGIN_DOWNLOADS = {"media.gmp-manager.updateEnabled": False, "media.gmp-widevinecdm.enabled": False,
                       "media.gmp-widevinecdm.visible": False, "media.gmp-gmpopenh264.enabled": False,
                       "media.eme.enabled": False, "app.update.enabled": False}
# Explicit locale per exit country: geoip alone produces odd values (es-PT).
LOCALES = {"es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT", "pt": "pt-PT", "nl": "nl-NL",
           "be": "nl-BE", "at": "de-AT", "pl": "pl-PL", "gb": "en-GB", "uk": "en-GB", "us": "en-US"}


def _dir(name: str) -> Path:
    return _settings.load().dir("cfrepl", name)


def _camoufox():
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise RuntimeError(INSTALL_HINT) from e
    return Camoufox


def playwright_proxy(url: str) -> dict:
    u = urlsplit(url)
    d = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        d["username"] = unquote(u.username)
        d["password"] = unquote(u.password or "")
    return d


def locale_for(country: str | None, locale: str | None) -> str:
    if locale:
        return locale
    return LOCALES.get((country or "").lower(), "en-US")


def serve(name: str, profile: Path, *, country: str | None = None, locale: str | None = None,
          no_media: bool = False) -> None:
    Camoufox = _camoufox()
    q = _dir(name)
    for f in q.glob("*"):
        f.unlink()
    proxy = None
    if country:
        from carhunt.access import proxy as _proxy
        url = _proxy.get(country, sticky_minutes=30)   # one sticky exit per run (rotating IPs trigger sliders)
        _proxy.verify_exit(url, country)               # fail closed before the first site request
        proxy = playwright_proxy(url)
    # os="macos": a random Windows identity on a Mac turns on canvas noise
    with Camoufox(headless=False, os="macos", locale=locale_for(country, locale), humanize=True,
                  geoip=bool(proxy), persistent_context=True, user_data_dir=str(profile), main_world_eval=True,
                  window=(1366, 900), proxy=proxy, firefox_user_prefs=NO_PLUGIN_DOWNLOADS) as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        net: list[tuple] = []
        page.on("response", lambda r: net.append((r.request.method, r.url[:200], r.status)))
        page.on("requestfailed", lambda r: net.append((r.method, r.url[:200], "FAILED " + str(r.failure)[:60])))
        if no_media:  # paid proxy bytes; not where a click needs media (milanuncios modal)
            page.route("**/*", lambda rt: rt.abort() if rt.request.resource_type in ("image", "media", "font")
                       else rt.continue_())
        g = {"page": page, "ctx": ctx, "net": net, "time": time, "json": json,
             "mw": lambda js: page.evaluate("mw:" + js)}
        (q / "ready").write_text(str(os.getpid()))
        try:
            while True:
                cmds = sorted(q.glob("cmd-*.py"))
                if not cmds:
                    time.sleep(0.3)
                    continue
                c = cmds[0]
                code = c.read_text()
                c.unlink()
                if code.strip() == "STOP":
                    break
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    try:
                        exec(code, g)
                    except Exception:
                        traceback.print_exc(file=buf)
                (q / c.name.replace("cmd-", "out-").replace(".py", ".txt")).write_text(buf.getvalue())
        finally:
            (q / "ready").unlink(missing_ok=True)


def _ready_pid(name: str) -> int | None:
    try:
        pid = int((_dir(name) / "ready").read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def run(name: str, code: str, timeout: float = 300) -> str:
    q = _dir(name)
    if _ready_pid(name) is None:
        raise RuntimeError(f"cfrepl {name} not running")
    n = f"{time.time():.6f}"
    (q / f"cmd-{n}.py").write_text(code)
    out = q / f"out-{n}.txt"
    t0 = time.time()
    while not out.exists():
        if time.time() - t0 > timeout:
            raise RuntimeError("timeout")
        if _ready_pid(name) is None:
            raise RuntimeError(f"cfrepl {name} exited")
        time.sleep(0.3)
    time.sleep(0.1)
    text = out.read_text()
    out.unlink()
    return text


def stop(name: str, timeout: float = 30) -> bool:
    pid = _ready_pid(name)
    if pid is None:
        return True
    (_dir(name) / f"cmd-{time.time():.6f}.py").write_text("STOP")
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _ready_pid(name) is None:
            return True
        time.sleep(0.3)
    return False


def status() -> list[dict]:
    root = _settings.load().dir("cfrepl")
    return [{"name": d.name, "pid": _ready_pid(d.name)} for d in sorted(root.iterdir()) if d.is_dir()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cfrepl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("serve")
    p.add_argument("name")
    p.add_argument("--profile", required=True, type=Path)
    p.add_argument("--proxy-country", help="residential exit country (carhunt.access.proxy), e.g. es")
    p.add_argument("--locale", help="default: from --proxy-country, else en-US")
    p.add_argument("--no-media", action="store_true", help="abort images/media/fonts (saves paid proxy bytes)")
    p = sub.add_parser("run")
    p.add_argument("name")
    p.add_argument("code")
    p.add_argument("--timeout", type=float, default=300)
    sub.add_parser("stop").add_argument("name")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "serve":
            serve(a.name, a.profile.expanduser(), country=a.proxy_country, locale=a.locale, no_media=a.no_media)
        elif a.cmd == "run":
            print(run(a.name, a.code, a.timeout), end="")
        elif a.cmd == "stop":
            return 0 if stop(a.name) else 1
        else:
            for r in status():
                print(json.dumps(r))
    except RuntimeError as e:
        print(f"cfrepl: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
