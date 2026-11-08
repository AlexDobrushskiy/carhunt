"""PAUSE file: while it exists every sender refuses. Only the owner or the schedule removes it.

Agents never unpause themselves.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from carhunt.core import clock, paths

from . import settings


class Paused(RuntimeError):
    pass


def paused() -> bool:
    return paths.pause_file().exists()


def info() -> dict | None:
    p = paths.pause_file()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text() or "{}")
    except ValueError:
        return {"reason": p.read_text().strip()}


def pause(reason: str = "", by: str | None = None, config: Mapping | None = None) -> dict:
    p = paths.pause_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"since": clock.now().isoformat(timespec="seconds"),
            "by": by or settings.self_role() or "owner", "reason": reason}
    p.write_text(json.dumps(data) + "\n")
    return data


def unpause(by: str | None = None) -> bool:
    """Remove PAUSE. Refused inside an agent session (CARHUNT_AGENT set) unless it is the schedule."""
    who = by or settings.self_role()
    if who and who not in ("owner", "schedule"):
        raise Paused(f"agent {who!r} may not unpause; only the owner or the schedule does")
    p = paths.pause_file()
    if p.exists():
        p.unlink()
        return True
    return False


def guard() -> None:
    """Call before any outward action (send, signup, purchase step)."""
    if paused():
        i = info() or {}
        raise Paused(f"paused since {i.get('since', '?')} by {i.get('by', '?')}: {i.get('reason', '')}".rstrip(": "))
