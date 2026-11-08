"""Optional local vision model (Ollama): reCAPTCHA tiles, locate an element, name an unknown wall,
last-resort slider gap. Never sends anything off this machine (ollama_url should be localhost / own box).

Default model qwen3.5:4b, ~0.5 s/tile. Tiles go one by one: a whole-grid "which tiles?" prompt is unreliable.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request
from collections.abc import Callable
from typing import Any

MAX_SIDE = 1600
PIXELS = 829_000

# (url, json body or None for GET, timeout s) -> parsed JSON response
Transport = Callable[[str, "dict | None", float], Any]


def urllib_transport(url: str, body: dict | None, timeout: float) -> Any:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data, {"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _grid(w, h):
    """The pixel grid a "grid"-coordinate model answers in (e.g. qwen2.5vl via Ollama): images
    under ~0.83 MP are upscaled to that size (28-px patches) and boxes come back in the upscaled grid."""
    sc = max(1.0, (PIXELS / (w * h)) ** 0.5)
    if sc == 1.0:
        return w, h
    return max(28, round(w * sc / 28) * 28), max(28, round(h * sc / 28) * 28)


# How a model family reports positions: "grid" = pixels of the grid it saw (see _grid),
# "norm" = 0..1000 relative to the image (Qwen3-VL family).
COORDS = {"qwen2.5vl": "grid"}


def coords_of(model: str) -> str:
    m = model.split(":")[0]
    return COORDS.get(m, "norm" if m.startswith("qwen3") else "grid")


def _boxes(text: str) -> list[tuple[float, float, float, float]]:
    """[x1, y1, x2, y2] boxes in the model's answer (JSON or loose)."""
    out = []
    for m in re.finditer(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text):
        x1, y1, x2, y2 = map(float, m.groups())
        if x2 > x1 and y2 > y1:
            out.append((x1, y1, x2, y2))
    return out


class Ollama:
    def __init__(self, url: str = "http://127.0.0.1:11434", model: str = "qwen3.5:4b",
                 transport: Transport | None = None, timeout: float = 180):
        self.url, self.model, self.timeout = url.rstrip("/"), model, timeout
        self.transport = transport or urllib_transport

    @classmethod
    def from_config(cls, cfg=None, transport: Transport | None = None) -> Ollama:
        if cfg is None:
            from .config import load
            cfg = load()
        return cls(cfg.ollama_url, cfg.model, transport)

    # --- server state ---
    def models(self) -> list[str] | None:
        """Pulled model names, or None when the server does not answer."""
        try:
            return [m["name"] for m in self.transport(self.url + "/api/tags", None, 2)["models"]]
        except Exception:
            return None

    def has_model(self, names: list[str] | None = None) -> bool:
        names = self.models() if names is None else names
        want = self.model if ":" in self.model else self.model + ":latest"
        return bool(names) and want in names

    def available(self) -> bool:
        return self.has_model()

    # --- asking ---
    def ask(self, img, prompt: str) -> tuple[str, float, float]:
        """(answer, kx, ky): multiply a "grid"-model x / y by kx / ky to get img pixels."""
        import cv2
        h, w = img.shape[:2]
        if max(h, w) > MAX_SIDE:  # keeps the upload small; the model rescales anyway
            s = MAX_SIDE / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        _, png = cv2.imencode(".png", img)
        body = {"model": self.model, "prompt": prompt, "images": [base64.b64encode(png.tobytes()).decode()],
                "stream": False, "think": False, "options": {"temperature": 0}}
        text = self.transport(self.url + "/api/generate", body, self.timeout)["response"]
        sh, sw = img.shape[:2]
        gw, gh = _grid(sw, sh)
        return text, w / gw, h / gh

    def ask_text(self, img, prompt: str) -> str:
        return self.ask(img, prompt)[0]

    def map_point(self, x: float, y: float, img, kx: float, ky: float) -> tuple[float, float]:
        if coords_of(self.model) == "norm":
            h, w = img.shape[:2]
            return x * w / 1000, y * h / 1000
        return x * kx, y * ky

    def locate(self, img, what: str) -> tuple[float, float, float, float] | None:
        """Bounding box (x1, y1, x2, y2) of `what` in img pixels, or None."""
        text, kx, ky = self.ask(img, f"Locate {what} in this image. Answer with JSON only: "
                                     '[{"bbox_2d": [x1, y1, x2, y2], "label": "..."}]')
        b = _boxes(text)
        if not b:
            return None
        x1, y1 = self.map_point(b[0][0], b[0][1], img, kx, ky)
        x2, y2 = self.map_point(b[0][2], b[0][3], img, kx, ky)
        return (x1, y1, x2, y2)

    def points(self, img, prompt: str) -> list[tuple[float, float]]:
        text, kx, ky = self.ask(img, prompt)
        return [self.map_point(float(m.group(1)), float(m.group(2)), img, kx, ky)
                for m in re.finditer(r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]", text)]

    def classify(self, img) -> dict:
        """What kind of challenge a screenshot shows: {"captcha", "type", "instruction", "raw"}."""
        text = self.ask_text(img, "This is a screenshot of a web page. Is a CAPTCHA or bot check shown? Answer with JSON only: "
                                  '{"captcha": true|false, "type": "slider-puzzle|slider|checkbox|press-and-hold|image-grid|text|blocked|other", '
                                  '"instruction": "the challenge text, verbatim"}')
        m = re.search(r"\{.*\}", text, re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:
            d = {}
        d["raw"] = text[:300]
        return d

    def tile_yes(self, tile, target: str) -> bool:
        """One reCAPTCHA tile: does it show the target? (upscaled to 336 px: small tiles answered worse)"""
        import cv2
        big = cv2.resize(tile, (336, 336), interpolation=cv2.INTER_CUBIC)
        a = self.ask_text(big, f"Does this photo show {target} (even partly)? Answer yes or no.")
        return a.strip().lower().startswith("yes")

    def gap_target(self, shot, pb: dict, bgb: dict, f: float) -> float | None:
        """Slider fallback: CSS px the piece must travel, from where the model sees the slot (3/12 within 4 px)."""
        b = self.locate(shot, "the empty puzzle-piece shaped slot (the darker or outlined hole where the loose piece must go), "
                              "not the loose piece itself on the left")
        if not b:
            return None
        x1 = b[0] / f + bgb["x"]
        if x1 <= pb["x"] + pb["width"] * 0.5:
            return None
        return x1 - pb["x"]
