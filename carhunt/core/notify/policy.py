"""Push policy, enforced in code (design D6).

Why: in the EV run 28 messages reached the owner's phone in one day and 14 asked nothing (FYI, "sent",
heartbeats). Only three kinds exist: `digest` (scheduled summary), `ask` (a decision that blocks progress
today; buttons or a free answer), `urgent` (a breach or a dead session the agent could not fix itself).
"""
from __future__ import annotations

import re

KINDS = ("digest", "ask", "urgent")
# default per kind during quiet hours: hold until the window ends, or send without sound
QUIET_DEFAULT = {"digest": "hold", "ask": "hold", "urgent": "silent"}
MAX_BUTTONS = 8

# Why: a hub DB once stored a site password sent in a ping (EV run, 11-06). Never put secrets in pings.
_SECRET_SHAPES = re.compile(
    r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b|sk-ant-[A-Za-z0-9_-]{20,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}"
    r"|\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{30,}|\bAKIA[0-9A-Z]{16}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:password|passwd|pwd|passwort|senha|contraseña)\s*[:=]\s*\S+", re.I)


class Refused(ValueError):
    """The message breaks the push policy; nothing was sent."""


def check(text: str, kind: str, buttons: list[str] | None) -> None:
    if kind not in KINDS:
        raise Refused(f"kind {kind!r} refused: pushes are only {', '.join(KINDS)}. "
                      "Progress/FYI goes into the next digest.")
    if not text or not text.strip():
        raise Refused("empty message")
    if _SECRET_SHAPES.search(text):
        raise Refused("text looks like it contains a secret (token, key or password); never put secrets in pings")
    if buttons is not None:
        if not 1 <= len(buttons) <= MAX_BUTTONS or any(not b.strip() for b in buttons):
            raise Refused(f"buttons: 1-{MAX_BUTTONS} non-empty labels")
        if kind != "ask":
            raise Refused("buttons only on kind=ask")


def quiet_mode(kind: str, overrides: dict | None) -> str:
    return (overrides or {}).get(kind) or QUIET_DEFAULT[kind]
