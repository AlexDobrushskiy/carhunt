"""Captcha settings: config `browsers.captcha` + defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, fields

from carhunt.access import _core


@dataclass(frozen=True)
class CaptchaConfig:
    enabled: bool = False                 # opt-in: solving raises a site's bot score if misused
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:4b"             # ~0.5 s/tile, 3.3 GB
    owlv2: bool = False                   # 4x4 grids via OWLv2 boxes (torch + transformers, ~0.6 GB weights)
    hcaptcha_vlm: bool = False            # hCaptcha canvas tasks via VLM points (unreliable)
    max_attempts: int = 2                 # per run: every failed try raises the site's bot score
    site_budget: int = 6                  # attempts per site per window …
    site_window_h: float = 6.0            # … refuses beyond this (`--force` overrides)
    screenshots: bool = True              # per-run screenshots under $CARHUNT_HOME/access/captcha-shots/


def load() -> CaptchaConfig:
    from carhunt.access import settings
    raw = dict(settings.load().captcha or {})
    known = {f.name for f in fields(CaptchaConfig)}
    kw = {k: v for k, v in raw.items() if k in known}
    if "ollama_url" not in kw and os.environ.get("OLLAMA_HOST"):
        h = os.environ["OLLAMA_HOST"]
        kw["ollama_url"] = h if h.startswith("http") else f"http://{h}"
    return CaptchaConfig(**kw)


def db_path():
    return _core.path("access", "captcha.sqlite")


def shots_root():
    return _core.home() / "access" / "captcha-shots"
