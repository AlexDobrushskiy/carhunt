"""coches.net: "Contactar" form on the ad.

Status: working only on this route: Camoufox (stealth Firefox) on a Spanish residential IP
(country ES); 5/5 sends on 2026-11-03. Imperva blocks the contact API from non-ES IPs for every
client (Playwright, raw CDP, curl_cffi, anti-detect browsers, 2026-11-02), and a Playwright-attached
Chromium flags the IP for hours: never open coches.net in a lane/identity Playwright tab.
Success = the site's own answer to POST …/contact-mail: 2xx sent, 403 Imperva (nothing delivered),
no answer → unknown (a "not sent" arrived anyway, #109 2026-11-03: check the relay mail before any
re-send). Seller replies arrive as Gmail relay mail (times CET, match by ad id): no thread reader.
"""
from __future__ import annotations

import random
import re
from typing import Any, ClassVar

from ..base import SendResult
from ._chat import Abort, ChatSite

FORM = 'form[aria-label="contact form"]'
# The app aborts XHRs after 10 s; the contact POST takes longer through the proxy (2026-11-03).
# "mw:" runs it in the page's main world under Camoufox; elsewhere it is a harmless JS label.
NO_XHR_TIMEOUT = ("mw:(()=>{const P=XMLHttpRequest.prototype; if(P.__noTO) return; Object.defineProperty(P,'timeout',"
                  "{configurable:true,get(){return 0},set(v){}}); P.__noTO=1;})()")


class Coches(ChatSite):
    name: ClassVar[str] = "coches.net"
    route: ClassVar[str] = "camoufox"
    country: ClassVar[str | None] = "ES"
    can_read: ClassVar[bool] = False
    blocked_markers: ClassVar[tuple[str, ...]] = ("eres un bot", "Pardon Our Interruption")
    consent_buttons: ClassVar[tuple[str, ...]] = ("Aceptar y cerrar", "Aceptar todo", "Aceptar")
    form_css: ClassVar[str] = FORM
    box: ClassVar[str] = f"{FORM} textarea"
    load_ms: ClassVar[int] = 8000
    settle_ms: ClassVar[int] = 1000
    js_click: ClassVar[bool] = False
    api_wait_s: ClassVar[int] = 180

    def reveal_form(self, page: Any) -> Any:
        if page.locator('[data-testid="shared-topbar-cta-login"]').count():
            raise Abort("not logged in", login=True)
        if not page.locator(FORM).count():
            raise Abort("no contact form (already contacted or ad gone)", no_form=True)
        return page

    def fill(self, page: Any, box: Any, text: str) -> None:
        # Never press Enter: a typed line break resets the form and the click sends nothing (2026-11-03).
        box.scroll_into_view_if_needed()
        box.click()
        lines = text.split("\n")
        for i, line in enumerate(lines):
            for ch in line:
                page.keyboard.type(ch)
                page.wait_for_timeout(random.randint(20, 60))
            if i < len(lines) - 1:
                page.keyboard.insert_text("\n")
        page.wait_for_timeout(1500)
        if (box.input_value() or "").strip() != text.strip():
            raise Abort("message box does not hold the text (form reset?)")

    def submit(self, page: Any, box: Any) -> None:
        try:
            page.evaluate(NO_XHR_TIMEOUT)
        except Exception:
            pass
        self._api: list[int] = []
        page.on("response", lambda r: self._api.append(r.status) if "/contact-mail" in r.url else None)
        page.on("requestfailed", lambda r: self._api.append(0) if "/contact-mail" in r.url else None)
        # Two "Contactar" buttons: a lead button outside the form and the form's submit. Click once, never again.
        page.locator(FORM).get_by_role("button", name=re.compile(r"^\s*Contactar\s*$")).first.click()

    def outcome(self, page: Any, box: Any, text: str, before: str, url_before: str) -> SendResult:
        for _ in range(self.api_wait_s):
            if self._api:
                break
            page.wait_for_timeout(1000)
        st = self._api[0] if self._api else None
        raw = {"submitted": True, "api_status": st, "confirmed": st is not None and 200 <= st < 300,
               "url": page.url}
        if st == 403:
            raw["site_error"] = "contact-mail 403 (Imperva)"
            return SendResult(False, error="contact-mail blocked by Imperva (403): nothing delivered", raw=raw)
        return SendResult(True, raw=raw)


CHANNEL = Coches
