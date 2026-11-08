"""Identity browsers: who holds each, release on idle, the pool of copies, cookie sync.

An identity browser is a persistent Chrome profile with the owner's logins, served to agents by its own
Playwright MCP server (`serve identity|identity-<x>`, MCP names `ch-identity`, `ch-identity-<x>`). Chrome
allows one live process per profile, so each browser has ONE holder at a time; the pool lets several agents
work at once, one per browser.

  identity        $CARHUNT_HOME/browsers/profiles/identity      the master (Google logins live here only)
  identity-a …    $CARHUNT_HOME/browsers/profiles/identity-<x>  copies of the master (`seed`), one holder each

Logins move between them by cookie sync. Google cookies never sync: Google logs out a session it sees in
several profiles (10-21); a copy keeps its own Google login, if any.
  - a copy's Chrome closes → its cookies newer than the master's go into the master (or, while the master's
    Chrome runs, into a pending store applied right before the master's next launch);
  - a copy's Chrome launches → it first pulls the master's (+ pending) newer cookies.
Only cookies sync: a site keeping its login in localStorage needs that login made on the master (or a `seed`).
All profiles use Chrome's mock keychain, so encrypted cookie values are portable between them.

Holders: an agent session (Claude Code hooks: the session that last called an identity tool while its Chrome
was up), `script:<name>` (`acquire`: a script launching its own Chrome on the profile), `login` (manual
sign-in window), `seed:<x>`. A detached reaper closes an agent-held Chrome after `browsers.idle_release_s`
(180 s) idle with no call in flight; the next call relaunches it on the same profile, cookies intact.
Hold an identity browser for ONE step, then browser_close; never across a wait on the user (a parked
master blocked two agents for >90 min, 11-01).

  pw-identity [-b <browser>] status            free | held by …; exit 1 if another session holds it
  pw-identity pool                             every identity browser + seed age
  pw-identity [-b <browser>] release [--force] [--holder H]   close it now (own / idle holder; --force: any)
  pw-identity [-b <browser>] login [url …]     plain, non-automated Chrome on the profile for signing in
                                               (Google refuses sign-in from an automation-controlled Chrome)
  pw-identity acquire <name> [--any | --pool | -b <browser>]
                                               for a script launching its own Chrome on a profile: frees an
                                               idle holder, records script:<name>, syncs cookies in, prints
                                               "acquired <browser> for <name>" then the profile path; exit 1 if
                                               busy. --any: a free copy, else the master, else an idle-held copy
                                               (copies first: keep the master free for Google steps). The hold
                                               ends (cookies sync out) when that Chrome exits.
  pw-identity seed <x|identity-x|--all|--stale [hours]>   fresh copy of the master onto pool browser(s), minus
                                               Google; works while the master runs (file clones)
  pw-identity sync [<browser>|--all]           run the cookie sync now (closed browsers only)
  pw-identity reap                             one pass: release idle agent holds / ended script holds
  pw-identity [-b <browser>] restart [--dry-run]   close its Chrome, kickstart its carhunt.* MCP server job
  pw-identity hook pre|post                    Claude Code Pre/PostToolUse(+Failure) on mcp__ch-identity(-x)?__.*
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from carhunt.access import _core
from carhunt.access import settings as _settings
from carhunt.access.errors import LeaseBusy
from carhunt.access.mcp import browser_for_server, server_name

MASTER = "identity"
LOGIN = "login"                     # holder id of a manual-login Chrome
ACQUIRE_GRACE = 60                  # a script holder may take this long to start its Chrome
INFLIGHT_MAX = 600                  # a tool call without its Post hook is dropped after this
RESEED_HOURS = 24.0
REPO = Path(__file__).resolve().parents[2]

# Not copied by `seed`: locks of the source's Chrome, caches, the open-tab session, on-device models
# (~4.4 GB on a master, 11-01: Chrome re-downloads them if it wants them).
SEED_SKIP_TOP = {"SingletonLock", "SingletonCookie", "SingletonSocket", "GPUCache", "GrShaderCache",
                 "ShaderCache", "GPUPersistentCache", "GraphiteDawnCache", "component_crx_cache",
                 "extensions_crx_cache", "BrowserMetrics", "BrowserMetrics-spare.pma", "Crashpad",
                 "RunningChromeVersion", "plain-chrome.json",
                 "OptGuideManifestModel", "optimization_guide_model_store", "OnDeviceHeadSuggestModel",
                 "WasmTtsEngine"}
SEED_SKIP_DEFAULT = {"Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "Sessions",
                     "Sessions_Encrypted", "Current Session", "Current Tabs", "Last Session", "Last Tabs",
                     "LOCK", "Shared Dictionary"}
# Inside Default: caches nobody needs in a copy (Service Worker caches: ~7k files; Google's IndexedDB blobs).
SEED_SKIP_PATHS = {"Service Worker/CacheStorage", "Service Worker/ScriptCache"}
SEED_SKIP_GLOBS = ["IndexedDB/https_*google.com_*", "IndexedDB/https_*youtube.com_*"]
GOOGLE_COOKIES = "host_key like '%google.%' or host_key like '%youtube.com' or host_key like '%gmail.com'"
GOOGLE_URL = re.compile(r"https?://([a-z0-9-]+\.)*(google\.[a-z.]+|gmail\.com|youtube\.com)(/|$|\?)", re.I)
KEY = ["host_key", "top_frame_site_key", "has_cross_site_ancestor", "name", "path", "source_scheme", "source_port"]


def _clock() -> int:
    if os.environ.get("CARHUNT_FAKE_NOW"):
        return int(_core.now().timestamp())
    return int(time.time())


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def chrome_pids() -> dict[str, int]:
    """{realpath(profile): main Chrome pid} for every Chrome process started with --user-data-dir (read-only ps)."""
    out = subprocess.run(["ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True).stdout
    found = {}
    for line in out.splitlines():
        pid, _, cmd = line.strip().partition(" ")
        if ("/Contents/MacOS/Google Chrome" not in cmd and "/chrome " not in cmd) or "--type=" in cmd:
            continue
        m = re.search(r"--user-data-dir=(.+?)(?= --|$)", cmd)
        if m:
            found[os.path.realpath(m.group(1).strip())] = int(pid)
    return found


def _kill(pid: int) -> None:
    """Stop one known Chrome (found by its profile path): TERM, then KILL after 6 s."""
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(12):
            time.sleep(0.5)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    time.sleep(0.5)                  # let the profile's files settle before a sync reads/writes them


def owned_outside(h: dict | None) -> bool:
    """A holder whose Chrome agents don't manage: a login window, a script's own Chrome, a seed copy."""
    return bool(h) and (h["session"] == LOGIN or h["session"].startswith(("script:", "seed:")))


def script_holder(holder: str) -> str:
    return holder if holder.startswith(("script:", "seed:")) or holder == LOGIN else f"script:{holder}"


def describe(h: dict | None) -> str:
    if not h:
        return "an unknown session"
    if h["session"] == LOGIN:
        return "a manual-login window"
    if h["session"].startswith("script:"):
        return f"the script {h['session'][7:]} (its own Chrome)"
    if h["session"].startswith("seed:"):
        return f"a seed copy ({h['session'][5:]})"
    return f"session {h['session'][:8]} ({h.get('cwd', '?')})"


@dataclass(frozen=True)
class Lease:
    """What `acquire` hands a script: launch your Chrome on `profile`; the hold ends when it exits."""
    name: str
    profile: Path
    mcp_port: int
    debug_port: int


class _FileLock:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = open(self.path, "a")
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        self.fd.close()


class _State:
    """flock-guarded lease state of one browser (leases/<browser>/); the kernel drops the lock if we die."""

    def __init__(self, pool: Pool, b: str, wait: float = 10):
        self.pool, self.b, self.wait = pool, b, wait
        self.dir = pool.s.leases_dir / b

    def __enter__(self):
        (self.dir / "inflight").mkdir(parents=True, exist_ok=True)
        self.fd = open(self.dir / "lock", "a")
        deadline = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() > deadline:
                    self.fd.close()
                    raise TimeoutError(f"{self.b} lease lock busy")
                time.sleep(0.05)

    def __exit__(self, *a):
        self.fd.close()

    def put(self, name: str, text: str) -> None:
        tmp = self.dir / f".{name}.{os.getpid()}"
        tmp.write_text(text)
        tmp.replace(self.dir / name)

    def _int(self, name: str) -> int:
        try:
            return int((self.dir / name).read_text())
        except (OSError, ValueError):
            return 0

    @property
    def holder(self) -> dict | None:
        try:
            return json.loads((self.dir / "holder").read_text())
        except (OSError, ValueError):
            return None

    @property
    def summary(self) -> Path:
        """leases/<browser>.json while held: browser-reaper spares a Chrome whose profile a lease names."""
        return self.dir.parent / f"{self.b}.json"

    @holder.setter
    def holder(self, h: dict | None) -> None:
        if h is None:
            (self.dir / "holder").unlink(missing_ok=True)
            self.summary.unlink(missing_ok=True)
        else:
            self.put("holder", json.dumps(h))
            tmp = self.summary.with_name(f".{self.b}.json.{os.getpid()}")
            tmp.write_text(json.dumps({"browser": self.b, "profile": str(self.pool.profile(self.b).resolve()),
                                       **h}))
            tmp.replace(self.summary)

    def last_use(self) -> int:
        return self._int("last-use")

    def stamp(self, now: int | None = None) -> None:
        self.put("last-use", str(self.pool.clock() if now is None else now))

    def seeded_at(self) -> int:
        return self._int("seeded-at")

    def inflight(self, now: int | None = None) -> int:
        now = self.pool.clock() if now is None else now
        d = self.dir / "inflight"
        if not d.is_dir():
            return 0
        n = 0
        for f in d.iterdir():
            try:
                started = int(f.read_text() or 0)
            except (OSError, ValueError):
                started = 0
            if now - started > INFLIGHT_MAX:
                f.unlink(missing_ok=True)
            else:
                n += 1
        return n

    def idle_for(self, now: int | None = None) -> int:
        return (self.pool.clock() if now is None else now) - self.last_use()

    def takeable(self, now: int | None = None) -> bool:
        """Its Chrome (if any) may be closed by someone else: no holder, or an idle agent holder."""
        h = self.holder
        if not h:
            return True
        if owned_outside(h):
            return False
        return self.inflight(now) == 0 and self.idle_for(now) >= self.pool.ttl

    def pending(self, now: int | None = None) -> bool:
        """A holder with no Chrome yet that must not be taken over: a running seed, a script still launching."""
        h = self.holder
        if not h:
            return False
        if h["session"].startswith("seed:"):
            return _alive(h.get("pid", 0))
        now = self.pool.clock() if now is None else now
        return h["session"].startswith("script:") and now - h.get("since", 0) < ACQUIRE_GRACE

    def clear(self) -> None:
        self.holder = None
        d = self.dir / "inflight"
        if d.is_dir():
            for f in d.iterdir():
                f.unlink(missing_ok=True)


class Pool:
    """The identity master + its copies. Injectable seams for tests: clock, chrome_pids, kill, launchctl."""

    def __init__(self, s: _settings.Settings | None = None, *, clock: Callable[[], int] = _clock,
                 find_chromes: Callable[[], dict[str, int]] = chrome_pids,
                 kill: Callable[[int], None] = _kill,
                 launchctl: Callable[[list[str]], object] | None = None):
        self.s = s or _settings.load()
        self.clock, self._find, self._kill = clock, find_chromes, kill
        self._launchctl = launchctl or (lambda cmd: subprocess.run(cmd, check=False))
        self.ttl = int(self.s.idle_release_s)
        self.reseed_hours = float(_core.section("browsers").get("identity_reseed_hours", RESEED_HOURS))

    # ----- names / paths -----

    @property
    def pool(self) -> list[str]:
        return self.s.pool_names()

    @property
    def browsers(self) -> list[str]:
        return [MASTER, *self.pool]

    def normalize(self, name: str) -> str:
        name = name.strip()
        if name in ("", "master"):
            return MASTER
        if len(name) == 1:
            name = f"identity-{name}"
        if name not in self.browsers:
            raise ValueError(f"unknown identity browser {name!r}: {', '.join(self.browsers)}")
        return name

    def profile(self, b: str) -> Path:
        return self.s.profile_dir(b)

    def by_profile(self, path: str | Path) -> str | None:
        real = os.path.realpath(path)
        for b in self.browsers:
            if os.path.realpath(self.profile(b)) == real:
                return b
        return None

    def state(self, b: str, wait: float = 10) -> _State:
        return _State(self, b, wait)

    def chrome_pid(self, b: str) -> int | None:
        return self._find().get(os.path.realpath(self.profile(b)))

    @property
    def _pending_db(self) -> Path:
        return self.s.leases_dir / "pending-cookies.db"

    @property
    def _pending_lock(self) -> Path:
        return self.s.leases_dir / "pending.lock"

    def log(self, msg: str) -> None:
        try:
            with open(self.s.logs / "identity.log", "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        except OSError:
            pass

    def lease_for(self, b: str) -> Lease:
        return Lease(b, self.profile(b), self.s.mcp_port(b), self.s.debug_port(b))

    # ----- cookie sync -----

    def cookie_db(self, b: str) -> Path:
        return self.profile(b) / "Default" / "Cookies"

    def apply_pending(self) -> int:
        """Pending store → master. Caller holds the master's lease and has checked its Chrome is down."""
        with _FileLock(self._pending_lock):
            if not self._pending_db.exists():
                return 0
            n = merge_cookies(self._pending_db, self.cookie_db(MASTER), log=self.log)
            self._pending_db.unlink(missing_ok=True)
        if n:
            self.log(f"pending → master: {n} cookie(s)")
        return n

    def push(self, b: str) -> None:
        """A closed copy's cookies → master if the master's Chrome is down (else → pending). Caller holds b's lease."""
        src = self.cookie_db(b)
        if b == MASTER or not src.exists():
            return
        try:
            with self.state(MASTER, wait=2) as lm:
                # inflight: a pre hook just let a call through that is about to launch the master's Chrome
                if not self.chrome_pid(MASTER) and not lm.pending() and lm.inflight() == 0:
                    self.apply_pending()
                    n = merge_cookies(src, self.cookie_db(MASTER), log=self.log)
                    if n:
                        self.log(f"{b} → master: {n} cookie(s)")
                    return
        except TimeoutError:
            pass
        with _FileLock(self._pending_lock):
            n = merge_cookies(src, self._pending_db, create=True, baseline=self.cookie_db(MASTER), log=self.log)
        if n:
            self.log(f"{b} → pending (master busy): {n} cookie(s)")

    def pull(self, b: str) -> None:
        """Master (+ pending) cookies newer than the copy's → the copy. The copy's Chrome must be down."""
        dst = self.cookie_db(b)
        if b == MASTER or not dst.exists():
            return
        n = merge_cookies(self.cookie_db(MASTER), dst, log=self.log)
        with _FileLock(self._pending_lock):
            if self._pending_db.exists():
                n += merge_cookies(self._pending_db, dst, log=self.log)
        if n:
            self.log(f"master → {b}: {n} cookie(s)")

    def on_closed(self, b: str) -> None:
        """b's Chrome just exited (caller holds b's lease)."""
        try:
            if b == MASTER:
                self.apply_pending()
            else:
                self.push(b)
        except Exception as e:  # sync is best effort; never break a hook over it
            self.log(f"on_closed {b}: {e!r}")

    def before_launch(self, b: str) -> None:
        """b's Chrome is about to start (caller holds b's lease, no Chrome on it)."""
        try:
            if b == MASTER:
                self.apply_pending()
            else:
                self.push(b)         # catch up a close nobody synced (crash, reboot)
                self.pull(b)
        except Exception as e:
            self.log(f"before_launch {b}: {e!r}")

    # ----- holders -----

    def free_pool(self, exclude: tuple[str, ...] = ()) -> list[str]:
        """Seeded copies nobody holds now (no Chrome, no pending holder). Lock-free: hooks call it while
        holding their own browser's lock."""
        pids, free = self._find(), []
        for b in self.pool:
            st = self.state(b)
            if (b not in exclude and os.path.realpath(self.profile(b)) not in pids and st.seeded_at()
                    and not st.pending()):
                free.append(b)
        return free

    def _take(self, st: _State, holder: dict) -> str | None:
        """Under st's lock: make the browser free for `holder` (close an idle agent's Chrome). Error or None."""
        b, h = st.b, st.holder
        pid = self.chrome_pid(b)
        if h and h["session"] == holder["session"] and not pid:
            st.holder = holder               # same script re-acquiring before its Chrome started
            return None
        if st.pending() or (pid and not st.takeable()):
            return f"{b} busy: held by {describe(h)}"
        if pid:
            self._kill(pid)
            self.on_closed(b)
        st.clear()
        st.holder = holder
        return None

    def acquire(self, holder: str, name: str | None = None, *, any_: bool = False,
                pool_only: bool = False) -> Lease:
        """Hold an identity browser for a script that launches its own Chrome on `Lease.profile`.
        Raises LeaseBusy when every candidate is held."""
        h = {"session": script_holder(holder), "since": self.clock()}
        if any_ or pool_only:                # truly free copies first, then idle-held ones
            free = self.free_pool()
            rest = [x for x in self.pool if x not in free]
            # copies first: keep the master free for Google / localStorage-login steps
            candidates = free + ([MASTER] if any_ else []) + rest
        else:
            candidates = [self.normalize(name or MASTER)]
        errs = []
        for b in candidates:
            with self.state(b) as st:
                if b != MASTER and not st.seeded_at():
                    errs.append(f"{b} never seeded (pw-identity seed {b})")
                    continue
                err = self._take(st, h)
                if not err:
                    self.before_launch(b)
            if not err:
                self.arm_reaper(b)
                return self.lease_for(b)
            errs.append(err)
        raise LeaseBusy("busy: " + "; ".join(errs) + " — retry later")

    def acquire_any(self, holder: str) -> Lease:
        return self.acquire(holder, any_=True)

    def release(self, holder: str | None, name: str = MASTER, *, force: bool = False) -> int | None:
        """Close `name` now. Allowed for its holder, when idle/orphaned, or with force. Returns the closed pid."""
        b = self.normalize(name)
        with self.state(b) as st:
            pid, h = self.chrome_pid(b), st.holder
            if not pid:
                if not h:
                    return None
                if h["session"].startswith("seed:") and st.pending():
                    raise LeaseBusy(f"{b} not released: {describe(h)} in progress")
                if st.pending() and not self._is(h, holder) and not force:
                    raise LeaseBusy(f"{b} not released: held by {describe(h)} (its Chrome is starting)")
                st.clear()                   # a hold without a Chrome (a script that already quit)
                return None
            mine = self._is(h, holder)
            if h and not mine and not st.takeable() and not force:
                raise LeaseBusy(f"{b} not released: held by {describe(h)}, idle {st.idle_for()}s (use --force)")
            self._kill(pid)
            st.clear()
            self.on_closed(b)
            return pid

    @staticmethod
    def _is(h: dict | None, holder: str | None) -> bool:
        return bool(h) and holder is not None and h["session"] in (holder, script_holder(holder))

    def held(self) -> dict[str, dict]:
        """{browser: {holder, chrome_pid, idle_s, inflight, seeded_at}} for every held or running browser."""
        out = {}
        for b in self.browsers:
            st = self.state(b)
            pid, h = self.chrome_pid(b), st.holder
            if h or pid:
                out[b] = {"holder": h, "chrome_pid": pid, "idle_s": st.idle_for() if st.last_use() else None,
                          "inflight": st.inflight(), "seeded_at": st.seeded_at() or None}
        return out

    def reap_idle(self, now: int | None = None) -> list[str]:
        """One pass: close agent-held Chromes idle ≥ ttl with no call in flight; clear holds whose Chrome is gone
        (scripts past their launch grace, agents, login windows). Returns the browsers released."""
        now = self.clock() if now is None else now
        released = []
        for b in self.browsers:
            with self.state(b) as st:
                pid, h = self.chrome_pid(b), st.holder
                if pid:
                    if h and not owned_outside(h) and st.inflight(now) == 0 and st.idle_for(now) >= self.ttl:
                        self._kill(pid)
                        st.clear()
                        self.on_closed(b)
                        released.append(b)
                    continue
                if not h or st.pending(now) or st.inflight(now):
                    continue                 # nothing held / still launching / a pre hook is about to launch it
                st.clear()
                if not h["session"].startswith("seed:"):
                    self.on_closed(b)
                released.append(b)
        return released

    # ----- detached reaper (one per browser while held) -----

    def arm_reaper(self, b: str) -> None:
        if os.environ.get("CARHUNT_IDENTITY_REAPER") == "0":    # tests drive reap_idle() instead
            return
        # Under the lease: a reaper decides to exit under the same lock, so a live pidfile here means that
        # reaper will still see this new holder (no gap where neither watches; seen 11-01).
        with self.state(b) as st:
            pidfile = st.dir / "reaper"
            try:
                if _alive(pidfile.read_text()):
                    return
            except OSError:
                pass
            env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO), os.environ.get("PYTHONPATH")]))}
            p = subprocess.Popen([sys.executable, "-m", "carhunt.access.identity", "reaper", b], env=env,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            pidfile.write_text(str(p.pid))

    def reaper(self, b: str) -> None:
        """Watch b until nothing holds it: each round ends when the current holder's Chrome is gone."""
        while True:
            self._reap_round(b)
            time.sleep(0.5)
            with self.state(b) as st:
                if not st.holder and not self.chrome_pid(b) and st.inflight() == 0:
                    (st.dir / "reaper").unlink(missing_ok=True)
                    return

    def _ran_since(self, b: str, t: int) -> bool:
        """A Chrome wrote b's profile at/after t (it writes these on start/stop; not Cookies: the pull writes it)."""
        for f in ("Local State", "Default/Preferences"):
            try:
                if (self.profile(b) / f).stat().st_mtime >= t:
                    return True
            except OSError:
                pass
        return False

    def _reap_round(self, b: str) -> None:
        seen = False                         # a script holder's Chrome has started
        while True:
            pid = self.chrome_pid(b)
            h = self.state(b).holder
            if h and h["session"].startswith("script:"):
                # A short-lived Chrome can start and exit between two polls; a profile written since the hold
                # began also means "it ran".
                seen = seen or bool(pid) or self._ran_since(b, h.get("since", 0))
                if not pid and (seen or self.clock() - h.get("since", 0) >= ACQUIRE_GRACE):
                    time.sleep(1)
                    with self.state(b) as st:  # the script's Chrome exited (or never came): the hold ends
                        if st.holder == h:
                            st.clear()
                        if seen and not self.chrome_pid(b):
                            self.on_closed(b)
                    return
                time.sleep(0.3)
                continue
            if not pid:
                with self.state(b) as st:
                    launching = st.inflight() > 0      # the pre hook runs before the tool launches Chrome
                    hh = st.holder
                    if not launching:
                        if hh and (hh["session"] == LOGIN or not owned_outside(hh)):
                            st.clear()
                        if not (hh and hh["session"].startswith("seed:")):
                            self.on_closed(b)
                if not launching:
                    return
                time.sleep(1)
                continue
            with self.state(b) as st:
                h = st.holder
                if h and h["session"] == LOGIN:
                    pass                     # the owner closes it; keep watching so the close gets synced
                elif owned_outside(h):
                    time.sleep(2)            # a script/seed: wait for its Chrome to exit (handled above)
                    continue
                else:
                    idle = st.idle_for()
                    due = 0 if st.inflight() == 0 and idle >= self.ttl else max(1, self.ttl - idle)
                    if due == 0:
                        self._kill(pid)
                        st.clear()
                        self.on_closed(b)
                        return
                    time.sleep(min(due, 5))
                    continue
            time.sleep(2)

    # ----- Claude Code hooks -----

    def _others_hint(self, b: str) -> str:
        free = self.free_pool(exclude=(b,))
        if free:
            return f" Free now: {', '.join(free)} — use those tools (mcp__{server_name(free[0])}__*) instead."
        return " No pool browser is free right now either."

    def hook(self, sub: str, ev: dict) -> int:
        """Pre/PostToolUse on identity MCP tools. Returns the exit code (2 = block the call, reason on stderr)."""
        me = ev.get("session_id") or os.environ.get("AGTERM_SESSION_ID") or "?"
        tid, tool = ev.get("tool_use_id", ""), ev.get("tool_name", "")
        parts = tool.split("__")
        b = browser_for_server(parts[1]) if len(parts) >= 3 else None
        if b not in self.browsers:
            return 0                         # not one of ours (another stack's tools, a disabled copy)
        with self.state(b) as st:
            pid, h = self.chrome_pid(b), st.holder
            if sub == "pre":
                url = str((ev.get("tool_input") or {}).get("url", ""))
                if b != MASTER and tool.endswith("browser_navigate") and GOOGLE_URL.match(url):
                    sys.stderr.write(
                        f"Google is master-only: copies carry no Google session (Google logs out a session shared "
                        f"by several profiles). Use the master (mcp__{server_name(MASTER)}__*) for {url[:60]}, "
                        f"one step, then browser_close.\n")
                    return 2
                if b != MASTER and not st.seeded_at():
                    sys.stderr.write(f"{b} has no copy of the master's logins yet. Run `pw-identity seed {b}`, "
                                     f"or use another one.{self._others_hint(b)}\n")
                    return 2
                if (pid or st.pending()) and h and h["session"] != me:
                    if owned_outside(h):
                        sys.stderr.write(f"{b} is held by {describe(h)}. Wait until it closes (check: "
                                         f"pw-identity -b {b} status), then retry. Don't close it yourself."
                                         f"{self._others_hint(b)}\n")
                        return 2
                    busy, idle = st.inflight(), st.idle_for()
                    if busy or idle < self.ttl:
                        wait = INFLIGHT_MAX if busy else self.ttl - idle
                        sys.stderr.write(
                            f"{b} is held by {describe(h)}, last used {idle}s ago, {busy} call(s) in flight. It "
                            f"frees itself after {self.ttl}s idle (≤ ~{wait}s from now) or when that session calls "
                            f"browser_close. Don't force-release it.{self._others_hint(b)}\n")
                        return 2
                    if pid:
                        self._kill(pid)      # idle holder: take over
                        self.on_closed(b)
                        pid = None
                    st.clear()
                if not pid:
                    self.before_launch(b)    # this call (re)starts its Chrome
                if not pid or not h or h["session"] != me:
                    st.holder = {"session": me, "cwd": ev.get("cwd", ""), "since": self.clock()}
                if tid:
                    (st.dir / "inflight" / _safe(tid)).write_text(str(self.clock()))
                st.stamp()
            else:
                if tid:
                    (st.dir / "inflight" / _safe(tid)).unlink(missing_ok=True)
                if h and h["session"] == me:
                    st.stamp()
                    if tool.endswith("browser_close"):
                        st.clear()
        self.arm_reaper(b)
        return 0

    # ----- login / restart -----

    def login(self, b: str, urls: list[str], *, force: bool = False) -> int:
        from carhunt.access import chrome
        with self.state(b) as st:
            pid, h = self.chrome_pid(b), st.holder
            busy = pid and h and h["session"] != LOGIN and (st.inflight() or st.idle_for() < self.ttl)
            if (busy or st.pending()) and not force:
                raise LeaseBusy(f"busy: held by {describe(h)}, idle {st.idle_for()}s — retry shortly or use --force")
            if pid:
                self._kill(pid)
                self.on_closed(b)
            self.before_launch(b)
            st.holder = {"session": LOGIN, "since": self.clock()}
            # Mock keychain = same cookie encryption as the MCP's Chrome; no debug port, no automation (Google
            # refuses sign-in from an automation-controlled Chrome). Agent Chrome, never the user's Chrome app.
            exe = chrome.agent_chrome_path(update=False)
            p = subprocess.Popen([str(exe), *chrome.launch_args(self.profile(b), None), *urls],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            chrome.write_pid_record(p.pid, "identity", profile=self.profile(b), debug_port=None, owner=LOGIN)
        self.arm_reaper(b)
        return p.pid

    def restart_server(self, b: str, *, dry_run: bool = False) -> list[str]:
        """Kickstart b's MCP server job (only carhunt.* labels: never another stack's launchd jobs)."""
        label = self.s.label(b)
        if not label.startswith("carhunt."):
            raise ValueError(f"refusing launchd label {label!r}: only carhunt.* jobs")
        cmd = ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{label}"]
        if not dry_run:
            self._launchctl(cmd)
        return cmd

    # ----- seed -----

    def seed(self, names: list[str] | None = None) -> dict[str, str | None]:
        """Fresh copy of the master onto each pool browser → {browser: None | reason not seeded}."""
        return {b: self._seed_one(b) for b in (names or self.pool)}

    def stale(self, hours: float | None = None) -> list[str]:
        hours = self.reseed_hours if hours is None else hours
        out = []
        for b in self.pool:
            with self.state(b) as st:
                if self.clock() - st.seeded_at() > hours * 3600:
                    out.append(b)
        return out

    def _seed_one(self, b: str) -> str | None:
        b = self.normalize(b)
        if b == MASTER:
            return "the master is the source; seed a pool browser"
        src, dst = self.profile(MASTER), self.profile(b)
        if not (src / "Default").is_dir():
            return f"master profile {src} has no Default/ yet (log in first: pw-identity login)"
        mark = {"session": f"seed:{b}", "pid": os.getpid(), "since": self.clock()}
        with self.state(b) as st:
            err = self._take(st, mark)
            if err:
                return err
            self.push(b)                     # don't lose logins made in the old copy
        tmp, old = dst.with_name(f".{dst.name}.seed-tmp"), dst.with_name(f".{dst.name}.old")
        try:
            for p in (tmp, old):
                shutil.rmtree(p, ignore_errors=True)
            copy_profile(src, tmp)
            keep_own_google(tmp, dst)
            with _FileLock(self._pending_lock):
                if self._pending_db.exists():
                    merge_cookies(self._pending_db, tmp / "Default" / "Cookies", log=self.log)
            if dst.exists():
                dst.rename(old)
            tmp.rename(dst)
            shutil.rmtree(old, ignore_errors=True)
            with self.state(b) as st:
                st.put("seeded-at", str(self.clock()))
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            with self.state(b) as st:
                if st.holder == mark:
                    st.clear()

    def sync(self, names: list[str] | None = None) -> dict[str, str]:
        """Run the cookie sync for closed browsers now → {browser: synced | skipped reason}."""
        out = {}
        for b in names or [*self.pool, MASTER]:
            b = self.normalize(b)
            with self.state(b) as st:
                if self.chrome_pid(b) or st.pending():
                    out[b] = "running, skipped (syncs when its Chrome closes)"
                    continue
                if b == MASTER:
                    self.on_closed(b)
                else:
                    self.before_launch(b)
                out[b] = "synced"
        return out

    # ----- status -----

    def status_line(self, b: str) -> str:
        st = self.state(b)
        pid, h = self.chrome_pid(b), st.holder
        if not pid:
            return f"pending: {describe(h)}" if st.pending() else "free"
        idle = (f"for {self.clock() - h['since']}s" if owned_outside(h) else
                f"idle {st.idle_for()}s" if st.last_use() else "never used via hooks")
        return f"held: chrome pid {pid} by {describe(h)}, {idle}, {st.inflight()} call(s) in flight"


def _safe(tid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", tid)[:120] or "call"


# ---------- cookie DB helpers ----------

def _chrome_now() -> int:
    return int((time.time() + 11644473600) * 1_000_000)


@contextlib.contextmanager
def _snapshot(db: Path) -> Iterator[Path]:
    """Copy a (maybe live) Cookies DB + journal to a temp dir; SQLite rolls a hot journal back on open."""
    tmp = Path(tempfile.mkdtemp(prefix="carhunt-ck-"))
    try:
        shutil.copy2(db, tmp / "Cookies")
        j = Path(str(db) + "-journal")
        if j.exists():
            shutil.copy2(j, tmp / "Cookies-journal")
        yield tmp / "Cookies"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def merge_cookies(src: Path, dst: Path, *, create: bool = False, baseline: Path | None = None,
                  log: Callable[[str], None] = lambda m: None) -> int:
    """Upsert src's non-Google, unexpired cookies into dst where src's copy is newer (last_update_utc) than dst's
    (and than `baseline`'s, e.g. the live master's). dst must not be open in a running Chrome. Returns rows written."""
    if not Path(src).exists() or (not create and not Path(dst).exists()):
        return 0
    with contextlib.ExitStack() as stack:
        snap = stack.enter_context(_snapshot(Path(src)))
        base = stack.enter_context(_snapshot(Path(baseline))) if baseline and Path(baseline).exists() else None
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(dst, timeout=10)
        try:
            c.execute("attach database ? as s", (str(snap),))
            if create:
                c.execute("create table if not exists main.cookies as select * from s.cookies where 0")
                for (sql,) in c.execute("select sql from s.sqlite_master where type='index' and sql is not null"
                                        ).fetchall():
                    c.execute(sql.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1))
            cols = [r[1] for r in c.execute("pragma main.table_info(cookies)")]
            scols = {r[1] for r in c.execute("pragma s.table_info(cookies)")}
            if set(cols) != scols or not set(KEY) <= scols:
                log(f"schema differs: {src} → {dst}; skipped")   # a Chrome update changed the table
                return 0
            collist = ", ".join(cols)
            same = " and ".join(f"d.{k} = x.{k}" for k in KEY)
            g = GOOGLE_COOKIES.replace("host_key", "x.host_key")
            newer_than_base = ""
            if base:
                c.execute("attach database ? as b", (str(base),))
                newer_than_base = (f"and not exists (select 1 from b.cookies d where {same} "
                                   f"and d.last_update_utc >= x.last_update_utc)")
            before = c.total_changes
            c.execute(f"""insert or replace into main.cookies ({collist})
                          select {", ".join("x." + k for k in cols)} from s.cookies x
                          where not ({g}) and (x.has_expires = 0 or x.expires_utc > ?)
                            and not exists (select 1 from main.cookies d where {same}
                                            and d.last_update_utc >= x.last_update_utc)
                            {newer_than_base}""", (_chrome_now(),))
            c.commit()
            return c.total_changes - before
        finally:
            c.close()


def _clone(src: str, dst_dir: Path) -> None:
    """Copy-on-write copy (APFS clonefile on macOS, reflink where the Linux fs supports it)."""
    flag = ["-c"] if sys.platform == "darwin" else ["--reflink=auto"]
    subprocess.run(["cp", "-a", *flag, src, str(dst_dir)], check=True)


def copy_profile(src: Path, dst: Path) -> None:
    """Clone src into a fresh dst (metadata only on APFS), minus caches, locks and open tabs."""
    (dst / "Default").mkdir(parents=True)
    for entry in os.scandir(src):
        if entry.name in SEED_SKIP_TOP:
            continue
        if entry.name == "Default":
            for sub in os.scandir(entry.path):
                if sub.name in SEED_SKIP_DEFAULT:
                    continue
                if sub.name in ("Service Worker", "IndexedDB"):
                    (dst / "Default" / sub.name).mkdir()
                    for leaf in os.scandir(sub.path):
                        rel = f"{sub.name}/{leaf.name}"
                        if rel in SEED_SKIP_PATHS or any(Path(rel).match(g) for g in SEED_SKIP_GLOBS):
                            continue
                        _clone(leaf.path, dst / "Default" / sub.name)
                    continue
                _clone(sub.path, dst / "Default")
        else:
            _clone(entry.path, dst)
    # leveldb stores (Local Storage, IndexedDB…) carry their own LOCK files: drop the copied ones
    for lock in dst.rglob("LOCK"):
        if lock.is_file() and lock.stat().st_size == 0:
            lock.unlink()


def keep_own_google(new: Path, old: Path) -> None:
    """In the fresh copy `new`, swap the master's Google cookies for the old copy's own (if any)."""
    db = new / "Default" / "Cookies"
    if not db.exists():
        return
    c = sqlite3.connect(db)
    try:
        c.execute(f"delete from cookies where {GOOGLE_COOKIES}")
        own = old / "Default" / "Cookies"
        if own.exists():
            c.execute("attach database ? as own", (str(own),))
            try:
                c.execute(f"insert or replace into cookies select * from own.cookies where {GOOGLE_COOKIES}")
            except sqlite3.Error:
                pass                         # schema changed with a Chrome update: the copy starts without Google
        c.commit()
    finally:
        c.close()


# ---------- module API (contract) ----------

def acquire(holder: str, name: str | None = None, *, any_: bool = False) -> Lease:
    return Pool().acquire(holder, name, any_=any_)


def acquire_any(holder: str) -> Lease:
    return Pool().acquire_any(holder)


def release(holder: str | None, name: str = MASTER, *, force: bool = False) -> int | None:
    return Pool().release(holder, name, force=force)


def held() -> dict[str, dict]:
    return Pool().held()


def reap_idle(now: int | None = None) -> list[str]:
    return Pool().reap_idle(now)


def seed(names: list[str] | None = None) -> dict[str, str | None]:
    return Pool().seed(names)


def sync(names: list[str] | None = None) -> dict[str, str]:
    return Pool().sync(names)


# ---------- CLI ----------

def _me(a) -> str | None:
    return getattr(a, "holder", None) or os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("AGTERM_SESSION_ID")


def _run(a, pool: Pool) -> int:
    b = pool.normalize(getattr(a, "browser", None) or MASTER)
    cmd = a.cmd or "status"
    if cmd == "hook":
        return pool.hook(a.phase, json.load(sys.stdin))
    if cmd == "reaper":
        pool.reaper(pool.normalize(a.target))
        return 0
    if cmd == "reap":
        for x in pool.reap_idle():
            print(f"{x}: released")
        return 0
    if cmd == "which":                       # for scripts: the browser name of a profile path
        print(pool.by_profile(a.path) or "")
        return 0
    if cmd == "pool":
        for x in pool.browsers:
            st = pool.state(x)
            age = "master" if x == MASTER else (
                f"seeded {(pool.clock() - st.seeded_at()) / 3600:.1f}h ago" if st.seeded_at() else "never seeded")
            print(f"{x:11} :{pool.s.mcp_port(x)}  {age:20} {pool.status_line(x)}")
        return 0
    if cmd == "seed":
        if a.stale is not None:
            targets = pool.stale(a.stale or None)
        elif a.all:
            targets = pool.pool
        elif a.targets:
            targets = [pool.normalize(t) for t in a.targets]
        else:
            print("usage: pw-identity seed <x|identity-x|--all|--stale [hours]>", file=sys.stderr)
            return 2
        rc = 0
        for x in targets:
            t0 = time.monotonic()
            err = pool.seed([x])[x]
            if err:
                print(f"{x}: not seeded — {err}")
                rc = 1
            else:
                print(f"{x}: seeded from the master in {time.monotonic() - t0:.1f}s")
        return rc
    if cmd == "sync":
        targets = None if not a.targets or a.targets == ["--all"] else a.targets
        for x, msg in pool.sync(targets).items():
            print(f"{x}: {msg}")
        return 0
    if cmd == "acquire":
        lease = pool.acquire(a.name, b, any_=a.any, pool_only=a.pool)
        print(f"acquired {lease.name} for {a.name}")
        print(lease.profile)
        return 0
    if cmd == "status":
        print(pool.status_line(b))
        h, me = pool.state(b).holder, _me(a)
        if pool.chrome_pid(b) and h and h["session"] != me and not owned_outside(h):
            return 1
        return 0
    if cmd == "release":
        pid = pool.release(_me(a), b, force=a.force)
        print(f"released: chrome pid {pid}" if pid else "free")
        return 0
    if cmd == "login":
        pool.login(b, a.urls, force=a.force)
        print('login window open — sign in, tick "keep me signed in", then quit that Chrome window (Cmd-Q)')
        return 0
    if cmd == "restart":
        if not a.dry_run:
            with contextlib.suppress(LeaseBusy):
                pool.release(_me(a), b, force=a.force)
        print(("would run: " if a.dry_run else "") + " ".join(pool.restart_server(b, dry_run=a.dry_run)))
        return 0
    raise AssertionError(cmd)


def _parser(prog: str = "pw-identity") -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-b", "--browser", default=argparse.SUPPRESS, help="identity | identity-<x> | <x>")
    ap = argparse.ArgumentParser(prog=prog, parents=[common], description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_commands(ap.add_subparsers(dest="cmd"), common)
    return ap


def _add_commands(sub, common) -> None:
    sub.add_parser("status", parents=[common], help="free | held by …")
    sub.add_parser("pool", parents=[common], help="every identity browser + seed age")
    p = sub.add_parser("release", parents=[common], help="close it now (own / idle holder)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--holder", help="release as this holder (default: this session)")
    p = sub.add_parser("login", parents=[common], help="plain Chrome on the profile for manual sign-in")
    p.add_argument("urls", nargs="*")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("acquire", parents=[common], help="hold a browser for a script's own Chrome")
    p.add_argument("name")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--any", action="store_true", help="a free copy, else the master, else an idle-held copy")
    g.add_argument("--pool", action="store_true", help="copies only")
    p = sub.add_parser("seed", help="copy the master onto pool browser(s), minus Google")
    p.add_argument("targets", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--stale", nargs="?", type=float, const=0.0, default=None, metavar="HOURS")
    p = sub.add_parser("sync", help="run the cookie sync now (closed browsers only)")
    p.add_argument("targets", nargs="*")
    sub.add_parser("reap", help="one pass: release idle holds")
    p = sub.add_parser("restart", parents=[common], help="close its Chrome, kickstart its carhunt.* MCP job")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("hook", help="Claude Code hook (reads the event JSON on stdin)")
    p.add_argument("phase", choices=["pre", "post"])
    p = sub.add_parser("reaper", help=argparse.SUPPRESS)
    p.add_argument("target")
    p = sub.add_parser("which", help="browser name of a profile path")
    p.add_argument("path")


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    pool = Pool()
    try:
        return _run(a, pool)
    except LeaseBusy as e:
        print(str(e), file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"pw-identity: {e}", file=sys.stderr)
        return 2


def register_cli(sub) -> None:
    """`carhunt browser identity …` = pw-identity …; sets func(args) -> int."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-b", "--browser", default=argparse.SUPPRESS, help="identity | identity-<x> | <x>")
    p = sub.add_parser("identity", parents=[common], help="identity browsers: leases, pool, seed, login")
    _add_commands(p.add_subparsers(dest="cmd"), common)

    def func(a) -> int:
        try:
            return _run(a, Pool())
        except LeaseBusy as e:
            print(str(e), file=sys.stderr)
            return 1
    p.set_defaults(func=func)


if __name__ == "__main__":
    sys.exit(main())
