"""browser-reaper kills only recorded, profile-matching, orphaned-or-old pids — on dummy sleep processes."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from carhunt.access import chrome, reaper

SLEEP = "import time; time.sleep(120)"


@pytest.fixture
def spawn(tmp_path, carhunt_home):
    pids: list[int] = []

    def _spawn(profile, *, orphan=False, exe=sys.executable):
        argv = [str(exe), "-c", SLEEP, f"--user-data-dir={profile}"]
        if orphan:  # parent exits at once → reparented to launchd/init, like a leaked browser
            out = subprocess.run(["sh", "-c", '"$@" >/dev/null 2>&1 & echo $!', "sh", *argv],
                                 capture_output=True, text=True, check=True).stdout
            pid = int(out.strip())
        else:
            pid = subprocess.Popen(argv).pid
        pids.append(pid)
        _wait_visible(pid)
        return pid

    yield _spawn
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


def _wait_visible(pid):
    for _ in range(50):
        if pid in reaper.processes():
            return
        time.sleep(0.05)


def _gone(pid):
    try:
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return True
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


def _by_pid(rows):
    return {p.pid: p for p in rows}


def test_old_recorded_is_killed_and_record_dropped(spawn, tmp_path):
    prof = tmp_path / "lane-1"
    pid = spawn(prof)
    chrome.write_pid_record(pid, "lane", profile=prof, debug_port=None, owner=f"pid{os.getpid()}")
    time.sleep(1.2)
    assert _by_pid(reaper.scan(max_age_h=1e-4))[pid].action == "kill"
    victims = reaper.reap(dry_run=False, max_age_h=1e-4)
    assert [p.pid for p in victims] == [pid]
    assert victims[0].result in ("terminated", "killed")
    assert _gone(pid)
    assert pid not in {r.pid for r in chrome.read_pid_records()}


def test_young_child_of_live_launcher_is_left(spawn, tmp_path):
    prof = tmp_path / "lane-2"
    pid = spawn(prof)
    chrome.write_pid_record(pid, "lane", profile=prof, debug_port=None)
    assert _by_pid(reaper.scan())[pid].action == "leave"
    assert reaper.reap(dry_run=False) == []
    assert not _gone(pid)


def test_orphan_without_holder_is_killed_but_leased_orphan_is_left(spawn, tmp_path, carhunt_home):
    free, leased = tmp_path / "lane-3", tmp_path / "identity-x"
    p_free, p_leased = spawn(free, orphan=True), spawn(leased, orphan=True)
    assert reaper.processes()[p_free].ppid == 1
    chrome.write_pid_record(p_free, "lane", profile=free, debug_port=None, owner="pid999999")
    chrome.write_pid_record(p_leased, "identity", profile=leased, debug_port=None, owner="agent-x")
    leases = carhunt_home / "browsers" / "leases"
    leases.mkdir(parents=True, exist_ok=True)
    (leases / "identity-x.json").write_text(json.dumps({"profile": str(leased), "holder": "agent-x"}))
    rows = _by_pid(reaper.scan())
    assert rows[p_free].action == "kill" and "orphaned" in rows[p_free].why
    assert rows[p_leased].action == "leave"
    assert [p.pid for p in reaper.reap(dry_run=False)] == [p_free]
    for _ in range(25):
        if _gone(p_free):
            break
        time.sleep(0.2)
    assert _gone(p_free) and not _gone(p_leased)


def test_pid_reuse_guard_leaves_mismatched_cmdline(spawn, tmp_path):
    pid = spawn(tmp_path / "actual")
    chrome.write_pid_record(pid, "lane", profile=tmp_path / "recorded", debug_port=None)
    time.sleep(1.2)
    row = _by_pid(reaper.scan(max_age_h=1e-4))[pid]
    assert row.action == "leave" and "pid reused" in row.why
    assert reaper.reap(dry_run=False, max_age_h=1e-4) == []
    assert not _gone(pid)


def test_unrecorded_is_never_killed_and_listed_as_not_ours(spawn, tmp_path):
    fake_chrome = tmp_path / "Google Chrome"  # argv[0] looks like a Chrome main process
    fake_chrome.symlink_to(sys.executable)
    pid = spawn(tmp_path / "someone-elses", orphan=True, exe=fake_chrome)
    time.sleep(1.2)
    row = _by_pid(reaper.scan(max_age_h=1e-4))[pid]
    assert row.action == "not-ours"
    assert pid not in [p.pid for p in reaper.reap(dry_run=False, max_age_h=1e-4)]
    assert not _gone(pid)


def test_dry_run_kills_nothing_and_drops_dead_records(spawn, tmp_path, capsys):
    prof = tmp_path / "lane-4"
    pid = spawn(prof, orphan=True)
    chrome.write_pid_record(pid, "lane", profile=prof, debug_port=None, owner="pid999999")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    chrome.write_pid_record(dead.pid, "lane", profile=tmp_path / "x", debug_port=None)
    assert reaper.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "WOULD KILL" in out and f"pid={pid}" in out
    assert not _gone(pid)
    assert {r.pid for r in chrome.read_pid_records()} == {pid}
    assert [p.pid for p in reaper.reap(dry_run=True)] == [pid]
    assert not _gone(pid)
