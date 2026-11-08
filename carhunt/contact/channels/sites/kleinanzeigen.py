"""kleinanzeigen.de: "Nachricht schreiben" on the ad, logged in.

Route: identity (logged in on the identity profiles; do account actions such as activation over
mobile data: the home IP range can be banned). The thread check (text in the page + box cleared)
is the main success signal. Replies come by alert mail; the thread reader
works on a conversation URL from the inbox (m-nachrichten.html) with the generic bubble heuristic.
"""
from __future__ import annotations

from typing import Any, ClassVar

from ._chat import ChatSite


class Kleinanzeigen(ChatSite):
    name: ClassVar[str] = "kleinanzeigen.de"
    route: ClassVar[str] = "identity"
    success_markers: ClassVar[tuple[str, ...]] = ("Nachricht gesendet", "wurde gesendet")
    consent_buttons: ClassVar[tuple[str, ...]] = ("Alle akzeptieren", "Einverstanden", "Akzeptieren")
    gone_markers: ClassVar[tuple[str, ...]] = ("nicht mehr verfügbar",)
    login_url_parts: ClassVar[tuple[str, ...]] = ("login.kleinanzeigen", "einloggen")
    open_form: ClassVar[tuple[Any, ...]] = ("Nachricht schreiben",)
    box: ClassVar[str] = "textarea:visible"
    submit_names: ClassVar[tuple[Any, ...]] = ("Nachricht senden",)
    submit_css: ClassVar[str] = "button[type=submit]:visible"
    inbox_url: ClassVar[str] = "https://www.kleinanzeigen.de/m-nachrichten.html"


CHANNEL = Kleinanzeigen
