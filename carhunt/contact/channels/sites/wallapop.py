"""wallapop.com (es): the item chat.

Route: identity (logged in; new-device logins get an email code). Chat URL
`es.wallapop.com/app/chat?itemId=<hash id>` (the ad's "Chat" button does not navigate over CDP).
An /item/<slug> URL is resolved to the hash id from the item page. The textarea cuts at 300 chars
without a warning: longer text is refused here; if a cut ever happens, send only the cut part with
an apology, never the list again. Wallapop sends no alert mail, so replies need this poll.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import Abort, ChatSite

CHAT = "https://es.wallapop.com/app/chat?itemId="


class Wallapop(ChatSite):
    name: ClassVar[str] = "wallapop.com"
    route: ClassVar[str] = "identity"
    max_len: ClassVar[int] = 300
    consent_buttons: ClassVar[tuple[str, ...]] = ("Aceptar todo", "Aceptar", "Accept")
    login_url_parts: ClassVar[tuple[str, ...]] = ("accounts.wallapop", "/login")
    box: ClassVar[str] = 'textarea[placeholder*="chatear" i], textarea'
    # Contact data (a phone) raises "¿Enviar datos personales?"; only approved texts get here.
    confirm_names: ClassVar[tuple[str, ...]] = ("Enviar de todas formas",)
    load_ms: ClassVar[int] = 7000
    inbox_url: ClassVar[str] = "https://es.wallapop.com/app/chat"
    conv_sel: ClassVar[str] = '[class*="conversation" i]:not([class*="conversation" i] [class*="conversation" i])'
    can_poll: ClassVar[bool] = True

    def target_url(self, page: Any, to: str) -> str:
        if "/app/chat" in to:
            return to
        if "/" not in to:
            return CHAT + to
        if "/item/" in to:
            page.goto(to, wait_until="domcontentloaded", timeout=60000)
            m = re.search(r'"item":\{"id":"([a-z0-9]+)"', page.content())
            if m:
                return CHAT + m.group(1)
        raise Abort(f"no wallapop item id for {to!r} (pass the chat URL or the item hash id)")

    def reveal_form(self, page: Any) -> Any:
        # First chat on a new account: an onboarding modal asks the account type.
        if page.get_by_text("Cuenta personal").count():
            page.get_by_text("Cuenta personal").first.evaluate("e => e.click()")
            page.wait_for_timeout(1500)
            btn = self.find_button(page, ("Guardar", "Continuar", "Aceptar", "Confirmar", "Siguiente"))
            if btn is not None:
                self.click(btn)
                page.wait_for_timeout(3000)
        return page


CHANNEL = Wallapop
