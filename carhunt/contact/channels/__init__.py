"""Channel registry: `get(name, cfg)` → adapter instance.

Built-ins: whatsapp, email. Marketplace chats: every module in channels/sites/ that defines
`CHANNEL` (a SiteChannel subclass); its `name` is the site key used in config and on the CLI
(e.g. `mobile.de`, `wallapop.com`).
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any

from .base import Channel, ChannelError


def _site_classes() -> dict[str, type[Channel]]:
    from . import sites

    out: dict[str, type[Channel]] = {}
    for m in pkgutil.iter_modules(sites.__path__):
        if m.name.startswith("_") or m.name in ("base", "fake"):
            continue
        mod = importlib.import_module(f"{sites.__name__}.{m.name}")
        cls = getattr(mod, "CHANNEL", None)
        if cls is not None:
            out[cls.name] = cls
    return out


def names() -> list[str]:
    return ["whatsapp", "email", *sorted(_site_classes())]


def site_names() -> list[str]:
    return sorted(_site_classes())


def get(name: str, cfg: dict[str, Any] | None = None, **opts: Any) -> Channel:
    if name == "whatsapp":
        from .whatsapp import WhatsApp

        return WhatsApp(cfg, **opts)
    if name == "email":
        from .email import Email

        return Email(cfg, **opts)
    sites = _site_classes()
    if name in sites:
        return sites[name](cfg, **opts)
    raise ChannelError(f"unknown channel {name!r}; known: {', '.join(names())}")
