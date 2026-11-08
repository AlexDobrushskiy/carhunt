"""Agent Chrome: executable lookup, launch flags, pid records of the browsers carhunt starts.

Every Chrome we launch writes a pid record under $CARHUNT_HOME/browsers/run/; browser-reaper kills
only recorded pids (never by name pattern: a sweep subagent's pkill once killed another agent's search, 11-03).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from carhunt.access import settings as _settings

REPO = Path(__file__).resolve().parents[2]
AGENT_CHROME_BIN = REPO / "browsers" / "bin" / "agent-chrome"


def agent_chrome_path(*, update: bool = True) -> Path:
    """Executable of the re-signed Chrome clone (built/refreshed by browsers/bin/agent-chrome).

    `CARHUNT_CHROME` overrides (tests, Linux). Never /Applications/Google Chrome.app directly:
    macOS takes the agent process for the user's Chrome (Dock click activates it, Quit fails, 10-16).
    """
    if os.environ.get("CARHUNT_CHROME"):
        return Path(os.environ["CARHUNT_CHROME"])
    args = [str(AGENT_CHROME_BIN)] + ([] if update else ["--no-update"])
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.strip().splitlines()
    return Path(out[-1])


def launch_args(profile: Path | None, debug_port: int | None, *, headless: bool = False,
                extra: list[str] | None = None) -> list[str]:
    """Chrome flags for a person-like launch (no automation flags; attach later over the debug port)."""
    args = ["--no-first-run", "--no-default-browser-check",
            # without these a launch on a persistent profile wiped every login (10-25)
            "--use-mock-keychain", "--password-store=basic"]
    if profile is not None:
        args.append(f"--user-data-dir={profile}")
    if debug_port:
        args += [f"--remote-debugging-port={debug_port}", "--remote-debugging-address=127.0.0.1"]
    if headless:
        args.append("--headless=new")
    return args + (extra or [])


@dataclass
class PidRecord:
    pid: int
    kind: str            # lane | identity | plain | geo | test
    profile: str | None  # user-data-dir the process must still carry (pid-reuse guard)
    debug_port: int | None
    started_at: float
    owner: str           # holder / agent id / tool name


def write_pid_record(pid: int, kind: str, *, profile: Path | None, debug_port: int | None,
                     owner: str = "") -> Path:
    s = _settings.load()
    rec = PidRecord(pid, kind, str(profile) if profile else None, debug_port, time.time(),
                    owner or os.environ.get("AGTERM_SESSION_ID", "") or f"pid{os.getpid()}")
    p = s.run_dir / f"{pid}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(rec)))
    tmp.replace(p)
    return p


def read_pid_records() -> list[PidRecord]:
    out = []
    for f in sorted(_settings.load().run_dir.glob("*.json")):
        try:
            out.append(PidRecord(**json.loads(f.read_text())))
        except (OSError, ValueError, TypeError):
            continue
    return out


def drop_pid_record(pid: int) -> None:
    (_settings.load().run_dir / f"{pid}.json").unlink(missing_ok=True)
