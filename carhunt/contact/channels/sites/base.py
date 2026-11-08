"""Shared shape for marketplace chat/contact-form senders.

A site sender opens the ad (or conversation) in a browser tab from `carhunt.access.session.tab`,
fills the message, submits, and confirms with the site's own success text per locale.
Rules every sender keeps (EV run):
- No URL in the text (base.check_text) — the site attaches the ad.
- Duplicate guard: refuse if the text's first 60 chars are already in the thread (an opener
  went out twice, 2026-11-01).
- Success = the site's own confirmation marker, per locale; a guessed marker logged real sends
  as FAILED (2026-11-04). No marker seen → `unknown`, never `delivered`.
- Already-contacted ad (no form, e.g. mobile.de) → reply inside the existing conversation.
"""
from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any, ClassVar, ContextManager

from ..base import Channel, ChannelError, Msg, SendResult

TabFactory = Callable[..., ContextManager[Any]]


def _default_tab_factory() -> TabFactory:
    try:
        from carhunt.access import session  # type: ignore
    except ImportError as e:  # access not merged yet
        raise ChannelError("carhunt.access is not installed: site senders need the browsers module") from e
    return session.tab


class SiteChannel(Channel):
    kind: ClassVar[str] = "site"
    route: ClassVar[str] = "identity"  # access route: http | lane | identity | plain-chrome | camoufox
    country: ClassVar[str | None] = None  # residential-proxy exit country, when the site needs one
    success_markers: ClassVar[tuple[str, ...]] = ()  # site confirmation text, all locales seen

    def __init__(self, cfg: dict[str, Any] | None = None, *, tab_factory: TabFactory | None = None, **opts: Any):
        super().__init__(cfg, **opts)
        self._tab_factory = tab_factory

    def tab(self) -> ContextManager[Any]:
        factory = self._tab_factory or _default_tab_factory()
        return factory(self.route, country=self.country, site=self.name)

    def normalize_to(self, to: str) -> str:
        """`to` is the ad URL (or conversation URL) on this site."""
        return to.strip()

    def dry_run(self, to: str, text: str) -> dict[str, Any]:
        return {"channel": self.name, "to": self.normalize_to(to), "text": text, "route": self.route,
                "country": self.country, "submit": False}

    # helpers for subclasses ---------------------------------------------------------------------
    @staticmethod
    def already_in_thread(thread: list[Msg], text: str) -> bool:
        head = text.strip()[:60]
        return any(m.from_me and head and head in m.text for m in thread)

    def confirmed(self, page_text: str) -> bool:
        low = page_text.lower()
        return any(m.lower() in low for m in self.success_markers)

    def send(self, to: str, text: str) -> SendResult:  # pragma: no cover - subclasses override
        raise NotImplementedError

    def read_thread(self, to: str, limit: int = 50) -> list[Msg]:  # pragma: no cover
        raise ChannelError(f"{self.name}: reading threads is not supported")


@contextlib.contextmanager
def no_tab(*_a: Any, **_k: Any):  # used by dry-run paths that must never open a browser
    raise ChannelError("dry run must not open a browser")
    yield
