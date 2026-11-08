"""Night pause + learning loop.

pause (night): PAUSE + each agent writes lessons/<date>.md · learning: one session reads the
day's lessons, edits only the user's local learned rules, proposes repo/hard-rule changes as
A/B/C for the morning digest · unpause (morning): agents re-read what changed.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path

from carhunt.core import clock, paths

from . import launch, msg, pause, state
from .session import Backend

LEARNING = "learning"


def _live_roles(backend: Backend) -> list[str]:
    out = []
    for role in state.roles():
        d = state.read(role)
        sid = d.get("active_agent")
        if role != LEARNING and d.get("status") == "running" and sid and backend.alive(sid):
            out.append(role)
    return out


def night(backend: Backend, config: Mapping | None = None) -> list[str]:
    """PAUSE + ask every live agent for its lessons. Returns the roles asked."""
    pause.pause("night pause", by="schedule", config=config)
    day = clock.now().date().isoformat()
    tmpl = launch.templates_dir() / "lessons.md"
    asked = []
    for role in _live_roles(backend):
        f = paths.agent_dir(role) / "lessons" / f"{day}.md"
        msg.send(role, f"Night pause is on (no sends). Finish the current step, then write {f} in the "
                 f"format of {tmpl} (≤30 lines, evidence for each line). Then arm your background wait "
                 "and stop. Seller replies that arrive now wait for the morning.",
                 backend=backend, sender="schedule")
        asked.append(role)
    return asked


def start(backend: Backend, config: Mapping | None = None) -> str:
    return launch.launch(LEARNING, backend=backend, config=config)


def collect(day: str | None = None, config: Mapping | None = None) -> dict[str, list[str]]:
    """Inputs for the learning session (paths only; it reads them itself)."""
    day = day or clock.now().date().isoformat()
    out: dict[str, list[str]] = {"lessons": [], "logs": [], "digest_inputs": []}
    for role in state.roles():
        d = paths.agent_dir(role)
        for key, p in (("lessons", d / "lessons" / f"{day}.md"), ("logs", d / "log.md"),
                       ("digest_inputs", d / "digest-input.md")):
            if p.is_file():
                out[key].append(str(p))
    return out


def day_file(day: str) -> Path:
    return paths.agent_dir(LEARNING) / "days" / f"{day}.md"


def morning(backend: Backend, config: Mapping | None = None) -> list[str]:
    """Remove PAUSE and point each live agent at last night's changes."""
    pause.unpause(by="schedule")
    yday = (clock.now().date() - timedelta(days=1)).isoformat()
    f = day_file(yday)
    told = []
    for role in _live_roles(backend):
        note = (f"Re-read the sections listed under 'Lessons applied' in {f} that touch "
                f"{paths.home() / 'learned' / (role + '.md')} or learned/common.md."
                if f.is_file() else "No learning changes last night.")
        msg.send(role, f"Unpaused, sends allowed again. {note}", backend=backend, sender="schedule")
        told.append(role)
    return told
