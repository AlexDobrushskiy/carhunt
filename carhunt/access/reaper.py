"""browser-reaper — close leaked browsers that carhunt started, and nothing else.

Kills a process only if ALL hold:
  1. it has a pid record in `run/` (written at launch by every carhunt browser);
  2. its current command line still carries the recorded profile dir (pid reuse: the number may now
     belong to someone else's process);
  3. it is orphaned (parent is launchd/init) with no live holder, or older than `reaper_max_age_h`.
Never by name pattern (a sweep subagent's pkill once killed another agent's search, 11-03); unrecorded
Chromes (the owner's own browser, other tools') are listed as "not ours" and left alone. Records whose pid
is gone are dropped.

  browser-reaper [--dry-run] [--max-age H] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from carhunt.access import chrome
from carhunt.access import settings as _settings

BROWSER_RE = re.compile(r"(Google Chrome|Chromium|chrome-headless-shell|headless_shell|/chrome)(\s|$)")


@dataclass
class Proc:
    pid: int
    ppid: int
    age_s: int
    args: str
    record: dict | None = None
    action: str = "leave"      # kill | leave | not-ours
    why: str = ""
    result: str = field(default="")

    def row(self) -> dict:
        d = asdict(self)
        d["profile"] = (self.record or {}).get("profile") or _profile_arg(self.args)
        d["age_h"] = round(self.age_s / 3600, 2)
        d.pop("args")
        return d


def etime_to_s(e: str) -> int:
    days = 0
    if "-" in e:
        d, e = e.split("-", 1)
        days = int(d)
    parts = [int(x) for x in e.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def processes() -> dict[int, Proc]:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,etime=,args="], capture_output=True, text=True).stdout
    procs = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(\S+)\s+(.*)", line)
        if m:
            procs[int(m[1])] = Proc(int(m[1]), int(m[2]), etime_to_s(m[3]), m[4])
    return procs


def _profile_arg(args: str) -> str | None:
    m = re.search(r"--user-data-dir[= ](\S+)", args)
    return m[1] if m else None


def _init_like(pid: int, procs: dict[int, Proc]) -> bool:
    if pid <= 1:
        return True
    p = procs.get(pid)
    if p is None:
        return True
    return bool(re.search(r"(^|/)(launchd|systemd)(\s|$)|systemd --user", p.args))


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _owner_pid(owner: str) -> int | None:
    m = re.fullmatch(r"pid(\d+)", owner or "")
    return int(m[1]) if m else None


def _held(rec: dict, s: _settings.Settings) -> tuple[bool, str]:
    """Is someone still using this browser? Unknown holders count as alive (only the age limit applies)."""
    profile = rec.get("profile")
    side = s.root / "plain-state" / f"{rec.get('debug_port')}.json"
    if rec.get("kind") == "plain" and side.exists():
        try:
            holders = json.loads(side.read_text()).get("holders", {})
        except (OSError, ValueError):
            holders = {}
        for h in holders.values():
            if h is None:
                return True, "plain-chrome tab with an untracked holder (CLI open)"
            if _pid_alive(int(h)):
                return True, f"plain-chrome tab held by pid {h}"
        return False, "plain-chrome: no live tab holder"
    for f in s.leases_dir.glob("*.json"):  # identity / geo leases name the profile they hold
        try:
            lease = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if profile and lease.get("profile") and Path(lease["profile"]) == Path(profile):
            return True, f"leased ({f.stem})"
    op = _owner_pid(rec.get("owner", ""))
    if op is not None:
        return (True, f"owner pid {op} alive") if _pid_alive(op) else (False, f"owner pid {op} gone")
    if rec.get("kind") in ("plain", "geo"):  # launched detached on purpose (parent is launchd from the start)
        return True, "detached launch, holder not checkable"
    return False, "no lease or live owner"


def _matches(proc: Proc, rec: dict) -> bool:
    """Pid-reuse guard: the live process must still carry the recorded profile (or debug port)."""
    if rec.get("profile"):
        a = proc.args
        p = rec["profile"]
        return f"--user-data-dir={p}" in a or f"--user-data-dir {p}" in a
    if rec.get("debug_port"):
        return f"--remote-debugging-port={rec['debug_port']}" in proc.args
    return False


def scan(max_age_h: float | None = None) -> list[Proc]:
    """Classify recorded browsers (kill/leave) and unrecorded Chrome mains (not-ours). Drops records of dead pids."""
    s = _settings.load()
    max_age_s = (s.reaper_max_age_h if max_age_h is None else max_age_h) * 3600
    procs = processes()
    out: list[Proc] = []
    recorded: set[int] = set()
    for f in sorted(s.run_dir.glob("*.json")):
        try:
            rec = json.loads(f.read_text())
            pid = int(rec["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        recorded.add(pid)
        proc = procs.get(pid)
        if proc is None:
            chrome.drop_pid_record(pid)
            continue
        proc.record = rec
        out.append(proc)
        if not _matches(proc, rec):
            proc.why = "pid reused: command line no longer carries the recorded profile"
            continue
        held, hwhy = _held(rec, s)
        if proc.age_s > max_age_s:
            proc.action, proc.why = "kill", f"older than {max_age_s / 3600:g} h ({hwhy})"
        elif _init_like(proc.ppid, procs) and not held:
            proc.action, proc.why = "kill", f"orphaned: launcher gone, {hwhy}"
        else:
            proc.why = hwhy if held else "launcher still alive"
    for proc in procs.values():
        if proc.pid in recorded or "--type=" in proc.args:
            continue
        exe = proc.args.split(" --")[0].split(" http")[0]
        if not BROWSER_RE.search(exe) or "crashpad" in exe:
            continue
        parent = procs.get(proc.ppid)
        if parent and BROWSER_RE.search(parent.args.split(" --")[0]) and "--type=" not in parent.args:
            continue  # child of another browser main
        proc.action, proc.why = "not-ours", "no carhunt pid record: left alone"
        out.append(proc)
    return out


def _kill(pid: int) -> str:
    """SIGTERM (Chrome quits cleanly and flushes cookies), SIGKILL after 5 s."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    for _ in range(25):
        time.sleep(0.2)
        try:  # reap if it is our own child (tests), else it stays a zombie
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return "terminated"
        except ChildProcessError:
            pass
        if not _pid_alive(pid):
            return "terminated"
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "terminated"
    return "killed"


def reap(dry_run: bool = True, max_age_h: float | None = None) -> list[Proc]:
    """Kill the leaks scan() marks; returns them (with `result`). dry_run kills nothing."""
    s = _settings.load()
    victims = [p for p in scan(max_age_h) if p.action == "kill"]
    if dry_run:
        return victims
    for p in victims:
        p.result = _kill(p.pid)
        chrome.drop_pid_record(p.pid)
        with open(s.logs / "reaper.log", "a") as fh:
            fh.write(f"{time.strftime('%F %T')} {p.result} pid={p.pid} kind={p.record.get('kind')} "
                     f"age_h={p.age_s / 3600:.1f} {p.record.get('profile')} [{p.why}]\n")
    if any((p.record or {}).get("kind") == "plain" for p in victims):
        from carhunt.access import plainchrome
        plainchrome.cleanup_dead()  # jar export + temp profile removal for reaped plain-chromes
    return victims


def _print(rows: list[Proc], dry_run: bool) -> None:
    for p in rows:
        tag = p.result or ("WOULD KILL" if p.action == "kill" and dry_run else p.action)
        r = p.row()
        print(f"{tag:11} pid={p.pid:<8} age={r['age_h']:>6}h  {r['profile'] or '-'}  [{p.why}]")


def _add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--dry-run", action="store_true", help="list what would be killed; kill nothing")
    ap.add_argument("--max-age", type=float, default=None, help="hours (default: settings reaper_max_age_h)")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=_run)


def _run(a: argparse.Namespace) -> int:
    all_rows = scan(a.max_age)
    if not a.dry_run:
        killed = {p.pid: p for p in reap(dry_run=False, max_age_h=a.max_age)}
        all_rows = [killed.get(p.pid, p) for p in all_rows]
    if a.json:
        print(json.dumps([p.row() for p in all_rows], indent=1))
    else:
        _print(all_rows, a.dry_run)
        if not all_rows:
            print("no browsers running")
    return 0


def register_cli(sub: Any) -> None:
    """`carhunt browser reap` under the browser group."""
    _add_args(sub.add_parser("reap", help="close leaked browsers carhunt started (pid records only)"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="browser-reaper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_args(ap)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
