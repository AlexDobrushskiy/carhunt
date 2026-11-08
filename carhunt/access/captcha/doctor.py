"""`carhunt doctor` checks for the captcha solver. Everything optional is a warn, never a fail:
the browsers work without the solver, only walls then need the owner's one-time solve."""
from __future__ import annotations

import importlib.util


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def checks(cfg=None, transport=None) -> list[dict]:
    from .config import load
    from .vlm import Ollama
    cfg = cfg or load()
    out: list[dict] = []

    def add(name, status, detail, fix=""):
        out.append(dict(name=f"captcha.{name}", status=status, detail=detail, fix=fix))

    if not cfg.enabled:
        add("enabled", "warn", "solver off: walls go up the escalation ladder to the owner's one-time solve",
            "set browsers.captcha.enabled: true (deterministic sliders need only numpy + opencv)")
    else:
        add("enabled", "ok", "solver on")

    vision_ok = _has("numpy") and _has("cv2")
    add("opencv", "ok" if vision_ok else "warn",
        "numpy + OpenCV present: DataDome / GeeTest / puzzle sliders" if vision_ok else "numpy / OpenCV missing: no slider solving",
        "" if vision_ok else "uv pip install numpy opencv-python-headless (or the carhunt[captcha] extra)")
    pw_ok = _has("playwright")
    add("playwright", "ok" if pw_ok else "warn", "attach to lane / identity / plain-chrome tabs over CDP" if pw_ok
        else "playwright missing: cannot attach to tabs", "" if pw_ok else "uv pip install playwright")

    client = Ollama(cfg.ollama_url, cfg.model, transport)
    names = client.models()
    if names is None:
        add("ollama", "warn", f"no Ollama at {cfg.ollama_url}: no reCAPTCHA grids, no unknown-wall VLM",
            "install Ollama (https://ollama.com), run it, then `ollama pull " + cfg.model + "`")
    elif not client.has_model(names):
        add("ollama", "warn", f"Ollama up, model {cfg.model} not pulled", f"ollama pull {cfg.model}")
    else:
        add("ollama", "ok", f"{cfg.model} ready: reCAPTCHA 3x3 grids, unknown-wall naming, slider gap fallback")

    if cfg.owlv2:
        owl_ok = _has("torch") and _has("transformers")
        add("owlv2", "ok" if owl_ok else "warn",
            "OWLv2 for 4x4 grids (weights download from Hugging Face on first use, ~0.6 GB)" if owl_ok
            else "owlv2: true but torch / transformers missing", "" if owl_ok else "uv pip install torch transformers")
    else:
        add("owlv2", "ok", "off: 4x4 grids use the VLM per square (not benchmarked)")

    features = []
    if cfg.enabled and vision_ok and pw_ok:
        features += ["datadome-slider", "geetest-slide", "generic-slider", "turnstile", "checkbox", "px-hold"]
        if names is not None and client.has_model(names):
            features += ["recaptcha-grid", "unknown-wall-vlm"] + (["hcaptcha-vlm"] if cfg.hcaptcha_vlm else [])
    add("features", "ok" if features else "warn", ", ".join(features) or "none")
    return out
