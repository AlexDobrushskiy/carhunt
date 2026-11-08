"""leboncoin.fr: "Envoyer un message" (/reply/<id>) or a reply in a /messages conversation.

Route: plain-chrome on the site's own profile through a French residential exit (country FR):
the account must only ever see one French IP and has no SMS recovery, so never the identity pool
or the home IP. A VPN exit gets a messaging soft block (blank /reply).
Stop the site at the first block (403 / DataDome slider): fast bursts get the IP hard-banned for
hours. Never "Faire une offre": a price is the owner's call.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import Abort, ChatSite


class Leboncoin(ChatSite):
    name: ClassVar[str] = "leboncoin.fr"
    route: ClassVar[str] = "plain-chrome"
    country: ClassVar[str | None] = "FR"
    max_len: ClassVar[int] = 2500  # /reply textarea limit
    success_markers: ClassVar[tuple[str, ...]] = ("message a bien été envoyé", "message envoyé",
                                                  "votre message a été envoyé")
    success_url_parts: ClassVar[tuple[str, ...]] = ("/messages", "reply-multi-apply")
    blocked_markers: ClassVar[tuple[str, ...]] = ChatSite.blocked_markers + ("Access is temporarily restricted",)
    blocked_html: ClassVar[tuple[str, ...]] = ("captcha-delivery",)
    login_url_parts: ClassVar[tuple[str, ...]] = ("auth.leboncoin", "/connexion")
    consent_buttons: ClassVar[tuple[str, ...]] = ("Accepter & Fermer", "Tout accepter", "Accepter")
    box: ClassVar[str] = "textarea[name=body], textarea"
    submit_names: ClassVar[tuple[Any, ...]] = (re.compile(r"^\s*Envoyer\s*$", re.I),)
    load_ms: ClassVar[int] = 8000
    inbox_url: ClassVar[str] = "https://www.leboncoin.fr/messages"
    conv_sel: ClassVar[str] = "a[href*='/messages/id/']"
    can_poll: ClassVar[bool] = True

    def target_url(self, page: Any, to: str) -> str:
        if "/reply/" in to or "/messages" in to:
            return to
        ad = re.search(r"/(\d{6,})(?:\.htm)?(?:[/?#]|$)", to) or re.fullmatch(r"(\d{6,})", to)
        if not ad:
            raise Abort(f"no leboncoin ad id in {to!r}")
        return f"https://www.leboncoin.fr/reply/{ad.group(1)}"

    def thread_url(self, page: Any, to: str) -> str:
        if "/messages" not in to:
            raise Abort("pass the /messages conversation URL (the ad page has no thread)")
        return to


CHANNEL = Leboncoin
