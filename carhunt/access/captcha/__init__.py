"""Local captcha / bot-wall solver for carhunt browsers (lane, identity, plain-chrome tabs over CDP).

    from carhunt.access.captcha import detect, solve
    info = detect(page)           # CaptchaInfo | None
    res = solve(page, route="plain", port=PORT)   # Result(status=solved|failed|hard-block|...)

Deterministic first (DOM + OpenCV); a local Ollama VLM (+ optional OWLv2) only where pixels need
understanding (reCAPTCHA tiles, unknown walls). No paid solving services, nothing leaves the machine.
Heavy deps import lazily: `detect` needs nothing beyond the stdlib; the slider maths needs numpy + OpenCV.
"""
from __future__ import annotations

from typing import Any

__all__ = ["detect", "classify", "solve", "CaptchaInfo", "Result", "site_of"]


def __getattr__(name: str) -> Any:
    if name in ("detect", "classify", "CaptchaInfo"):
        from . import detect as _d
        return getattr(_d, name)
    if name in ("solve", "Result", "site_of"):
        from . import core as _c
        return getattr(_c, name)
    raise AttributeError(name)
