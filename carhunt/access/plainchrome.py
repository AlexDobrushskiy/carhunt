"""plain-chrome — Agent Chrome launched like a person launches it; automation attaches only after the first load.

Akamai (mobile.de) and DataDome (lacentrale.fr) block every Playwright-*launched* Chrome, headed or
headless, fresh or logged in, but pass the same Chrome started normally: they catch Playwright's launch
switches and its CDP session being live during the first load. Chrome starts here with only a debug
port; we attach after the first load committed and passed the check, then keep driving it over CDP.

Solves persist and are shared:
  - The default profile is persistent (`profiles/plain`), not a throwaway.
  - A second caller on a running profile gets a new TAB, not a second browser (two browsers = two captchas).
    The browser closes cleanly when its last holder releases.
  - Trust cookies (bot-check only, never logins) go to the jar when a browser closes; every launch is seeded
    from the jar (see carhunt.access.jar).

CLI (`plain-chrome …`):
  fetch [opts] URL [URL …]   open on the first URL, wait, attach, visit the rest in the same tab; one JSON line
                             per URL {n, url, final, title, blocked, len, head} + <out>/<n>.txt/.html/.jpg
  open [opts] URL            leave it running; prints {cdp, port, target, profile, reused}. Drive the page whose
                             CDP targetId == target (other tabs may be other agents'); release with `close`.
  close PORT [TARGET]        close your tab; the browser quits cleanly once no other holder has a tab
  close [--profile DIR] [--force]   close a profile's whole browser (refuses while others hold tabs)
  show|hide PORT [TARGET]    move the window on-screen and to the front (owner solves a captcha) / back off-screen
  cookies [--delete DOMAIN NAME]    list the trust-cookie jar (no values) / drop a poisoned cookie
  status                     running plain-chrome browsers
  opts: --profile DIR (identity copy after `pw-identity acquire`), --fresh (temp profile, deleted on close),
        --warm URL (load the home page first: lacentrale serves its captcha on a cold deep link),
        --headless (loses the advantage on Akamai/DataDome), --onscreen, --wait S (settle, default 10), --out DIR
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from carhunt.access import _core, chrome, jar, rawcdp
from carhunt.access import settings as _settings

BLOCK = re.compile(r"zugriff verweigert|access denied|captcha-delivery\.com|just a moment|cf-chl|verify you are human|"
                   r"are you a robot|prove your humanity|pardon our interruption|request unsuccessful|"
                   r"n[ãa]o a um robot|pas un robot|kein roboter|slide right|deslize para a direita|"
                   r"glissez vers la droite", re.I)
FIRST_SETTLE_S = 15.0  # first load: let the bot check finish before anything attaches


def log(msg: str) -> None:
    print(f"plain-chrome: {msg}", file=sys.stderr, flush=True)


# ---------- layout ----------

def _s() -> _settings.Settings:
    return _settings.load()


def shared_profile() -> Path:
    return _s().dir("profiles", "plain")


def _state_dir() -> Path:  # one sidecar per running browser: <port>.json {port, pid, profile, temp, holders}
    return _s().dir("plain-state")


def _fresh_dir() -> Path:
    return _s().dir("plain-fresh")


def _profile_for(profile: Path | str | None, fresh: bool) -> tuple[Path, bool]:
    if profile:
        return Path(profile).expanduser(), False
    if fresh:
        return Path(tempfile.mkdtemp(prefix="fresh-", dir=_fresh_dir())), True
    return shared_profile(), False


def _same(a: Path | str, b: Path | str) -> bool:
    return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()


def port_for(profile: Path | str) -> int | None:
    """Fixed debug port for known profiles (shared plain, identity master/copies); None → pick a free one."""
    s = _s()
    p = Path(profile).expanduser().resolve()
    if p == (s.profiles / "plain").resolve():
        return s.plain_debug_port
    if p.parent == s.profiles.resolve() and (p.name == "identity" or p.name.startswith("identity-")):
        try:
            return s.debug_port(p.name)
        except ValueError:
            return None
    return None


def free_port() -> int:
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket() as sk:
        sk.settimeout(0.5)
        return sk.connect_ex(("127.0.0.1", port)) == 0


# ---------- DevTools HTTP (no websocket, nothing attached) ----------

def _http(port: int, path: str, method: str = "GET") -> bytes:
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def _alive(port: int) -> bool:
    try:
        _http(port, "/json/version")
        return True
    except Exception:
        return False


def _pages(port: int) -> list[dict]:
    return [t for t in json.loads(_http(port, "/json/list")) if t.get("type") == "page"]


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:  # our own child that exited is a zombie until reaped; kill(0) would still succeed
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


# ---------- instance sidecars ----------

def _sidecar(port: int) -> Path:
    return _state_dir() / f"{port}.json"


def _load(port: int) -> dict | None:
    try:
        return json.loads(_sidecar(port).read_text())
    except (OSError, ValueError):
        return None


def _save(inst: dict) -> None:
    p = _sidecar(inst["port"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(inst))
    tmp.replace(p)


def instances() -> list[dict]:
    out = []
    for f in sorted(_state_dir().glob("*.json")):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def _running(profile: Path) -> dict | None:
    for inst in instances():
        if _same(inst["profile"], profile) and _pid_alive(inst["pid"]) and _alive(inst["port"]):
            return inst
    return None


def _after_exit(inst: dict) -> None:
    """Browser is gone: drop its records, save its trust cookies, delete a --fresh profile."""
    chrome.drop_pid_record(inst["pid"])
    prof = Path(inst["profile"])
    if prof.exists():
        n = jar.export_from(prof) if inst.get("jar", True) else 0
        if n:
            log(f"saved {n} trust cookie(s) to the jar")
        if inst.get("temp"):
            shutil.rmtree(prof, ignore_errors=True)
    _sidecar(inst["port"]).unlink(missing_ok=True)


def cleanup_dead() -> list[int]:
    """Tidy sidecars whose browser exited (crash, reaper, manual quit). Returns their ports."""
    done = []
    for inst in instances():
        if not _pid_alive(inst["pid"]):
            with _lock(inst["profile"]):
                if _load(inst["port"]) == inst:
                    _after_exit(inst)
                    done.append(inst["port"])
    return done


@contextlib.contextmanager
def _lock(profile: Path | str) -> Iterator[None]:
    key = hashlib.sha1(str(Path(profile).expanduser().resolve()).encode()).hexdigest()[:12]
    with _core.flock(f"plain-{key}"):
        yield


# ---------- launch / reuse ----------

def _app_bundle(exe: Path) -> Path | None:
    return next((p for p in exe.parents if p.suffix == ".app"), None)


def _use_open(exe: Path, headless: bool) -> bool:
    """macOS `open -g -n -a`: no focus steal, a new instance next to other Agent Chromes.
    CARHUNT_PLAIN_EXEC=1 forces a direct exec (tests, Linux, a bare binary)."""
    return (sys.platform == "darwin" and not headless and _app_bundle(exe) is not None
            and os.environ.get("CARHUNT_PLAIN_EXEC") != "1")


def build_args(profile: Path, port: int, *, headless: bool = False, onscreen: bool = False) -> list[str]:
    extra = ["--window-size=1360,900"]
    if not headless and not onscreen:
        extra.append("--window-position=-3000,0")  # off-screen: headed but invisible to the owner
    return chrome.launch_args(profile, port, headless=headless, extra=extra)


def _listener_pid(port: int, profile: Path) -> int | None:
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                         capture_output=True, text=True).stdout
    for pid in (int(x) for x in out.split()):
        args = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True).stdout
        if f"--user-data-dir={profile}" in args:
            return pid
    return None


def _launch(url: str, profile: Path, port: int, *, headless: bool, onscreen: bool,
            extra_args: list[str] | None = None, env: dict[str, str] | None = None) -> int:
    exe = chrome.agent_chrome_path()
    args = build_args(profile, port, headless=headless, onscreen=onscreen) + list(extra_args or [])
    proc = None
    if _use_open(exe, headless):
        envs = [x for k, v in (env or {}).items() for x in ("--env", f"{k}={v}")]
        subprocess.run(["open", "-g", "-n", "-a", str(_app_bundle(exe)), *envs, "--args", *args, url], check=True)
    else:
        proc = subprocess.Popen([str(exe), *args, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, env={**os.environ, **(env or {})})
    deadline = time.time() + 30
    while not _alive(port):
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(f"Chrome exited with {proc.returncode} before opening debug port {port}")
        if time.time() > deadline:
            raise RuntimeError(f"Chrome did not open its debug port {port}")
        time.sleep(0.3)
    pid = proc.pid if proc is not None else _listener_pid(port, profile)
    if not pid:
        raise RuntimeError(f"no process with --user-data-dir={profile} listens on {port}")
    return pid


def start(url: str, profile: Path | str, *, headless: bool = False, onscreen: bool = False, temp: bool = False,
          port: int | None = None, holder: int | None = None, extra_args: list[str] | None = None,
          env: dict[str, str] | None = None, jar_sync: bool = True, kind: str = "plain") -> tuple[int, str, bool]:
    """Reuse the profile's running browser (new tab) or launch one on `url`. Returns (port, target, reused).

    `holder` = pid of the caller holding the tab (None: unknown, e.g. a CLI `open`; the reaper then only
    applies its age limit). `extra_args`/`env`: geo launches (proxy, WebRTC, locale flags + TZ);
    `jar_sync=False` keeps a profile out of the trust-cookie jar both ways.
    """
    profile = Path(profile).expanduser()
    if profile.name.startswith("geo-") and not extra_args:
        # a geo profile must never reach the site from the home IP (account lives on one exit IP)
        raise RuntimeError(f"{profile.name}: geo profiles launch only through carhunt.access.geo (proxy flags)")
    profile.mkdir(parents=True, exist_ok=True)
    cleanup_dead()
    with _lock(profile):
        inst = _running(profile)
        if inst:
            t = json.loads(_http(inst["port"], "/json/new?" + urllib.parse.quote(url, safe=""), method="PUT"))
            inst["holders"][t["id"]] = holder
            _save(inst)
            return inst["port"], t["id"], True
        master = _s().profile_dir("identity")
        if jar_sync and master.exists() and not _same(master, profile):
            jar.export_from(master)  # pull the identity master's fresh solves into the jar first
        n = jar.import_into(profile) if jar_sync else 0
        if n:
            log(f"seeded {n} trust cookie(s) from the jar")
        port = port or port_for(profile)
        if port is None or _listening(port):
            if port is not None:
                log(f"port {port} busy, picking a free one")
            port = free_port()
        pid = _launch(url, profile, port, headless=headless, onscreen=onscreen, extra_args=extra_args, env=env)
        chrome.write_pid_record(pid, kind, profile=profile, debug_port=port, owner="plain-chrome")
        inst = dict(port=port, pid=pid, profile=str(profile), temp=temp, holders={}, started_at=time.time(),
                    jar=jar_sync)
        _save(inst)  # before waiting for the tab: a crash still leaves a record cleanup_dead() can tidy
        for _ in range(40):
            pages = _pages(port)
            if pages:
                inst["holders"][pages[0]["id"]] = holder
                _save(inst)
                return port, pages[0]["id"], False
            time.sleep(0.5)
    release(port, force=True)
    raise RuntimeError("Chrome opened no tab")


def ensure_running(profile: Path | str | None = None, port: int | None = None, *,
                   headless: bool = False, onscreen: bool = False, extra_args: list[str] | None = None,
                   env: dict[str, str] | None = None, jar: bool = True, kind: str = "plain") -> tuple[int, int]:
    """Make sure a browser runs on `profile` (default: shared plain). Returns (port, pid).

    Holds an about:blank tab for the calling process until `close(profile)`.
    """
    prof, _ = _profile_for(profile, False)
    inst = _running(prof)
    if inst:
        return inst["port"], inst["pid"]
    p, _target, _reused = start("about:blank", prof, headless=headless, onscreen=onscreen, port=port,
                                holder=os.getpid(), extra_args=extra_args, env=env, jar_sync=jar, kind=kind)
    return p, _load(p)["pid"]


def _quit(port: int, pid: int) -> None:
    """Clean quit so the cookie DB is flushed (a killed Chrome loses its last ~30 s of cookies).

    Browser.close on the browser endpoint attaches to no page (enabling page domains is what Imperva sees).
    """
    try:
        rawcdp.browser_send(port, "Browser.close")
        sent = True
    except Exception as e:  # the socket also drops when Chrome exits mid-reply: that counts as sent
        sent = not isinstance(e, (OSError, KeyError, ValueError)) or not _alive(port)
    for sig, wait_s in ((None, 20.0 if sent else 0.0), (signal.SIGTERM, 10.0), (signal.SIGKILL, 5.0)):
        if sig is not None:
            if sig == signal.SIGKILL:
                log(f"Chrome {pid} ignored Browser.close and SIGTERM; killing (recent cookies may be lost)")
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, sig)
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.2)


def release(port: int, target: str | None = None, *, force: bool = False) -> bool:
    """Give back a tab (or, without target, the whole browser). The browser quits when no other holder has a tab.

    Returns False when it refused (others hold tabs and not force, or not a plain-chrome port).
    """
    inst = _load(port)
    if inst is None:
        log(f"port {port}: no plain-chrome browser recorded here; leaving it alone")
        return False
    with _lock(inst["profile"]):
        inst = _load(port)
        if inst is None:
            return True
        if not _alive(port) or not _pid_alive(inst["pid"]):
            _after_exit(inst)
            return True
        page_ids = {t["id"] for t in _pages(port)}
        mine = os.getpid() if target is None else None  # a whole-browser close from this process owns its tabs
        others = [t for t, h in inst["holders"].items()
                  if t != target and t in page_ids and (mine is None or h != mine)]
        if others and not force:
            if target is None:
                log(f"{len(others)} tab(s) held by others: not closing; pass your TARGET (or --force)")
                return False
            with contextlib.suppress(Exception):
                _http(port, f"/json/close/{target}")
            inst["holders"].pop(target, None)
            _save(inst)
            return True
        # last holder: quit with our tab still open (a windowless Chrome refuses the CDP attach)
        _quit(port, inst["pid"])
        _after_exit(inst)
        return True


def close(profile: Path | str | None = None, *, force: bool = False) -> bool:
    """Close the browser running on `profile` (default: shared plain); cookies flush, jar export, temp dir removed."""
    prof, _ = _profile_for(profile, False)
    inst = _running(prof)
    if inst is None:
        cleanup_dead()
        return True
    return release(inst["port"], None, force=force)


# ---------- Playwright on top ----------

def _wait_committed(port: int, target: str, timeout: float) -> bool:
    """Wait until the tab's first navigation committed (its URL left about:blank) — no CDP attached yet."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(Exception):
            for t in _pages(port):
                if t["id"] == target and t.get("url") and not t["url"].startswith(("about:", "chrome:")):
                    return True
        time.sleep(0.5)
    log(f"tab {target}: no committed navigation after {timeout:.0f} s; attaching anyway")
    return False


def find_page(browser: Any, target: str) -> Any:
    for c in browser.contexts:
        for pg in c.pages:
            s = c.new_cdp_session(pg)
            try:
                if s.send("Target.getTargetInfo")["targetInfo"]["targetId"] == target:
                    return pg
            finally:
                s.detach()
    raise RuntimeError(f"tab {target} not found")


@contextlib.contextmanager
def open_tab(url: str, *, profile: Path | str | None = None, warm: str | None = None, fresh: bool = False,
             headless: bool = False, onscreen: bool = False, settle: float = FIRST_SETTLE_S,
             timeout: float = 45.0) -> Iterator[tuple[Any, Any]]:
    """Open `url` (after `warm`, if given) in a plain-chrome tab → (browser, page); the tab is released on exit.

    Playwright connects only after the first navigation committed + `settle` seconds.
    """
    prof, temp = _profile_for(profile, fresh)
    port, target, reused = start(warm or url, prof, headless=headless, onscreen=onscreen, temp=temp,
                                 holder=os.getpid())
    if reused:
        log(f"reusing the running browser on {prof} (port {port})")
    pw = None
    try:
        _wait_committed(port, target, timeout)
        time.sleep(settle)
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        page = find_page(browser, target)
        if warm:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            time.sleep(settle)
        yield browser, page
    finally:
        if pw is not None:
            with contextlib.suppress(Exception):
                pw.stop()
        release(port, target)


def report(page: Any, n: int, out: Path) -> dict:
    html = page.content()
    text = page.evaluate("document.body ? document.body.innerText : ''")
    base = out / f"{n:02d}"
    base.with_suffix(".txt").write_text(text)
    base.with_suffix(".html").write_text(html)
    with contextlib.suppress(Exception):
        page.screenshot(path=str(base.with_suffix(".jpg")), type="jpeg", quality=60)
    title = page.title()
    m = BLOCK.search(title + " " + text[:3000]) or BLOCK.search(html[:20000])
    return dict(n=n, final=page.url, title=title[:90], len=len(text),
                blocked=(m.group(0) if m else ("empty page" if len(text) < 50 else "")),
                head=re.sub(r"\s+", " ", text)[:160])


def fetch(urls: list[str], *, warm: str | None = None, wait: float = 10.0, out: Path | None = None,
          **kw: Any) -> list[dict]:
    """Visit urls in one tab; one result dict per URL (warm page included as n=0). Stops at nothing: check `blocked`."""
    out = Path(out) if out else _s().dir("plain-out", time.strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=True)
    seq = ([warm] if warm else []) + list(urls)
    results = []
    with open_tab(seq[0], settle=max(FIRST_SETTLE_S, wait), **kw) as (_b, page):
        for n, url in enumerate(seq):
            if n:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    r = dict(n=n, url=url, error=str(e)[:150])
                    print(json.dumps(r), flush=True)
                    results.append(r)
                    continue
                time.sleep(wait)
            r = report(page, n, out)
            r["url"] = url
            print(json.dumps(r, ensure_ascii=False), flush=True)
            results.append(r)
    return results


def show(port: int, target: str | None = None, *, on: bool = True) -> None:
    """Move the window on/off screen over the browser endpoint (no page attach)."""
    target = target or _pages(port)[0]["id"]
    wid = rawcdp.browser_send(port, "Browser.getWindowForTarget", {"targetId": target})["windowId"]
    rawcdp.browser_send(port, "Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
    rawcdp.browser_send(port, "Browser.setWindowBounds",
                        {"windowId": wid, "bounds": {"left": 80 if on else -3000, "top": 60}})
    if on:
        with contextlib.suppress(Exception):
            _http(port, f"/json/activate/{target}")
        inst = _load(port)
        if sys.platform == "darwin" and inst:
            subprocess.run(["osascript", "-e", f'tell application id "{_bundle_id()}" to activate'],
                           check=False, capture_output=True)


def _bundle_id() -> str:
    with contextlib.suppress(Exception):
        app = _app_bundle(chrome.agent_chrome_path(update=False))
        if app:
            out = subprocess.run(["defaults", "read", str(app / "Contents" / "Info"), "CFBundleIdentifier"],
                                 capture_output=True, text=True).stdout.strip()
            if out:
                return out
    return "com.google.Chrome"


def status() -> list[dict]:
    cleanup_dead()
    rows = []
    for inst in instances():
        try:
            tabs = len(_pages(inst["port"]))
        except Exception:
            tabs = None
        rows.append(dict(port=inst["port"], pid=inst["pid"], profile=inst["profile"], temp=inst.get("temp", False),
                         tabs=tabs, holders=len(inst["holders"]),
                         age_min=round((time.time() - inst.get("started_at", time.time())) / 60, 1)))
    return rows


# ---------- CLI ----------

def _opts(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", help="persistent profile dir (identity copy after `pw-identity acquire`)")
    p.add_argument("--fresh", action="store_true", help="throwaway profile (jar-seeded), deleted on close")
    p.add_argument("--warm", help="load this first (site home page)")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--onscreen", action="store_true")
    p.add_argument("--wait", type=float, default=10.0, help="seconds to let each page settle")


def _add_commands(sub: Any) -> None:
    p = sub.add_parser("fetch", help="load URLs in one tab, print one JSON line each")
    _opts(p)
    p.add_argument("--out", type=Path)
    p.add_argument("urls", nargs="+")
    p.set_defaults(func=_cmd_fetch)
    p = sub.add_parser("open", help="open a tab and leave it running")
    _opts(p)
    p.add_argument("url")
    p.set_defaults(func=_cmd_open)
    p = sub.add_parser("close", help="close your tab / a profile's browser")
    p.add_argument("port", nargs="?", type=int)
    p.add_argument("target", nargs="?")
    p.add_argument("--profile")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=_cmd_close)
    for name in ("show", "hide"):
        p = sub.add_parser(name, help="move the window on-screen (captcha hand-off)" if name == "show" else
                           "move it back off-screen")
        p.add_argument("port", type=int)
        p.add_argument("target", nargs="?")
        p.set_defaults(func=_cmd_show, on=(name == "show"))
    p = sub.add_parser("cookies", help="list the trust-cookie jar (no values)")
    p.add_argument("--delete", nargs=2, metavar=("DOMAIN", "NAME"))
    p.set_defaults(func=_cmd_cookies)
    p = sub.add_parser("status", help="running plain-chrome browsers")
    p.set_defaults(func=_cmd_status)


def _kw(a: argparse.Namespace) -> dict:
    return dict(profile=a.profile, fresh=a.fresh, headless=a.headless, onscreen=a.onscreen)


def _cmd_fetch(a: argparse.Namespace) -> int:
    rs = fetch(a.urls, warm=a.warm, wait=a.wait, out=a.out, **_kw(a))
    return 1 if any(r.get("blocked") or r.get("error") for r in rs) else 0


def _cmd_open(a: argparse.Namespace) -> int:
    prof, temp = _profile_for(a.profile, a.fresh)
    first = a.warm or a.url
    port, target, reused = start(first, prof, headless=a.headless, onscreen=a.onscreen, temp=temp)
    if a.warm:  # warm page first, then the real URL in the same tab, still without attaching
        _wait_committed(port, target, 45)
        time.sleep(a.wait)
        p = rawcdp.Page(port, target)
        try:
            p.navigate(a.url)
        finally:
            p.close()
    print(json.dumps(dict(cdp=f"http://127.0.0.1:{port}", port=port, target=target, profile=str(prof),
                          reused=reused)))
    return 0


def _cmd_close(a: argparse.Namespace) -> int:
    if a.port is not None:
        return 0 if release(a.port, a.target, force=a.force) else 1
    return 0 if close(a.profile, force=a.force) else 1


def _cmd_show(a: argparse.Namespace) -> int:
    show(a.port, a.target, on=a.on)
    return 0


def _cmd_cookies(a: argparse.Namespace) -> int:
    if a.delete:
        domain, name = a.delete
        prof = shared_profile()
        if _running(prof):
            log("shared plain browser is running: deleted from the jar only; `plain-chrome close` and repeat, "
                "or its copy returns on the next export")
            profiles = []
        else:
            profiles = [prof]
        print(f"deleted {jar.delete(domain, name, profiles=profiles)} row(s)")
        return 0
    for r in jar.listing():
        print(f"{r['host']:32} {r['name']:16} until {time.strftime('%Y-%m-%d', time.localtime(r['expires']))}")
    return 0


def _cmd_status(_a: argparse.Namespace) -> int:
    rows = status()
    for r in rows:
        print(json.dumps(r))
    if not rows:
        print("no plain-chrome browsers running")
    return 0


def register_cli(sub: Any) -> None:
    """`carhunt browser plain <cmd>` under the browser group."""
    p = sub.add_parser("plain", help="plain-chrome: Chrome launched like a person, attach after first load")
    _add_commands(p.add_subparsers(dest="plain_cmd", required=True))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="plain-chrome", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except RuntimeError as e:
        log(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
