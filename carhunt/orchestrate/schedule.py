"""`carhunt schedule install|uninstall|show`: launchd jobs from `orchestrate.schedule`.

The day runs on launchd, not on the overseer's loop: a blocking prompt in the overseer must not
stall sweep, unpause and digest.
"""
from __future__ import annotations

import os
import plistlib
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from carhunt.core import paths

from . import settings

PREFIX = "carhunt."
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CLEANUP_EVERY_S = 30 * 60

# job → carhunt argv; digests get a slot each (first time = morning, later = evening)
COMMANDS = {
    "sweep": ["agent", "launch", "sweep"],
    "unpause": ["unpause", "--morning"],
    "pause": ["pause", "--night"],
    "learning": ["learn", "start"],
}


class ScheduleError(RuntimeError):
    pass


def _times(v: object) -> list[str]:
    items = v if isinstance(v, list) else [v]
    out = []
    for t in items:
        if not isinstance(t, str) or not HHMM.match(t.strip()):
            raise ScheduleError(f"bad time {t!r} (HH:MM)")
        out.append(t.strip())
    return out


def jobs(config: Mapping) -> list[dict]:
    """[{label, argv, times[] | interval}] from config; empty/null entries are skipped."""
    sched = settings.get(config, "orchestrate.schedule", {}) or {}
    overrides = settings.get(config, "orchestrate.schedule_commands", {}) or {}
    out = []
    for job, when in sched.items():
        if not when:
            continue
        times = _times(when)
        if job == "digest":
            for i, t in enumerate(times):
                slot = "morning" if i == 0 else "evening"
                out.append({"label": f"{PREFIX}digest-{slot}", "argv": ["digest", "--slot", slot],
                            "times": [t]})
            continue
        argv = overrides.get(job) or COMMANDS.get(job)
        if not argv:
            raise ScheduleError(f"no command for schedule job {job!r}; set orchestrate.schedule_commands.{job}")
        out.append({"label": f"{PREFIX}{job}", "argv": list(argv), "times": times})
    out.append({"label": f"{PREFIX}cleanup", "argv": ["state", "cleanup"], "interval": CLEANUP_EVERY_S})
    return out


def carhunt_exe() -> str:
    return shutil.which("carhunt") or str(Path(sys.executable).with_name("carhunt"))


def plist(job: Mapping, *, exe: str, home: Path, path_env: str) -> dict:
    logs = home / "logs" / "schedule"
    d: dict = {
        "Label": job["label"],
        "ProgramArguments": [exe, *job["argv"]],
        "EnvironmentVariables": {"CARHUNT_HOME": str(home), "PATH": path_env},
        "StandardOutPath": str(logs / f"{job['label']}.log"),
        "StandardErrorPath": str(logs / f"{job['label']}.log"),
        "RunAtLoad": False,
    }
    if os.environ.get("CARHUNT_CONFIG"):
        d["EnvironmentVariables"]["CARHUNT_CONFIG"] = os.environ["CARHUNT_CONFIG"]
    if "interval" in job:
        d["StartInterval"] = int(job["interval"])
    else:
        cal = [{"Hour": int(t.split(":")[0]), "Minute": int(t.split(":")[1])} for t in job["times"]]
        d["StartCalendarInterval"] = cal[0] if len(cal) == 1 else cal
    return d


def agents_dir() -> Path:
    return Path(os.environ.get("CARHUNT_LAUNCHAGENTS_DIR") or "~/Library/LaunchAgents").expanduser()


def render_all(config: Mapping, *, exe: str | None = None) -> dict[str, bytes]:
    home = paths.home()
    path_env = os.pathsep.join(dict.fromkeys(
        [str(Path(exe or carhunt_exe()).parent), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin",
         "/usr/sbin", "/sbin"]))
    return {j["label"]: plistlib.dumps(plist(j, exe=exe or carhunt_exe(), home=home, path_env=path_env))
            for j in jobs(config)}


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def installed() -> list[Path]:
    d = agents_dir()
    return sorted(d.glob(f"{PREFIX}*.plist")) if d.is_dir() else []


def install(config: Mapping, *, load: bool = True, exe: str | None = None) -> list[Path]:
    """Write plists (replacing old carhunt.* ones) and load them into the user's GUI domain."""
    uninstall(unload=load)
    d = agents_dir()
    d.mkdir(parents=True, exist_ok=True)
    (paths.home() / "logs" / "schedule").mkdir(parents=True, exist_ok=True)
    written = []
    for label, data in render_all(config, exe=exe).items():
        p = d / f"{label}.plist"
        p.write_bytes(data)
        written.append(p)
        if load:
            res = _launchctl("bootstrap", f"gui/{os.getuid()}", str(p))
            if res.returncode != 0:
                raise ScheduleError(f"launchctl bootstrap {label}: {(res.stderr or res.stdout).strip()}")
    return written


def uninstall(*, unload: bool = True) -> list[Path]:
    removed = []
    for p in installed():
        if unload:
            _launchctl("bootout", f"gui/{os.getuid()}/{p.stem}")
        p.unlink()
        removed.append(p)
    return removed


def show(config: Mapping) -> list[str]:
    on_disk = {p.stem for p in installed()}
    lines = []
    for j in jobs(config):
        when = f"every {j['interval'] // 60} min" if "interval" in j else ", ".join(j["times"])
        mark = "installed" if j["label"] in on_disk else "not installed"
        lines.append(f"{j['label']:<24} {when:<14} carhunt {' '.join(j['argv'])}  [{mark}]")
    return lines
