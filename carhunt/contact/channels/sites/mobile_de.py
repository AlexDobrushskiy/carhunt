"""mobile.de: the ad's contact form, or a reply inside the message-center conversation.

Form confirmed by "Anfrage erfolgreich gesendet"; conversation reply via the "Senden" box.
Route: identity (plain-chrome on a logged-in identity profile): Akamai answers every
Playwright-launched Chrome with "Zugriff verweigert".
Already-contacted ads have no "E-Mail schreiben": reply in the conversation (`to` = its URL), or
answer the seller's relay mail on the email channel.
Seller replies arrive as relay mail, so no site poll.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import Abort, ChatSite


class MobileDe(ChatSite):
    _form_mode = False
    name: ClassVar[str] = "mobile.de"
    route: ClassVar[str] = "identity"
    success_markers: ClassVar[tuple[str, ...]] = ("Anfrage erfolgreich gesendet",)
    consent_buttons: ClassVar[tuple[str, ...]] = ("Einverstanden", "Alle akzeptieren", "Akzeptieren")
    open_form: ClassVar[tuple[Any, ...]] = ("E-Mail schreiben",)
    login_url_parts: ClassVar[tuple[str, ...]] = ("id.mobile.de",)
    submit_names: ClassVar[tuple[Any, ...]] = (re.compile(r"^\s*E-Mail senden\s*$", re.I), re.compile(r"^\s*Senden\s*$", re.I))
    submit_css: ClassVar[str] = "button[type=submit]"
    # Contact data in a conversation reply raises a warning dialog.
    confirm_names: ClassVar[tuple[str, ...]] = ("Trotzdem senden",)

    AD = re.compile(r"details\.html\?(?:.*&)?id=(\d+)|/fahrzeuge/details|/checkout/core/")

    def normalize_to(self, to: str) -> str:
        to = to.strip()
        return f"https://suchen.mobile.de/fahrzeuge/details.html?id={to}" if to.isdigit() else to

    def thread_url(self, page: Any, to: str) -> str:
        if self.AD.search(to):
            raise Abort("an ad URL has no thread: pass the message-center conversation URL")
        return to

    def reveal_form(self, page: Any) -> Any:
        self._form_mode = bool(self.AD.search(page.url))
        if self.visible(page, self.s("box")):
            return page  # conversation, or a form already open
        btn = self.find_button(page, self.s("open_form"))
        if btn is None:
            raise Abort("no 'E-Mail schreiben' on the ad (already contacted?): reply in the conversation "
                        "URL or to the seller's relay mail", no_form=True, already_contacted=True)
        try:  # the form opens in a new tab (/checkout/core/<id>)
            with page.context.expect_page(timeout=8000) as new:
                self.click(btn)
            form = new.value
            form.wait_for_load_state("domcontentloaded")
            form.wait_for_timeout(self.load_ms)
        except Exception:
            form = page
        self.check_page(form)
        return form

    def prepare(self, page: Any) -> None:
        if self._form_mode:
            # The account prefills name/email/phone: keep the phone out and every opt-in off (mde_send).
            for el in page.locator("input[type=tel], input[name*=phone i]").all():
                try:
                    el.fill("")
                except Exception:
                    pass
            for cb in page.locator("input[type=checkbox]").all():
                try:
                    if cb.is_checked():
                        cb.evaluate("e => e.click()")
                except Exception:
                    pass


CHANNEL = MobileDe
