"""Notifier transports: telegram (Bot API), stdout, none."""
from __future__ import annotations

import json
import sys
from typing import Any, Protocol

import requests

LIMIT = 4096  # Telegram's max message length


class NotifyError(RuntimeError):
    pass


class Backend(Protocol):
    name: str

    def send(self, text: str, *, silent: bool, buttons: list[str] | None, ask: bool) -> list[int]: ...


def chunks(text: str, limit: int = LIMIT) -> list[str]:
    out = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        out.append(text)
    return out


class TelegramBackend:
    name = "telegram"

    def __init__(self, token: str, chat_id: str | int, api_base: str = "https://api.telegram.org", timeout: float = 20):
        self._token = token
        self.chat_id = str(chat_id)
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def call(self, method: str, payload: dict, *, timeout: float | None = None) -> Any:
        # the token is part of the URL: never let it into an error message or a log
        try:
            r = requests.post(f"{self.api_base}/bot{self._token}/{method}", json=payload,
                              timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise NotifyError(f"telegram {method}: {type(e).__name__}") from None
        try:
            body = r.json()
        except ValueError:
            raise NotifyError(f"telegram {method}: HTTP {r.status_code}, not JSON") from None
        if not body.get("ok"):
            desc = str(body.get("description", "")).replace(self._token, "<token>")
            raise NotifyError(f"telegram {method}: HTTP {r.status_code} {desc}")
        return body["result"]

    def send(self, text: str, *, silent: bool, buttons: list[str] | None, ask: bool) -> list[int]:
        parts = chunks(text)
        ids = []
        for i, part in enumerate(parts):
            p: dict[str, Any] = {"chat_id": self.chat_id, "text": part, "disable_web_page_preview": True}
            if silent:
                p["disable_notification"] = True
            if i == len(parts) - 1:
                if buttons:
                    rows = [[b] for b in range(len(buttons))] if len(buttons) > 3 else [list(range(len(buttons)))]
                    p["reply_markup"] = {"inline_keyboard": [[{"text": buttons[j], "callback_data": str(j)}
                                                              for j in row] for row in rows]}
                elif ask:
                    p["reply_markup"] = {"force_reply": True, "input_field_placeholder": "Answer…"}
            ids.append(int(self.call("sendMessage", p)["message_id"]))
        return ids

    def updates(self, offset: int | None, timeout: int) -> list[dict]:
        p: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            p["offset"] = offset
        return self.call("getUpdates", p, timeout=timeout + 15)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})
        except NotifyError:
            pass  # cosmetic (stops the button spinner); the answer is already routed


class StdoutBackend:
    name = "stdout"

    def __init__(self) -> None:
        self._n = 0

    def send(self, text: str, *, silent: bool, buttons: list[str] | None, ask: bool) -> list[int]:
        self._n += 1
        tag = " ".join(t for t, on in (("silent", silent), ("ask", ask)) if on)
        print(f"[notify{(' ' + tag) if tag else ''}] {text}", file=sys.stdout)
        if buttons:
            print("  buttons: " + json.dumps(buttons, ensure_ascii=False), file=sys.stdout)
        return [self._n]


class NoneBackend:
    name = "none"

    def send(self, text: str, *, silent: bool, buttons: list[str] | None, ask: bool) -> list[int]:
        return []
