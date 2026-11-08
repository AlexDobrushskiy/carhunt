"""Find and classify a bot wall on a page (all frames, incl. cross-origin iframes).

Two steps: `snapshot(page)` reads what the classifier needs from a live Playwright page (one probe per
frame), `classify(snap)` is pure. `detect(page)` = both; a `static.StaticPage` (saved HTML) works too.

kinds (CaptchaInfo.kind):
  datadome-slider        DataDome captcha iframe (t=fe): "slide right" / puzzle slider      -> solvable
  datadome-blocked       DataDome iframe with t=bv: IP/device banned, nothing to solve       -> hard block
  datadome-interstitial  DataDome "device check" page: resolves itself                       -> wait
  geetest-slide          GeeTest v3/v4 puzzle slider (also its "click to verify" button)     -> solvable
  generic-slider         another slider/puzzle slider (handle + wall words)                  -> best effort
  turnstile              Cloudflare Turnstile checkbox / "Just a moment" managed challenge    -> click / wait
  recaptcha              reCAPTCHA v2 checkbox (stage=checkbox) or image grid (image-challenge)
  hcaptcha               hCaptcha checkbox or image task (image tasks: unsupported by default)
  px-hold                PerimeterX/HUMAN "Press & Hold"                                       -> solvable
  akamai-interstitial    Akamai sec-cpt challenge page                                        -> wait
  hard-block             403-style page with nothing to solve ("Access denied", ...)          -> hard block
  unknown                looks like a wall (captcha words) but no known widget                -> VLM / give up
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

BLOCK_TEXT = re.compile(r"access denied|access is temporarily restricted|zugriff verweigert|acc[eè]s refus[ée]|you have been blocked|vous avez [ée]t[ée] bloqu|"
                        r"request unsuccessful|pardon our interruption|forbidden|sorry, you have been blocked|"
                        r"acesso negado|dost[eę]p zablokowany|error 1020", re.I)
WALL_TEXT = re.compile(r"captcha|verify you are (a )?human|are you a robot|prove your humanity|slide (right|to)|"
                       r"glissez|faites glisser|deslize|schieben|przesu[nń]|press (and|&) hold|i'?m not a robot|"
                       r"pas un robot|kein roboter|just a moment|un instant|checking your browser", re.I)
DD_BLOCK_TEXT = re.compile(r"blocked|bloqu|temporarily restricted|temporairement restreint|acc[eè]s.{0,20}restreint", re.I)

# name -> CSS selector; the probe reports the first *visible* match's box (frame-relative) and presence
PROBES = {
    "dd_slider": ".slider, [class*=slider]",
    "geetest": ".geetest_slider_button, .geetest_btn, .geetest_btn_click, .geetest_canvas_bg, .geetest_radar_tip, .geetest_bg",
    "geetest_done": ".geetest_radar_success, .geetest_lock_success, .geetest_success",
    "px": "#px-captcha",
    "generic_handle": "[class*=slider] [class*=handle], [class*=slider] [class*=button], [class*=slider] [class*=btn], "
                      "[class*=slider][class*=icon], .sliderIcon, [class*=drag][class*=btn], [class*=captcha] [class*=slider]",
}
TOKEN_SEL = '[name="cf-turnstile-response"], [name="g-recaptcha-response"], [name="h-captcha-response"]'

_PROBE_JS = r"""(probes) => {
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const out = {};
  for (const [k, sel] of Object.entries(probes)) {
    let els = []; try { els = [...document.querySelectorAll(sel)]; } catch (e) {}
    const v = els.find(vis), r = v && v.getBoundingClientRect();
    out[k] = {present: els.length > 0, box: v ? {x: r.x, y: r.y, width: r.width, height: r.height} : null};
  }
  return out; }"""
_TEXT_JS = "(n) => document.body ? document.body.innerText.slice(0, n) : ''"
_TOKEN_JS = """(sel) => Math.max(0, ...[...document.querySelectorAll(sel)].map(e => (e.value || '').length))"""


@dataclass
class CaptchaInfo:
    kind: str
    vendor: str
    solvable: bool
    frame: object = None            # Frame holding the widget (None = main frame)
    url: str = ""
    detail: dict = field(default_factory=dict)

    def __repr__(self):
        return f"CaptchaInfo({self.kind}, vendor={self.vendor}, solvable={self.solvable}, detail={self.detail})"


@dataclass
class FrameSnap:
    url: str
    text: str = ""                                  # innerText, first 4000 chars
    probes: dict = field(default_factory=dict)      # PROBES name -> {"present": bool, "box": dict|None}
    box: dict | None = None                         # the iframe element's box in the page (None: main / not laid out)
    box_visible: dict | None = None                 # same, only when the iframe element is visible
    ref: object = None                              # the live Frame (handlers act on it)

    def visible(self, probe: str) -> bool:
        return bool((self.probes.get(probe) or {}).get("box"))

    def present(self, probe: str) -> bool:
        return bool((self.probes.get(probe) or {}).get("present"))


@dataclass
class PageSnap:
    url: str
    title: str
    html_head: str                                  # page.content()[:6000]
    frames: list[FrameSnap]                         # main frame first
    token_len: int = 0
    nav_status: int = 0


def _box(b) -> dict | None:
    return b if b and b["width"] > 2 and b["height"] > 2 else None


def furl(f, page=None) -> str:
    """Frame URL; over CDP Playwright sometimes loses an out-of-process iframe's URL (''), so ask the frame."""
    u = f.url
    if not u and (page is None or f != page.main_frame):
        try:
            u = f.evaluate("location.href")
        except Exception:
            u = ""
    return u


def token_len(page) -> int:
    """Length of a Turnstile / reCAPTCHA / hCaptcha response token on the page (0 = none yet)."""
    if hasattr(page, "static_token_len"):
        return page.static_token_len()
    try:
        return int(page.evaluate(_TOKEN_JS, TOKEN_SEL))
    except Exception:
        return 0


def snapshot(page, status: int | None = None) -> PageSnap:
    """Read everything `classify` needs from a live Playwright page (or a static.StaticPage)."""
    if hasattr(page, "static_snapshot"):
        return page.static_snapshot(status)
    frames = []
    for f in page.frames:
        fs = FrameSnap(url=furl(f, page), ref=f)
        try:
            fs.probes = f.evaluate(_PROBE_JS, PROBES)
        except Exception:
            fs.probes = {}
        try:
            fs.text = f.evaluate(_TEXT_JS, 4000) or ""
        except Exception:
            fs.text = ""
        if f != page.main_frame:
            try:
                el = f.frame_element()
                fs.box = _box(el.bounding_box())
                fs.box_visible = fs.box if fs.box and el.is_visible() else None
            except Exception:
                pass
        frames.append(fs)
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        head = page.content()[:6000]
    except Exception:
        head = ""
    nav = status
    if nav is None:
        try:
            nav = page.evaluate("(performance.getEntriesByType('navigation')[0] || {}).responseStatus || 0")
        except Exception:
            nav = 0
    return PageSnap(page.url, title, head, frames, token_len(page), int(nav or 0))


def detect(page, status: int | None = None) -> CaptchaInfo | None:
    """What wall the page shows, or None for a normal page."""
    return classify(snapshot(page, status))


def classify(s: PageSnap) -> CaptchaInfo | None:
    main = s.frames[0] if s.frames else FrameSnap(s.url)
    # --- DataDome ---
    for f in s.frames:
        u = urlparse(f.url)
        if "captcha-delivery.com" in u.netloc:
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if "/interstitial" in u.path:
                return CaptchaInfo("datadome-interstitial", "datadome", False, f.ref, f.url, dict(box=f.box))
            if q.get("t") == "bv" or (DD_BLOCK_TEXT.search(f.text[:800]) and not f.visible("dd_slider")):
                return CaptchaInfo("datadome-blocked", "datadome", False, f.ref, f.url, dict(t=q.get("t"), box=f.box))
            if "/captcha" in u.path:
                return CaptchaInfo("datadome-slider", "datadome", True, f.ref, f.url, dict(t=q.get("t"), box=f.box))
    m = re.search(r"var dd=\{[^}]*'rt':'(\w)'[^}]*\}", s.html_head)
    if m:
        t = re.search(r"'t':'(\w+)'", m.group(0))
        if t and t.group(1) == "bv":
            return CaptchaInfo("datadome-blocked", "datadome", False, None, s.url, dict(t="bv", note="block page, iframe not loaded"))
        kind = "datadome-interstitial" if m.group(1) == "i" else "datadome-slider"
        return CaptchaInfo(kind, "datadome", kind == "datadome-slider", None, s.url, dict(note="iframe not loaded yet"))

    # --- GeeTest (same-origin widget) ---
    for f in s.frames:
        if f.visible("geetest") and not f.present("geetest_done"):
            return CaptchaInfo("geetest-slide", "geetest", True, f.ref, f.url)

    # --- PerimeterX / HUMAN press & hold ---
    for f in s.frames:
        if f.visible("px"):
            return CaptchaInfo("px-hold", "perimeterx", True, f.ref, f.url)

    # --- Cloudflare ---
    for f in s.frames:
        if "challenges.cloudflare.com" in f.url and f.box and s.token_len < 15:
            return CaptchaInfo("turnstile", "cloudflare", True, f.ref, f.url, dict(box=f.box))
    if re.search(r"just a moment|un instant|einen moment", s.title, re.I) or "cf-chl" in s.html_head or "challenge-platform" in s.html_head:
        return CaptchaInfo("turnstile", "cloudflare", True, None, s.url, dict(note="managed challenge page, widget not visible yet"))

    # --- reCAPTCHA / hCaptcha (a token on the page = already solved) ---
    has_token = s.token_len >= 15
    if not has_token:
        for f in s.frames:
            if re.search(r"(google\.com|recaptcha\.net)/recaptcha/(api2|enterprise)/bframe", f.url):
                b = f.box_visible
                if b and b["height"] > 150:
                    return CaptchaInfo("recaptcha", "google", True, f.ref, f.url, dict(stage="image-challenge", box=b))
        for f in s.frames:
            if re.search(r"(google\.com|recaptcha\.net)/recaptcha/(api2|enterprise)/anchor", f.url) and f.box:
                return CaptchaInfo("recaptcha", "google", True, f.ref, f.url, dict(stage="checkbox"))
        for f in s.frames:
            if "hcaptcha.com" in f.url and "frame=challenge" in f.url:
                b = f.box_visible
                if b and b["height"] > 150:
                    return CaptchaInfo("hcaptcha", "hcaptcha", True, f.ref, f.url, dict(stage="image-challenge", box=b))
        for f in s.frames:
            if "hcaptcha.com" in f.url and "frame=checkbox" in f.url and f.box:
                return CaptchaInfo("hcaptcha", "hcaptcha", True, f.ref, f.url, dict(stage="checkbox"))

    # --- Akamai ---
    if "sec-if-cpt" in s.html_head or "_sec/cp_challenge" in s.html_head:
        return CaptchaInfo("akamai-interstitial", "akamai", False, None, s.url)

    # --- generic slider anywhere ---
    for f in s.frames:
        if f.visible("generic_handle") and WALL_TEXT.search(f.text[:2000]):
            return CaptchaInfo("generic-slider", "unknown", True, f.ref, f.url, dict(handle=f.probes["generic_handle"]["box"]))

    # --- hard block / unknown wall ---
    body = main.text[:3000]
    vendor = _vendor_guess(s.html_head, body)
    if BLOCK_TEXT.search(s.title + " " + body[:1500]) and len(body) < 3000:
        return CaptchaInfo("hard-block", vendor, False, None, s.url, dict(status=s.nav_status, text=body[:200]))
    if s.nav_status in (403, 429) and len(body) < 1500:
        kind = "unknown" if WALL_TEXT.search(body) else "hard-block"
        return CaptchaInfo(kind, vendor, False, None, s.url, dict(status=s.nav_status, text=body[:200]))
    if WALL_TEXT.search(s.title + " " + body[:800]) and len(body) < 1500 and not has_token:
        return CaptchaInfo("unknown", vendor, False, None, s.url, dict(status=s.nav_status, text=body[:200]))
    return None


def _vendor_guess(html: str, body: str) -> str:
    s = (html + body).lower()
    for v, k in [("datadome", "datadome"), ("akamai", "reference #"), ("akamai", "edgesuite"), ("cloudflare", "cloudflare"),
                 ("imperva", "incapsula"), ("perimeterx", "px-captcha")]:
        if k in s:
            return v
    return "unknown"
