"""Agent-to-agent messages: `carhunt msg --to ROLE|SESSION "text"`.

A role resolves to its state.json active_agent at send time — never a hard-coded id
(EV run 11-02: 12 briefs pointed at a closed overseer after one handover).
"""
from __future__ import annotations

from . import _core, state
from .session import UUID_RE, Backend


class MsgError(RuntimeError):
    pass


def resolve(to: str) -> str:
    if UUID_RE.fullmatch(to):
        return to
    try:
        sid = state.read(to).get("active_agent")
    except state.StateError as e:
        raise MsgError(f"{to!r} is neither a session id nor a known role") from e
    if not sid:
        raise MsgError(f"role {to!r} has no active agent")
    return sid


def send(to: str, text: str, *, backend: Backend, interrupt: bool = False,
         sender: str | None = None) -> dict:
    if not text.strip():
        raise MsgError("message is empty")
    sid = resolve(to)
    if not backend.alive(sid):
        raise MsgError(f"session {sid} ({to}) is not open")
    who = sender or _core.self_role() or "owner"
    via = backend.send(sid, f"[carhunt from {who}] {text.strip()}", interrupt=interrupt)
    return {"to": to, "session": sid, "via": via}
