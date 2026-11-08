"""Identity leases, idle release, pool choice, seed and cookie sync — temp dirs, fake Chrome processes."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from carhunt.access import identity
from carhunt.access.errors import LeaseBusy

REPO = Path(__file__).resolve().parents[3]
T0 = 1_800_000_000


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path / "carhunt"))
    monkeypatch.setenv("CARHUNT_IDENTITY_REAPER", "0")      # tests drive reap_idle() themselves
    monkeypatch.delenv("CARHUNT_CONFIG", raising=False)
    monkeypatch.delenv("CARHUNT_FAKE_NOW", raising=False)
    return tmp_path


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def pool(clock):
    return identity.Pool(clock=clock)


@pytest.fixture
def fake_chrome(tmp_path):
    """Start a process the pool's ps scan takes for Chrome on a profile (`…/chrome --user-data-dir=P`)."""
    exe = tmp_path / "fakebin" / "chrome"
    exe.parent.mkdir()
    exe.write_text("import time\ntime.sleep(600)\n")
    procs = []

    def start(profile: Path) -> subprocess.Popen:
        profile.mkdir(parents=True, exist_ok=True)
        p = subprocess.Popen([sys.executable, str(exe), f"--user-data-dir={profile}"])
        procs.append(p)
        deadline = time.time() + 5
        while os.path.realpath(profile) not in identity.chrome_pids():
            assert time.time() < deadline, "fake chrome not visible to ps"
            time.sleep(0.05)
        return p

    yield start
    for p in procs:
        if p.poll() is None:
            p.kill()
        p.wait()


def mark_seeded(pool, *names):
    for b in names:
        with pool.state(b) as st:
            st.put("seeded-at", str(pool.clock()))
        (pool.profile(b) / "Default").mkdir(parents=True, exist_ok=True)


def hook(pool, phase, session, tool="mcp__ch-identity-a__browser_snapshot", tid="t1", **inp):
    return pool.hook(phase, {"session_id": session, "tool_use_id": tid, "tool_name": tool,
                             "tool_input": inp, "cwd": "/w"})


# ---------- fake Chrome cookie DB ----------

COLS = ("creation_utc integer, host_key text, top_frame_site_key text, has_cross_site_ancestor integer, "
        "name text, value text, encrypted_value blob, path text, expires_utc integer, is_secure integer, "
        "has_expires integer, last_update_utc integer, source_scheme integer, source_port integer")


def cookie_db(path: Path, rows):
    """rows: (host, name, value, last_update_utc)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(f"create table if not exists cookies ({COLS})")
    c.execute("create unique index if not exists cookies_unique_index on cookies(host_key, top_frame_site_key, "
              "has_cross_site_ancestor, name, path, source_scheme, source_port)")
    for host, name, value, upd in rows:
        c.execute("insert or replace into cookies values (0, ?, '', 0, ?, ?, x'', '/', 0, 1, 0, ?, 2, 443)",
                  (host, name, value, upd))
    c.commit()
    c.close()


def cookies(path: Path) -> dict:
    c = sqlite3.connect(path)
    try:
        return {(h, n): v for h, n, v in c.execute("select host_key, name, value from cookies")}
    finally:
        c.close()


# ---------- leases ----------

def test_acquire_is_exclusive_and_lease_names_profile(pool):
    lease = pool.acquire("sweep", "identity")
    assert lease.name == "identity" and lease.mcp_port == 18932 and lease.debug_port == 19332
    with pytest.raises(LeaseBusy):
        pool.acquire("other", "identity")
    pool.acquire("sweep", "identity")                         # same script re-acquiring: fine
    summary = json.loads((pool.s.leases_dir / "identity.json").read_text())
    assert summary["profile"] == str(pool.profile("identity").resolve())   # browser-reaper spares it
    assert summary["session"] == "script:sweep"


def test_unseeded_copy_refused(pool):
    with pytest.raises(LeaseBusy, match="never seeded"):
        pool.acquire("s", "identity-a")


def test_any_prefers_free_copy_then_master(pool):
    mark_seeded(pool, "identity-a", "identity-b")
    assert pool.acquire("one", any_=True).name == "identity-a"
    assert pool.acquire("two", any_=True).name == "identity-b"
    assert pool.acquire("three", any_=True).name == "identity"       # master only when no copy is free
    with pytest.raises(LeaseBusy):
        pool.acquire("four", any_=True)


def _race(argv_list, env):
    procs = [subprocess.Popen([sys.executable, "-m", "carhunt.access.identity", *argv], env=env, cwd=REPO,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for argv in argv_list]
    return [(p.wait(30), p.stdout.read(), p.stderr.read()) for p in procs]


def test_two_processes_racing_for_one_browser(pool):
    mark_seeded(pool, "identity-a")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    for round_ in range(3):
        res = _race([["-b", "identity-a", "acquire", f"r{round_}-{i}"] for i in range(2)], env)
        assert sorted(rc for rc, _, _ in res) == [0, 1], res
        winner = next(out for rc, out, _ in res if rc == 0)
        assert winner.startswith("acquired identity-a for ")
        loser = next(err for rc, _, err in res if rc == 1)
        assert "busy" in loser
        with pool.state("identity-a") as st:                 # next round starts free
            st.clear()


def test_many_processes_any_get_distinct_browsers(pool):
    mark_seeded(pool, "identity-a", "identity-b")
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    res = _race([["acquire", f"p{i}", "--any"] for i in range(4)], env)
    got = [out.splitlines()[0].split()[1] for rc, out, _ in res if rc == 0]
    assert sorted(got) == ["identity", "identity-a", "identity-b"], res
    assert sum(rc == 1 for rc, _, _ in res) == 1


def test_release_by_non_holder_refused(pool, fake_chrome):
    mark_seeded(pool, "identity-a")
    pool.acquire("owner", "identity-a")
    p = fake_chrome(pool.profile("identity-a"))
    with pytest.raises(LeaseBusy):
        pool.release("intruder", "identity-a")
    with pytest.raises(LeaseBusy):
        pool.release(None, "identity-a")
    assert p.poll() is None
    assert pool.release("owner", "identity-a") == p.pid
    assert p.wait(5) is not None
    assert pool.state("identity-a").holder is None
    assert not (pool.s.leases_dir / "identity-a.json").exists()


def test_release_of_starting_script_hold_refused_for_others(pool):
    pool.acquire("owner", "identity")
    with pytest.raises(LeaseBusy):
        pool.release("intruder", "identity")
    assert pool.release("intruder", "identity", force=True) is None
    assert pool.state("identity").holder is None


# ---------- idle release (hooks + fake clock) ----------

def test_idle_release_with_fake_clock(pool, clock, fake_chrome):
    mark_seeded(pool, "identity-a")
    assert hook(pool, "pre", "sess-1", tool="mcp__ch-identity-a__browser_navigate", url="https://example.invalid/") == 0
    p = fake_chrome(pool.profile("identity-a"))           # the MCP server launched Chrome for the call
    assert hook(pool, "post", "sess-1", tool="mcp__ch-identity-a__browser_navigate") == 0
    clock.t += pool.ttl - 1
    assert pool.reap_idle() == []
    assert p.poll() is None
    clock.t += 1
    assert pool.reap_idle() == ["identity-a"]
    assert p.wait(5) is not None
    assert pool.state("identity-a").holder is None


def test_call_in_flight_is_never_reaped(pool, clock, fake_chrome):
    mark_seeded(pool, "identity-a")
    hook(pool, "pre", "sess-1")
    p = fake_chrome(pool.profile("identity-a"))
    clock.t += pool.ttl + 10                                # pre without post: a long call still running
    assert pool.reap_idle() == []
    assert p.poll() is None


def test_other_session_blocked_until_idle_then_takes_over(pool, clock, fake_chrome, capsys):
    mark_seeded(pool, "identity-a", "identity-b")
    hook(pool, "pre", "sess-1")
    p = fake_chrome(pool.profile("identity-a"))
    hook(pool, "post", "sess-1")
    assert hook(pool, "pre", "sess-2", tid="t2") == 2
    err = capsys.readouterr().err
    assert "held by session sess-1" in err and "mcp__ch-identity-b__" in err
    clock.t += pool.ttl
    assert hook(pool, "pre", "sess-2", tid="t2") == 0       # idle holder: closed and taken over
    assert p.wait(5) is not None
    assert pool.state("identity-a").holder["session"] == "sess-2"


def test_browser_close_ends_hold(pool, fake_chrome):
    hook(pool, "pre", "sess-1", tool="mcp__ch-identity__browser_close")
    fake_chrome(pool.profile("identity"))
    hook(pool, "post", "sess-1", tool="mcp__ch-identity__browser_close")
    assert pool.state("identity").holder is None


def test_google_blocked_on_copies_and_foreign_tools_ignored(pool, capsys):
    mark_seeded(pool, "identity-a")
    assert hook(pool, "pre", "s", tool="mcp__ch-identity-a__browser_navigate",
                url="https://accounts.google.com/x") == 2
    assert "master-only" in capsys.readouterr().err
    assert hook(pool, "pre", "s", tool="mcp__ch-identity__browser_navigate", url="https://mail.google.com/") == 0
    assert hook(pool, "pre", "s", tool="mcp__identity-a__browser_click") == 0     # another stack's server
    assert pool.state("identity-a").holder is None


def test_hook_cli_reads_stdin(pool, monkeypatch):
    mark_seeded(pool, "identity-a")
    ev = {"session_id": "s9", "tool_use_id": "t", "tool_name": "mcp__ch-identity-a__browser_snapshot"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(ev)))
    assert identity.main(["hook", "pre"]) == 0
    assert identity.Pool().state("identity-a").holder["session"] == "s9"


def test_script_hold_ends_after_grace_without_chrome(pool, clock):
    pool.acquire("slow", "identity")
    assert pool.reap_idle() == []                          # still within the launch grace
    clock.t += identity.ACQUIRE_GRACE
    assert pool.reap_idle() == ["identity"]


def test_restart_only_carhunt_labels(clock):
    calls = []
    pool = identity.Pool(clock=clock, launchctl=calls.append)
    cmd = pool.restart_server("identity-b")
    assert cmd[:3] == ["launchctl", "kickstart", "-k"] and cmd[3].endswith("/carhunt.identity-b")
    assert calls == [cmd]
    assert pool.restart_server("identity", dry_run=True) and len(calls) == 1


def test_restart_refuses_foreign_prefix(tmp_path, monkeypatch, clock):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("browsers:\n  launchd_prefix: com.someone.\n")
    monkeypatch.setenv("CARHUNT_CONFIG", str(cfg))
    calls = []
    with pytest.raises(ValueError):
        identity.Pool(clock=clock, launchctl=calls.append).restart_server("identity")
    assert calls == []


# ---------- seed + cookie sync ----------

def _master(pool, rows):
    m = pool.profile("identity")
    cookie_db(m / "Default" / "Cookies", rows)
    (m / "Default" / "Cache").mkdir()
    (m / "Default" / "Cache" / "blob").write_text("x")
    (m / "Default" / "Preferences").write_text("{}")
    (m / "Local State").write_text("{}")
    (m / "SingletonLock").write_text("")
    return m


def test_seed_copies_master_minus_google(pool):
    now = identity._chrome_now()
    _master(pool, [("accounts.google.com", "SID", "g", now), (".example.invalid", "sess", "m1", now)])
    old = pool.profile("identity-a")
    cookie_db(old / "Default" / "Cookies", [(".google.com", "OWN", "copy-own", now)])
    assert pool.seed(["identity-a"]) == {"identity-a": None}
    c = pool.profile("identity-a")
    ck = cookies(c / "Default" / "Cookies")
    assert ck[(".example.invalid", "sess")] == "m1"
    assert ("accounts.google.com", "SID") not in ck               # Google stays master-only
    assert ck[(".google.com", "OWN")] == "copy-own"               # the copy keeps its own Google login
    assert not (c / "Default" / "Cache").exists() and not (c / "SingletonLock").exists()
    assert (c / "Default" / "Preferences").exists()
    assert pool.state("identity-a").seeded_at() == pool.clock()
    assert pool.state("identity-a").holder is None
    assert pool.stale(1) == ["identity-b", "identity-c", "identity-d"]


def test_seed_refuses_busy_copy(pool, fake_chrome):
    _master(pool, [])
    mark_seeded(pool, "identity-a")
    pool.acquire("busy", "identity-a")
    fake_chrome(pool.profile("identity-a"))
    assert "busy" in pool.seed(["identity-a"])["identity-a"]


def test_two_way_sync_and_pending_store(pool, fake_chrome):
    now = identity._chrome_now()
    _master(pool, [(".site.invalid", "a", "old", now - 10)])
    pool.seed(["identity-a"])
    copy_db = pool.profile("identity-a") / "Default" / "Cookies"
    cookie_db(copy_db, [(".site.invalid", "a", "new", now), (".google.com", "X", "nope", now)])
    pool.sync(["identity-a"])                                     # copy closed → master (master down)
    m = cookies(pool.cookie_db("identity"))
    assert m[(".site.invalid", "a")] == "new" and (".google.com", "X") not in m
    # master running → the copy's newer cookie waits in the pending store
    cookie_db(copy_db, [(".site.invalid", "b", "later", now + 5)])
    master_chrome = fake_chrome(pool.profile("identity"))
    pool.sync(["identity-a"])
    assert (".site.invalid", "b") not in cookies(pool.cookie_db("identity"))
    assert (pool.s.leases_dir / "pending-cookies.db").exists()
    master_chrome.kill()
    master_chrome.wait()
    pool.sync(["identity"])                                       # master closed → pending applied
    assert cookies(pool.cookie_db("identity"))[(".site.invalid", "b")] == "later"
    assert not (pool.s.leases_dir / "pending-cookies.db").exists()
    # an older copy value never overwrites a newer master value
    cookie_db(pool.cookie_db("identity"), [(".site.invalid", "c", "master-new", now + 100)])
    cookie_db(copy_db, [(".site.invalid", "c", "copy-old", now + 50)])
    pool.sync(["identity-a"])
    assert cookies(pool.cookie_db("identity"))[(".site.invalid", "c")] == "master-new"
    assert cookies(copy_db)[(".site.invalid", "c")] == "master-new"   # and the pull brought it to the copy
