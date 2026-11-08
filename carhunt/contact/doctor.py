"""`carhunt doctor` checks for contact: wacli, Gmail secrets, ledger, config sanity, PAUSE."""
from __future__ import annotations

import shutil
from typing import Any

from carhunt.core.doctor import Check

from . import deps
from .settings import contact_settings


def checks(cfg: dict[str, Any] | None = None) -> list[Check]:
    cfg = cfg if cfg is not None else deps.load_config()
    s = contact_settings(cfg)
    out: list[Check] = []

    w = shutil.which("wacli")
    out.append(Check("contact.wacli", "ok" if w else "warn", w or "wacli not on PATH (WhatsApp channel off)",
                     "" if w else "brew install openclaw/tap/wacli && wacli auth  (see docs/contact.md: ban risk)"))

    for name in ("gmail_oauth_client", "gmail_token"):
        have = deps.secret(name) is not None
        out.append(Check(f"contact.secret.{name}", "ok" if have else "warn", "set" if have else "missing (email channel off)",
                         "" if have else f"carhunt secret set {name}  (docs/contact.md § Gmail OAuth)"))

    try:
        p = deps.path("contact", "ledger.jsonl")
        p.touch(exist_ok=True)
        out.append(Check("contact.ledger", "ok", str(p)))
    except OSError as e:
        out.append(Check("contact.ledger", "fail", str(e), "check $CARHUNT_HOME permissions"))

    names = [lim.get("name") for lim in s["limits"]]
    bad = [n for n in names if not n] + [n for n in set(names) if names.count(n) > 1]
    out.append(Check("contact.limits", "fail" if bad else "ok", f"{len(names)} limits" + (f"; bad: {bad}" if bad else ""),
                     "every contact.limits entry needs a unique name" if bad else ""))
    if not (s["nudge"].get("qualify") or []):
        out.append(Check("contact.nudge", "warn", "no nudge.qualify predicates: every --nudge is refused",
                         "add predicates (docs/contact.md § nudge)"))

    if deps.pause_file().exists():
        out.append(Check("contact.pause", "warn", "PAUSE file present: all sends refused", "carhunt unpause"))
    return out
