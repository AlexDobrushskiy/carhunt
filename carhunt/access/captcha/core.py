"""solve(page): detect the wall, run the matching handler, verify, log. Never notifies anyone.

Rules (each one cost a block or a manual solve once):
- Solve DataDome in plain-chrome, never in a Playwright-launched browser (MCP lane / identity MCP): the
  correct slide there got "Access is temporarily restricted" (10-26). solve() refuses with `wrong-route`.
- Never open a second browser on a site whose captcha is showing or was just solved: solve in the tab
  that shows it and keep using that browser (the owner had to solve one twice, 10-26). After a solve,
  close the tab with `plain-chrome close` so the new datadome/_abck cookie reaches the trust-cookie jar.
- A datadome cookie in a profile does not prove a solve: only the page loading without the wall does.
- At most `max_attempts` (2) tries per run and `site_budget` (6) per site per 6 h: every failed try
  raises the site's bot score (~10 test hits/h got an IP flagged, 10-25).
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import human, inputs
from .attempts import AttemptLog
from .config import CaptchaConfig
from .detect import CaptchaInfo, detect, token_len

HARD = {"datadome-blocked", "hard-block"}
WAIT = {"datadome-interstitial", "akamai-interstitial"}
PLAYWRIGHT_ROUTES = {"lane", "identity"}   # browsers launched by the Playwright MCP server (serve)
OK = {"solved", "no-captcha"}


@dataclass
class Result:
    # solved | failed | hard-block | unknown-type | unsupported | no-captcha | budget | error
    # | dry-run | disabled | wrong-route
    status: str
    kind: str | None = None
    vendor: str | None = None
    attempts: int = 0
    duration: float = 0.0
    input: str = "cdp"
    route: str = "plain"
    screenshot: str | None = None
    message: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Ctx:
    """What a handler gets besides the page and the wall."""
    page: object
    mouse: object
    shots: Path | None
    cfg: CaptchaConfig
    vlm: object | None          # Ollama client when enabled + reachable + model pulled
    owl: bool                   # OWLv2 allowed and installed


def site_of(url: str) -> str:
    host = urlparse(url).hostname or ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _safe_detect(page):
    err = None
    for _ in range(3):
        try:
            return detect(page), None
        except Exception as e:
            err = e
            time.sleep(0.7)
    return "error", str(err)[:200]


def wait_outcome(page, before: CaptchaInfo, timeout=15.0):
    """Poll until the wall is gone (solved), turned into a hard block, or is still there after `timeout`."""
    t0 = time.time()
    last = before
    while time.time() - t0 < timeout:
        time.sleep(0.7)
        info, _ = _safe_detect(page)
        if info == "error":
            continue  # navigating
        if info is None:
            time.sleep(1.0)  # let a reload settle, then confirm
            info2, _ = _safe_detect(page)
            if info2 is None:
                return "solved", None
            if info2 == "error":
                continue
            info = info2
        last = info
        if info.kind in HARD:
            return "hard-block", info
        if info.kind == "datadome-slider":
            try:
                if info.frame and info.frame.locator("button.retryLink").first.is_visible():
                    return "failed", info
            except Exception:
                pass
            if before.kind == "datadome-slider" and time.time() - t0 > 8:
                return "failed", info
    return "failed", last


# ---------------- handlers: each does ONE attempt and returns a dict of what it did ----------------

def _slider(ctx: Ctx, info: CaptchaInfo, shots: Path | None) -> dict:
    from .discover import discover, known_parts
    from .slider import Slider
    page, mouse = ctx.page, ctx.mouse
    f = info.frame or page.main_frame
    if info.vendor == "geetest":
        # v3/v4 start with a "click to verify" button; the puzzle opens after it
        for sel in (".geetest_radar_tip", ".geetest_btn_click"):
            try:
                loc = f.locator(sel).first
                if loc.count() and loc.is_visible() and not f.locator(".geetest_slider_button, .geetest_track").first.is_visible():
                    b = loc.bounding_box()
                    mouse.click(b["x"] + b["width"] * random.uniform(0.3, 0.6), b["y"] + b["height"] * random.uniform(0.35, 0.65))
                    time.sleep(random.uniform(2.0, 3.0))
                    break
            except Exception:
                pass
    if info.vendor == "datadome":
        # an expired / failed DataDome challenge shows a RETRY button; a person clicks it and gets a fresh slider
        try:
            retry = f.locator("button.retryLink").first
            if retry.count() and retry.is_visible():
                b = retry.bounding_box()
                mouse.click(b["x"] + b["width"] * random.uniform(0.3, 0.7), b["y"] + b["height"] * random.uniform(0.3, 0.7))
                time.sleep(random.uniform(2.0, 3.0))
        except Exception:
            pass
    parts = known_parts(f, info.vendor)
    found = None
    if parts is None and info.vendor == "datadome":
        return {"error": "DataDome widget without a known slider (new layout?)", "html_classes": _classes(f)}
    if parts is None:
        parts, found = discover(f)
    if parts is None:
        return {"error": "no slider handle found", "discover": found}
    time.sleep(human.pause(0.4, 1.0))  # look at the puzzle first
    rep = Slider(page, mouse, parts, shots, vlm=ctx.vlm.gap_target if ctx.vlm else None).run()
    return {"method": rep.method, "target_px": rep.target_px, "ratio": rep.ratio, "final_err_px": rep.final_err_px,
            "gap_margin": rep.gap_margin, "notes": rep.notes, "parts": [parts.handle, parts.bg, parts.piece, parts.track]}


def _classes(f):
    try:
        return f.evaluate("[...new Set([...document.querySelectorAll('[class]')].filter(e => e.getBoundingClientRect().width > 0)"
                          ".map(e => String(e.className).slice(0, 40)))].slice(0, 60)")
    except Exception:
        return None


def _checkbox(ctx: Ctx, info: CaptchaInfo, shots: Path | None) -> dict:
    page, mouse, f = ctx.page, ctx.mouse, info.frame
    if info.kind == "turnstile":
        if f is None:
            return {"waited": True}
        b = info.detail.get("box") or f.frame_element().bounding_box()
        x, y = b["x"] + min(30, b["width"] * 0.12) + random.uniform(-4, 4), b["y"] + b["height"] / 2 + random.uniform(-4, 4)
        mouse.click(x, y)
        return {"clicked": [round(x), round(y)]}
    if info.detail.get("stage") == "image-challenge":
        return _challenge(ctx, info.kind, f, shots)
    sel = "#recaptcha-anchor" if info.kind == "recaptcha" else "#checkbox"
    bb = f.locator(sel).first.bounding_box()
    x, y = bb["x"] + bb["width"] * random.uniform(0.3, 0.7), bb["y"] + bb["height"] * random.uniform(0.3, 0.7)
    mouse.click(x, y)
    out = {"clicked": [round(x), round(y)]}
    time.sleep(random.uniform(2.5, 3.5))
    new, _ = _safe_detect(page)
    if new and new != "error" and new.detail.get("stage") == "image-challenge":
        out.update(_challenge(ctx, new.kind, new.frame, shots))
    return out


def _challenge(ctx: Ctx, kind: str, f, shots: Path | None) -> dict:
    ok = lambda: token_len(ctx.page) >= 15  # noqa: E731
    if kind == "hcaptcha":
        if not (ctx.cfg.hcaptcha_vlm and ctx.vlm):
            return {"method": "hcaptcha", "outcome": "unsupported",
                    "notes": ["hCaptcha image task: VLM path is opt-in (browsers.captcha.hcaptcha_vlm, 0/3 measured)"]}
        from . import hcaptcha
        rep = hcaptcha.solve_challenge(ctx.page, ctx.mouse, f, shots, ok, vlm=ctx.vlm)
        rep["method"] = "hcaptcha-vlm"
        return rep
    if ctx.vlm is None and not ctx.owl:
        return {"method": "recaptcha-grid", "outcome": "unsupported",
                "notes": ["reCAPTCHA image grid needs the local VLM (Ollama + browsers.captcha.model) or OWLv2"]}
    from . import recaptcha
    rep = recaptcha.solve_grid(ctx.page, ctx.mouse, f, shots, ok, vlm=ctx.vlm, owl=ctx.owl)
    rep["method"] = "recaptcha-grid"
    return rep


def _hold(ctx: Ctx, info: CaptchaInfo, shots: Path | None) -> dict:
    mouse = ctx.mouse
    f = info.frame or ctx.page.main_frame
    b = f.locator("#px-captcha").first.bounding_box()
    x, y = b["x"] + b["width"] * random.uniform(0.35, 0.65), b["y"] + b["height"] * random.uniform(0.35, 0.65)
    mouse.place()
    mouse.reach(x, y)
    time.sleep(human.pause(0.15, 0.4))
    mouse.down()
    t0 = time.time()
    while time.time() - t0 < 15:  # hold with tremor until the widget clears
        mouse.play(human.segment(mouse.x, mouse.y, x + random.gauss(0, 0.8), y + random.gauss(0, 0.8), random.uniform(0.3, 0.6), tremor=0.2))
        try:
            if not f.locator("#px-captcha").first.is_visible():
                break
            if re.search(r"verified|vérifi|verificad", f.locator("#px-captcha").first.inner_text(timeout=500), re.I):
                break
        except Exception:
            break
    held = time.time() - t0
    time.sleep(human.pause(0.1, 0.3))
    mouse.up()
    return {"held_s": round(held, 1)}


def _unknown(ctx: Ctx, info: CaptchaInfo, shots: Path | None) -> dict:
    """Let the local VLM name it; act only on the simple shapes (checkbox, slider-to-end)."""
    if ctx.vlm is None:
        return {"error": "unknown wall and no local VLM"}
    from . import vision
    from .discover import discover
    shot = vision.decode_png(ctx.page.screenshot(scale="css"))[:, :, :3]
    c = ctx.vlm.classify(shot)
    out = {"vlm": c}
    if c.get("type") == "checkbox":
        b = ctx.vlm.locate(shot, "the captcha checkbox")
        if b:
            ctx.mouse.click((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            out["clicked"] = b
    elif c.get("type") in ("slider", "slider-puzzle"):
        parts, _ = discover(info.frame or ctx.page.main_frame)
        if parts:
            out.update(_slider(ctx, CaptchaInfo("generic-slider", "unknown", True, info.frame), shots))
        else:
            out["error"] = "slider seen by the VLM but no DOM handle found"
    else:
        out["error"] = f"unknown wall ({c.get('type')}); nothing safe to do"
    return out


HANDLERS = {"datadome-slider": _slider, "geetest-slide": _slider, "generic-slider": _slider,
            "turnstile": _checkbox, "recaptcha": _checkbox, "hcaptcha": _checkbox, "px-hold": _hold, "unknown": _unknown}


def _wait_frame(page, info, timeout=10):
    """DataDome's iframe content loads after the block page: wait until its widget renders."""
    if info.kind == "datadome-slider":
        t0 = time.time()
        while time.time() - t0 < timeout:
            fr = info.frame
            if fr is not None:
                try:
                    if fr.evaluate("document.readyState") == "complete" and fr.evaluate(
                            "!!document.querySelector('canvas, img, [class*=slider]')"):
                        time.sleep(1.0)
                        return info
                except Exception:
                    pass
            time.sleep(0.5)
            new, _ = _safe_detect(page)
            if new and new != "error":
                info = new
    return info


def _vlm_for(cfg: CaptchaConfig, use_vlm: bool, transport=None):
    if not (use_vlm and cfg.enabled):
        return None
    from .vlm import Ollama
    c = Ollama(cfg.ollama_url, cfg.model, transport)
    return c if c.available() else None


def _owl_for(cfg: CaptchaConfig) -> bool:
    if not cfg.owlv2:
        return False
    from .grid import owl_installed
    return owl_installed()


def solve(page, *, route: str = "plain", input: str = "cdp", port: int | None = None, max_attempts: int | None = None,
          site: str | None = None, force: bool = False, use_vlm: bool = True, info: CaptchaInfo | None = None,
          dry_run: bool = False, cfg: CaptchaConfig | None = None, log: AttemptLog | None = None,
          vlm=None, outcome_timeout: float = 15.0) -> Result:
    """Solve whatever wall `page` shows (a Playwright Page attached over CDP).

    route: plain | lane | identity (identity-a… count as identity) | cdp: which browser the tab lives in.
    input: "cdp" (default) or "macos" (native events to the Chrome process; needs port).
    force: ignore the per-site budget and the DataDome route rule (the owner said so).
    vlm: an Ollama client to use instead of building one from config (tests)."""
    from .config import load, shots_root
    cfg = cfg or load()
    log = log or AttemptLog()
    route_kind = "identity" if route.startswith("identity") else route
    max_attempts = max_attempts or cfg.max_attempts
    t0 = time.time()
    url = page.url
    site = site or site_of(url)
    info = info or detect(page)
    t_settle = time.time()
    while info is not None and info.kind == "unknown" and time.time() - t_settle < 8 and not dry_run:
        time.sleep(1.0)   # widgets load late (iframes): give a known one the chance to show up
        new, _ = _safe_detect(page)
        if new != "error":
            info = new
    run_dir = shots_root() / time.strftime("%Y%m%d-%H%M%S") / site if cfg.screenshots else None
    res = Result("no-captcha", input=input, route=route)
    if info is None:
        res.duration = round(time.time() - t0, 2)
        return res
    res.kind, res.vendor = info.kind, info.vendor

    def finish(status, msg="", **detail):
        res.status, res.message, res.duration = status, msg, round(time.time() - t0, 2)
        res.detail.update(detail)
        if run_dir is not None and status not in ("dry-run", "disabled", "budget", "wrong-route"):
            try:
                run_dir.mkdir(parents=True, exist_ok=True)
                p = run_dir / f"final-{status}.jpg"
                page.screenshot(path=str(p), type="jpeg", quality=70)
                res.screenshot = str(p)
            except Exception:
                pass
        return res

    if not cfg.enabled:
        return finish("disabled", "captcha solving is off (config browsers.captcha.enabled: false)")
    if info.kind == "datadome-slider" and route_kind in PLAYWRIGHT_ROUTES and not force:
        return finish("wrong-route", "DataDome wall in a Playwright-launched browser: a correct slide there gets "
                                     "'Access temporarily restricted'. Open the URL in plain-chrome and solve there "
                                     "(and keep that browser: don't open a second one on this site).")
    if info.kind in WAIT or (info.kind == "turnstile" and info.frame is None):
        if dry_run:
            return finish("dry-run", "interstitial: would wait up to 25 s", info=repr(info))
        out, new = wait_outcome(page, info, timeout=25)
        log.record(site, url, info.kind, input, "wait", out, time.time() - t0, 0)
        if out == "solved":
            return finish("solved", "interstitial cleared by itself")
        if new is None or new.kind == info.kind:
            return finish("failed", "interstitial did not clear in 25 s")
        info = new
        res.kind, res.vendor = info.kind, info.vendor
    if info.kind in HARD:
        log.record(site, url, info.kind, input, "-", "hard-block", time.time() - t0, 0, info.detail)
        return finish("hard-block", "blocked, nothing to solve (IP/device ban). Retry later or from another IP/profile.",
                      **{k: v for k, v in info.detail.items() if k != "box"})
    if info.kind == "hcaptcha" and info.detail.get("stage") == "image-challenge" and not cfg.hcaptcha_vlm:
        log.record(site, url, info.kind, input, "-", "unsupported", time.time() - t0, 0)
        return finish("unsupported", "hCaptcha image task: not solved locally (opt-in browsers.captcha.hcaptcha_vlm; 0/3 measured)")
    handler = HANDLERS.get(info.kind)
    if handler is None:
        return finish("unknown-type", f"no handler for {info.kind}")
    if not force:
        used = log.recent(site, cfg.site_window_h * 3600)
        if used >= cfg.site_budget:
            return finish("budget", f"{used} attempts on {site} in the last {cfg.site_window_h:g} h; not trying again now")
    if dry_run:
        return finish("dry-run", "detected only", info=repr(info))

    ctx = Ctx(page, None, run_dir, cfg, vlm if vlm is not None else _vlm_for(cfg, use_vlm), _owl_for(cfg))
    for n in range(1, max_attempts + 1):
        ta = time.time()
        info = _wait_frame(page, info)
        if ctx.mouse is None:
            ctx.mouse = inputs.make(page, input, port)
        try:
            did = handler(ctx, info, run_dir / f"attempt{n}" if run_dir else None)
        except Exception as e:
            did = {"error": f"{type(e).__name__}: {e}"[:300]}
        res.attempts = n
        if did.get("error") and not did.get("method"):
            log.record(site, url, info.kind, input, "-", "error", time.time() - ta, n, did)
            return finish("unknown-type" if "no slider" in did["error"] or "unknown" in did["error"] else "error",
                          did["error"], **{f"attempt{n}": did})
        if did.get("outcome") == "unsupported":
            log.record(site, url, info.kind, input, did.get("method", info.kind), "unsupported", time.time() - ta, n, did)
            return finish("unsupported", "; ".join(did.get("notes", [])) or "unsupported challenge", **{f"attempt{n}": did})
        out, new = wait_outcome(page, info, timeout=outcome_timeout)
        log.record(site, url, info.kind, input, did.get("method", info.kind), out, time.time() - ta, n, did)
        res.detail[f"attempt{n}"] = did
        if out == "solved":
            return finish("solved")
        if out == "hard-block":
            return finish("hard-block", "the wall turned into a hard block after the attempt", after=new.kind)
        if new is None or n == max_attempts:
            break
        info = new
        time.sleep(random.uniform(1.5, 3.5))  # a person re-reads the new puzzle
    return finish("failed", f"still blocked after {res.attempts} attempt(s)")
