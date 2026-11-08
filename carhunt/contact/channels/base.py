"""Channel adapter contract. Every way of reaching a seller (WhatsApp, email, a marketplace chat)
implements this; `carhunt say` and `carhunt watch` only talk to channels through it."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

DELIVERED, FAILED, UNKNOWN = "delivered", "failed", "unknown"

URL_RE = re.compile(r"https?://|www\.", re.I)


@dataclass
class Msg:
    """One message in a thread, normalised across channels."""
    at: datetime
    from_me: bool
    text: str = ""
    id: str = ""
    reaction: str = ""
    media: str = ""
    revoked: bool = False
    sender: str = ""  # counterpart handle when inbound (phone, email, site user)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_content(self) -> bool:
        """A real message: has text or media, not a reaction/edit/delete stub.
        Why: wacli shows empty protocolMessages (edits/deletes) as new messages."""
        return not self.reaction and not self.revoked and bool(self.text.strip() or self.media)


@dataclass
class SendResult:
    ok: bool
    external_id: str = ""
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class ChannelError(Exception):
    pass


class Channel(ABC):
    """Subclasses set `name`, `kind`, and implement send/verify/read_thread."""

    name: ClassVar[str]
    kind: ClassVar[str]  # chat | email | site
    max_len: ClassVar[int] = 500  # longer → split at a sentence before calling say (WA guard cap)
    can_read: ClassVar[bool] = True

    def __init__(self, cfg: dict[str, Any] | None = None, **opts: Any):
        self.cfg = cfg or {}
        self.opts = opts

    # -- addressing ---------------------------------------------------------------------------
    def normalize_to(self, to: str) -> str:
        return to.strip()

    # -- send path ----------------------------------------------------------------------------
    def check_text(self, text: str) -> str | None:
        """Channel-specific refusal reason, or None. Sites: never a URL (the site attaches the ad;
        a pasted link reads like a bot, EV 2026-11-04)."""
        if self.kind == "site" and URL_RE.search(text):
            return "URL in a site message (the site attaches the ad)"
        if len(text) > self.max_len:
            return f"text is {len(text)} chars, {self.name} max {self.max_len}: split at a sentence"
        return None

    def dry_run(self, to: str, text: str) -> dict[str, Any]:
        """The payload that would be sent. Must not touch the network."""
        return {"channel": self.name, "to": self.normalize_to(to), "text": text}

    @abstractmethod
    def send(self, to: str, text: str) -> SendResult:
        ...

    def verify(self, to: str, text: str, result: SendResult) -> str:
        """delivered | failed | unknown. Default: trust the send result's ok flag as unknown-safe.
        Why: a coches.net script 'succeeded' and delivered nothing (2026-11-02), so adapters
        should override with a real check (sent folder, thread re-read, confirmation text)."""
        return UNKNOWN if result.ok else FAILED

    # -- read path ----------------------------------------------------------------------------
    @abstractmethod
    def read_thread(self, to: str, limit: int = 50) -> list[Msg]:
        """Oldest first. Raise ChannelError when the thread can't be read."""

    def poll(self, since: datetime) -> list[tuple[str, Msg]]:
        """Inbound messages since `since` as (counterpart, Msg). Used by `carhunt watch`."""
        return []
