"""standvirtual.com: the ad's "Mensagem" chat panel.

Status: working (2026-11-01..05). Route: identity (OLX Group login, shared with olx.pt; it lives
on the identity master, pool copies can be stale: re-seed them). Success = box cleared and the
text visible in the panel; never retry without reading the chat first (sv-send). Read the thread
on the same ad URL. No site poll: the inbox is /contapessoal/messages, the site mails alerts.
"""
from __future__ import annotations

import re
from typing import Any, ClassVar

from ._chat import ChatSite

# The chat panel = the box's nearest ancestor that also holds the day header / conversation text.
PANEL = "xpath=ancestor::*[contains(., 'HOJE') or contains(., 'Hoje') or contains(., 'conversa')][1]"


class StandVirtual(ChatSite):
    name: ClassVar[str] = "standvirtual.com"
    route: ClassVar[str] = "identity"
    open_form: ClassVar[tuple[Any, ...]] = (re.compile(r"^\s*Mensagem\s*$", re.I), "Mensagem")
    open_thread: ClassVar[tuple[Any, ...]] = open_form
    box: ClassVar[str] = '[data-testid="message-text-area"]'
    login_url_parts: ClassVar[tuple[str, ...]] = ("login.standvirtual", "/authentication")
    load_ms: ClassVar[int] = 3000
    inbox_url: ClassVar[str] = "https://www.standvirtual.com/contapessoal/messages"

    def fill(self, page: Any, box: Any, text: str) -> None:
        box.fill(text.replace("\n", " "))  # a newline would submit early
        page.wait_for_timeout(800)

    def submit(self, page: Any, box: Any) -> None:
        self.click(box.locator("xpath=following::button[1]"))

    def thread_text(self, page: Any) -> str:
        panel = page.locator(self.s("box")).first.locator(PANEL)
        try:
            if panel.count():
                return panel.inner_text(timeout=5000)
        except Exception:
            pass
        return self.page_text(page)


CHANNEL = StandVirtual
