"""AutoScout24 guest contact form (no login), every country domain.

Status: working on .it (and other domains where the form still sends); refused on .de/.nl, where
the form sends nothing → email the dealer (email channel). `force=True` (opts) sends anyway.
Route: lane (headless browser, no login).
Success text differs per domain; only .it/.de are known. "afterlead" in the URL also means sent,
but its absence does not mean failed.
Replies come by email (persona.email, the plus-address), so no thread reader.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar
from urllib.parse import urlparse

from ..base import SendResult
from ._chat import ChatSite

_OPEN = re.compile(r"E-Mail senden|Contatta venditore|^\s*E-mail\s*$|Contacter le vendeur|Contactar vendedor|"
                   r"Verkoper contacteren|Invia e-mail|Envoyer un e-mail|Enviar e-mail|E-mail sturen|Send e-?mail", re.I)
_SEND = re.compile(r"E-Mail senden|Nachricht senden|Senden|Envoyer|Invia|Enviar|Verzenden|Versturen|Send", re.I)


class AutoScout24(ChatSite):
    name: ClassVar[str] = "autoscout24"
    route: ClassVar[str] = "lane"
    can_read: ClassVar[bool] = False
    success_markers: ClassVar[tuple[str, ...]] = ("Messaggio inviato con successo", "Anfrage wurde verschickt")
    success_url_parts: ClassVar[tuple[str, ...]] = ("afterlead",)
    consent_buttons: ClassVar[tuple[str, ...]] = ("Alle akzeptieren", "Accetta tutto", "Tout accepter", "Accepter",
                                                  "Aceptar", "Accepteren", "Akzeptieren", "Einverstanden")
    open_form: ClassVar[tuple[Any, ...]] = (_OPEN,)
    form_css: ClassVar[str] = "[role=dialog]"
    box: ClassVar[str] = "[role=dialog] textarea"
    # The dialog's last button is an empty close (×): click the named send button.
    submit_names: ClassVar[tuple[Any, ...]] = (_SEND,)
    submit_css: ClassVar[str] = "button:not(:empty)"
    persona_fields: ClassVar[dict[str, str]] = {"input[type=text]": "name", "input[type=email]": "email"}
    uncheck_css: ClassVar[str] = "input[type=checkbox]"
    js_click: ClassVar[bool] = False  # own headless browser, real clicks work
    broken_hosts: ClassVar[tuple[str, ...]] = ("autoscout24.de", "autoscout24.nl")

    def send(self, to: str, text: str) -> SendResult:
        host = urlparse(self.normalize_to(to)).hostname or ""
        if not self.opts.get("force") and any(host.endswith(h) for h in self.broken_hosts):
            return SendResult(False, error=f"{host} contact form sends nothing: email the dealer instead",
                              raw={"refused": "broken_form", "submitted": False})
        return super().send(to, text)


CHANNEL = AutoScout24
