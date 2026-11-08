"""Agent state.json: read/write under a lock, schema-checked, plus the handover protocol.

Handover:
1. The old agent writes handover_notes — unanswered inbound replies listed explicitly — and
   spawns its successor with the same brief (`carhunt state handover`).
2. The successor rebuilds state from files, then `carhunt state takeover`: it becomes
   active_agent and closes the predecessor. The old session is closed only after this confirm.
3. `carhunt state cleanup` closes sessions whose state is completed.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from carhunt.core import clock, paths
from .session import Backend

HANDOVER_KEYS = ("open_threads", "unanswered_inbound", "pending_sends", "scheduled", "promises",
                 "cross_module")


class StateError(RuntimeError):
    pass


def schema_path() -> Path:
    return paths.repo_root() / "agents" / "state.schema.json"


def validate(state: Mapping) -> None:
    schema = json.loads(schema_path().read_text())
    try:
        import jsonschema
    except ImportError:  # minimal check without the dependency
        missing = [k for k in schema["required"] if k not in state]
        if missing:
            raise StateError(f"state.json missing {missing}")
        return
    try:
        jsonschema.validate(dict(state), schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise StateError(f"state.json invalid at {where}: {e.message}") from e


def path(role: str) -> Path:
    return paths.agent_dir(role) / "state.json"


def _stamp() -> str:
    return clock.now().isoformat(timespec="seconds")


def read(role: str) -> dict:
    p = path(role)
    if not p.is_file():
        raise StateError(f"no state for agent {role!r} ({p})")
    return json.loads(p.read_text())


@contextlib.contextmanager
def edit(role: str, create: bool = False) -> Iterator[dict]:
    """Locked read-modify-write; validates before the atomic replace."""
    p = path(role)
    with open(p.with_suffix(".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if p.is_file():
            data = json.loads(p.read_text())
        elif create:
            data = {"role": role, "active_agent": None, "status": "starting"}
        else:
            raise StateError(f"no state for agent {role!r} ({p})")
        yield data
        data["updated_at"] = _stamp()
        validate(data)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, p)


def roles() -> list[str]:
    root = paths.agents_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir() if (d / "state.json").is_file())


def _parse(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def get_key(data: Mapping, dotted: str | None) -> Any:
    if not dotted:
        return data
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise StateError(f"no key {dotted!r}")
    return cur


def _container(data: dict, dotted: str) -> tuple[dict, str]:
    parts = dotted.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if nxt is None:
            nxt = cur[part] = {}
        if not isinstance(nxt, dict):
            raise StateError(f"{part!r} is not an object")
        cur = nxt
    return cur, parts[-1]


def set_key(role: str, dotted: str, value: str | Any) -> None:
    if dotted in ("active_agent", "role"):
        raise StateError(f"{dotted} changes only through launch/takeover")
    with edit(role) as data:
        c, k = _container(data, dotted)
        c[k] = _parse(value) if isinstance(value, str) else value


def add_key(role: str, dotted: str, value: str | Any) -> None:
    with edit(role) as data:
        c, k = _container(data, dotted)
        lst = c.setdefault(k, [])
        if not isinstance(lst, list):
            raise StateError(f"{dotted!r} is not a list")
        lst.append(_parse(value) if isinstance(value, str) else value)


def init(role: str, *, active_agent: str | None, name: str, cli: str, brief: str) -> dict:
    with edit(role, create=True) as data:
        data.update(role=role, name=name, cli=cli, brief=brief, active_agent=active_agent,
                    status="running", started_at=_stamp(), handover_from=None, successor=None)
        for k in ("completed_at", "closed_at"):
            data.pop(k, None)
        data.setdefault("handover_notes", {})
        data.setdefault("pending_owner", [])
        data.setdefault("open_issues", [])
        data.setdefault("cursors", {})
        return dict(data)


def done(role: str, summary: str | None = None) -> None:
    with edit(role) as data:
        data["status"] = "completed"
        data["completed_at"] = _stamp()
        if summary:
            data["summary"] = summary


def _require_active(data: Mapping, me: str | None) -> None:
    if not me:
        raise StateError("own session id unknown (CARHUNT_SESSION_ID / AGTERM_SESSION_ID unset)")
    if data.get("active_agent") != me:
        raise StateError(f"you ({me}) are not the active agent of {data.get('role')} "
                         f"({data.get('active_agent')})")


def handover(role: str, notes: Mapping, *, me: str | None, backend: Backend,
             config: Mapping | None = None) -> str:
    """Write notes, spawn the successor with the same brief. Returns the successor's session id."""
    missing = [k for k in ("unanswered_inbound",) if k not in notes]
    if missing:
        raise StateError("handover notes must list unanswered_inbound explicitly ([] if none): an unlisted "
                         "seller reply goes unanswered after the handover")
    unknown = [k for k in notes if k not in HANDOVER_KEYS and k != "other"]
    if unknown:
        raise StateError(f"unknown handover_notes keys {unknown}; use {list(HANDOVER_KEYS)} or 'other'")
    with edit(role) as data:
        _require_active(data, me)
        data["handover_notes"] = {**(data.get("handover_notes") or {}), **notes}
        data["handover_from"] = me
    from . import launch
    sid = launch.launch(role, successor_of=me, backend=backend, config=config)
    with edit(role) as data:
        data["successor"] = {"id": sid, "spawned_at": _stamp()}
    return sid


def takeover(role: str, *, me: str | None, backend: Backend) -> str | None:
    """Successor confirms: becomes active_agent, closes the predecessor. Returns the closed id."""
    if not me:
        raise StateError("own session id unknown (CARHUNT_SESSION_ID / AGTERM_SESSION_ID unset)")
    with edit(role) as data:
        old = data.get("handover_from") or data.get("active_agent")
        succ = (data.get("successor") or {}).get("id")
        if succ and succ != me:
            raise StateError(f"successor of {role} is {succ}, not {me}")
        if old == me:
            return None
        data["active_agent"] = me
        data["status"] = "running"
        if old:
            data.setdefault("previous_agents", []).append(old)
    closed = None
    if old and backend.alive(old):
        backend.close(old)
        closed = old
    with edit(role) as data:
        data["handover_from"] = None
        data["successor"] = None
    return closed


def cleanup(backend: Backend) -> list[str]:
    """Close the sessions of completed agents (once). Returns the closed session ids."""
    closed: list[str] = []
    for role in roles():
        data = read(role)
        if data.get("status") != "completed" or data.get("closed_at"):
            continue
        sid = data.get("active_agent")
        if sid and backend.alive(sid):
            backend.close(sid)
            closed.append(sid)
        with edit(role) as d:
            d["closed_at"] = _stamp()
    return closed


def load_notes(text: str) -> dict:
    """Handover notes from JSON or YAML text."""
    try:
        notes = json.loads(text)
    except json.JSONDecodeError:
        import yaml
        notes = yaml.safe_load(text)
    if not isinstance(notes, dict):
        raise StateError("handover notes must be an object")
    return notes
