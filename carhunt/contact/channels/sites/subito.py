"""subito.it: "Contatta" on the ad, or a reply inside an existing chat thread.

Route: identity (Google + password login on the identity profile). A removed ad keeps its
thread: reply inside it with the conversation URL from areariservata.subito.it/messaggi.
Success: the text shows in the chat with the box cleared (the sender's only reliable signal).
Poll: the inbox list at areariservata (www.subito.it/messaggi is an error page).
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import ChatSite


class Subito(ChatSite):
    name: ClassVar[str] = "subito.it"
    route: ClassVar[str] = "identity"
    success_markers: ClassVar[tuple[str, ...]] = ("Messaggio inviato",)
    consent_buttons: ClassVar[tuple[str, ...]] = ("Accetta tutto", "Accetta", "Accetto")
    login_url_parts: ClassVar[tuple[str, ...]] = ("/login",)
    open_form: ClassVar[tuple[Any, ...]] = (re.compile(r"^\s*Contatta\s*$", re.I), "Contatta")
    submit_names: ClassVar[tuple[Any, ...]] = (re.compile(r"^\s*Invia\s*$", re.I),)
    submit_css: ClassVar[str] = "button[type=submit]"
    inbox_url: ClassVar[str] = "https://areariservata.subito.it/messaggi"
    conv_sel: ClassVar[str] = "a[href*='/messaggi/']"
    can_poll: ClassVar[bool] = True


CHANNEL = Subito
