"""olx.pt: the ad's chat (`<ad>?chat=1`).

Thread reader: bubbles carry aria-label "Mensagem enviada por <name>". The send selectors are
unverified. Delivery counts only when our text shows in the thread with the box cleared.
Route: identity (OLX Group login on the identity master; a pool-copy 401 = stale token, re-seed,
not a block). Who is "us" in a bubble: `contact.persona.aliases` (the
names the site shows for the buyer's account) plus the site's own "you" words.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import ChatSite

_LABEL = re.compile(r"Mensagem enviada por\s+(.+)", re.I)
_YOU = {"ti", "si", "mim", "você", "voce", "tu"}


class Olx(ChatSite):
    name: ClassVar[str] = "olx.pt"
    route: ClassVar[str] = "identity"
    box: ClassVar[str] = "textarea"
    submit_css: ClassVar[str] = "button[type=submit]"
    msg_sel: ClassVar[str] = '[aria-label^="Mensagem enviada por"]'
    load_ms: ClassVar[int] = 8000

    def target_url(self, page: Any, to: str) -> str:
        if "chat=1" in to:
            return to
        return to + ("&" if "?" in to else "?") + "chat=1"

    def is_mine(self, row: dict[str, Any]) -> bool:
        m = _LABEL.match(row.get("label") or "")
        if not m:
            return bool(row.get("mine"))
        who = m.group(1).strip().lower()
        names = {str(a).strip().lower() for a in (self.persona.get("aliases") or [])}
        return who in _YOU or who in names


CHANNEL = Olx
