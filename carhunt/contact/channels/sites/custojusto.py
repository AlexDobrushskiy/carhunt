"""custojusto.pt: one-way contact form on the ad, then a Sendbird chat in the site inbox.

"Enviar mensagem" on an ad is a form, not a chat: "contactado com sucesso", and the seller's
answer opens a thread in the CJ inbox later (often the next day); poll the inbox for form-contacted
cars. Replies inside a conversation (`/user/messages?id=…`) go through the Sendbird box. Route:
identity, but the login lives on the master; pool copies can lack it. Name/email come from
`contact.persona` when the form asks for them.
"""
from __future__ import annotations

from typing import Any, ClassVar

from ._chat import ChatSite

_CHAT = {  # Sendbird UIKit chat (cj-send / cj-conv)
    "open_form": (),
    "box": "#sendbird-message-input-text-field",
    "submit_names": (),
    "submit_css": "",  # Enter; the send icon below is the fallback
    "msg_sel": ".sendbird-message-content",
    "mine_sel": ".sendbird-message-content.outgoing",
    "text_sel": ".sendbird-text-message-item-body",
    "success_markers": (),
    "persona_fields": {},
}


class CustoJusto(ChatSite):
    name: ClassVar[str] = "custojusto.pt"
    route: ClassVar[str] = "identity"
    success_markers: ClassVar[tuple[str, ...]] = ("contactado com sucesso",)
    open_form: ClassVar[tuple[Any, ...]] = ("Enviar mensagem",)
    submit_names: ClassVar[tuple[Any, ...]] = ("Enviar",)
    submit_css: ClassVar[str] = "button[type=submit]"
    persona_fields: ClassVar[dict[str, str]] = {"input[name*=name i]": "name", "input[type=email]": "email"}
    login_url_parts: ClassVar[tuple[str, ...]] = ("/login",)
    inbox_url: ClassVar[str] = "https://www.custojusto.pt/user/messages"
    conv_sel: ClassVar[str] = ".sendbird-channel-preview"
    unread_sel: ClassVar[str] = "[class*='unread-message-count']"
    msg_sel: ClassVar[str] = _CHAT["msg_sel"]
    mine_sel: ClassVar[str] = _CHAT["mine_sel"]
    text_sel: ClassVar[str] = _CHAT["text_sel"]
    can_poll: ClassVar[bool] = True
    _chat_mode = False

    def s(self, key: str) -> Any:
        if self._chat_mode and key in _CHAT and key not in self._sel:
            return _CHAT[key]
        return super().s(key)

    def target_url(self, page: Any, to: str) -> str:
        self._chat_mode = "/user/messages" in to
        return to

    def submit(self, page: Any, box: Any) -> None:
        if not self._chat_mode:
            return super().submit(page, box)
        box.press("Enter")
        page.wait_for_timeout(3000)
        if (box.inner_text() or "").strip():  # Enter didn't take: the send icon
            btn = page.locator(".sendbird-message-input--send")
            if btn.count():
                btn.last.click()


CHANNEL = CustoJusto
