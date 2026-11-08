"""Generic slider / puzzle-slider engine, shared by the DataDome, GeeTest and generic handlers.

Closed loop, like a person: grab the handle, pull it a bit, look how far the piece moved (handle and
piece often move at different rates), then slide to the gap with an overshoot, look again, nudge if
needed, release.

Gap finding uses the cleanest pixels available (offline, 32 GeeTest v3 puzzles: 32/32 within 3 px):
  1. the puzzle's own images (canvas pixels, <img> / background-image files) with the piece's alpha;
  2. screenshots: the piece's shape is recovered from how the pixels move during the first pull
     (rigid motion: piece pixels move with the handle, background pixels stay).
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import human, vision


@dataclass
class Parts:
    frame: object
    handle: str
    bg: str | None = None      # puzzle background (with the gap)
    piece: str | None = None   # the moving piece
    track: str | None = None   # slider rail (for plain "slide to the end" sliders)
    goal: str | None = None    # drop zone the handle must land on (DataDome "slide right" box)


@dataclass
class DragReport:
    method: str = ""            # how the target was found: canvas / image / screenshot / track-end / vlm
    target_px: float | None = None
    ratio: float | None = None
    final_err_px: float | None = None
    gap_margin: float | None = None
    notes: list = field(default_factory=list)


def _box(frame, sel):
    if not sel: return None
    try:
        loc = frame.locator(sel).first
        if loc.count() == 0: return None
        b = loc.bounding_box(timeout=2000)
        return b if b and b["width"] > 1 and b["height"] > 1 else None
    except Exception:
        return None


_IMG_JS = r"""(el) => {
  if (el.tagName === 'CANVAS') { try { return {kind: 'canvas', data: el.toDataURL('image/png'), w: el.width, h: el.height}; }
                                 catch (e) { return {kind: 'tainted'}; } }
  if (el.tagName === 'IMG') return {kind: 'img', src: el.currentSrc || el.src, w: el.naturalWidth, h: el.naturalHeight};
  const bi = getComputedStyle(el).backgroundImage; const m = bi && bi.match(/url\(["']?(.*?)["']?\)/);
  if (m) return {kind: 'bgimg', src: m[1], size: getComputedStyle(el).backgroundSize, pos: getComputedStyle(el).backgroundPosition};
  return {kind: 'none'}; }"""


def element_image(page, frame, sel):
    """The element's own pixels (with alpha when it has some), or None. Returns (img, info)."""
    try:
        info = frame.locator(sel).first.evaluate(_IMG_JS)
    except Exception:
        return None, {"kind": "error"}
    try:
        if info["kind"] == "canvas":
            return vision.decode_data_url(info["data"]), info
        if info["kind"] in ("img", "bgimg") and info.get("src"):
            src = info["src"]
            if src.startswith("data:"): return vision.decode_data_url(src), info
            r = page.context.request.get(src, headers={"referer": frame.url})
            if r.ok: return vision.decode_png(r.body()), info
    except Exception as e:
        info["error"] = str(e)[:120]
    return None, info


def _bg_fills(info, box, img) -> bool:
    """True if a CSS background image is drawn exactly over its element (scaled, not cropped or offset)."""
    if info.get("pos") not in ("0% 0%", "0px 0px", "left top", "0% 0px", "0px 0%"): return False
    ih, iw = img.shape[:2]
    same_aspect = abs(iw / ih - box["width"] / box["height"]) < 0.02
    size = (info.get("size") or "auto").strip()
    if size in ("100% 100%",): return True
    if size in ("100% auto", "100%", "auto 100%", "cover", "contain"): return same_aspect
    if size == "auto": return abs(iw - box["width"]) < 1.5 and abs(ih - box["height"]) < 1.5
    m = re.fullmatch(r"([\d.]+)px(?: ([\d.]+)px)?", size)
    if m:
        w = float(m.group(1)); h = float(m.group(2)) if m.group(2) else w * ih / iw
        return abs(w - box["width"]) < 1.5 and abs(h - box["height"]) < 1.5
    return False


def _shot(page, box, scale="device"):
    png = page.screenshot(clip=dict(x=box["x"], y=box["y"], width=box["width"], height=box["height"]), scale=scale)
    return vision.decode_png(png)[:, :, :3]


class Slider:
    def __init__(self, page, mouse, parts: Parts, shots: Path | None = None, vlm=None, screenshot_only: bool = False):
        """vlm: optional fallback `(shot, piece_box, bg_box, scale) -> target px | None` (Ollama.gap_target).
        screenshot_only: skip the puzzle's own images (debugging the motion path)."""
        self.page, self.mouse, self.p, self.shots, self.vlm = page, mouse, parts, shots, vlm
        self.screenshot_only = screenshot_only
        self.r = DragReport()

    def _save(self, name, img):
        if self.shots is not None and img is not None:
            self.shots.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(self.shots / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])

    # ---- piece model: where the piece is and what it looks like, in screenshot pixels ("S-space") ----
    def _model_from_images(self, bgb, pb, shotA, fS):
        """Piece mask + gap from the puzzle's own images (canvas / <img> pixels with alpha)."""
        bg_img, bi = element_image(self.page, self.p.frame, self.p.bg)
        pc_img, pi = element_image(self.page, self.p.frame, self.p.piece)
        self.r.notes.append(f"bg:{bi.get('kind')} piece:{pi.get('kind')}")
        if bg_img is None or pc_img is None or pc_img.ndim < 3 or pc_img.shape[2] < 4: return None
        for k, b, im in ((bi, bgb, bg_img), (pi, pb, pc_img)):
            if k["kind"] == "bgimg" and not _bg_fills(k, b, im):
                self.r.notes.append(f"{k['kind']} size {k.get('size')} pos {k.get('pos')}: not a plain fill")
                return None  # sprites / offset backgrounds: use screenshots instead
        fc = bg_img.shape[1] / bgb["width"]               # bg image px per CSS px
        fp = pc_img.shape[1] / pb["width"]                # piece image px per CSS px
        _, mask, x0, y0 = vision.piece_from_rgba(pc_img)
        if abs(fc - fp) > 0.02:
            k = fc / fp
            mask = cv2.resize(mask.astype(np.uint8), None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST) > 0
            x0, y0 = x0 * k, y0 * k
        px = (pb["x"] - bgb["x"]) * fc + x0
        py = (pb["y"] - bgb["y"]) * fc + y0
        bg = bg_img[:, :, :3] if bg_img.ndim == 3 else cv2.cvtColor(bg_img, cv2.COLOR_GRAY2BGR)
        if bg_img.ndim == 3 and bg_img.shape[2] == 4:  # transparent areas -> white
            a = bg_img[:, :, 3:4] / 255.0
            bg = (bg * a + 255 * (1 - a)).astype(np.uint8)
        g = vision.find_gap(bg, mask, int(round(py)), x_min=int(px + mask.shape[1] * 0.6))
        self.r.method, self.r.gap_margin = bi["kind"], round(g.margin, 2)
        self._save("bg", bg)
        k = fS / fc  # -> S-space
        mS = cv2.resize(mask.astype(np.uint8), None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST) > 0
        return dict(mask=mS, x=px * k, y=py * k, target=(g.x - px) / fc)

    def _model_from_motion(self, A, B):
        """Piece shape from a rigid motion between two screenshots: piece pixels moved by some shift s,
        background pixels stayed. Returns the model in S-space + the shift found."""
        ga = cv2.cvtColor(A, cv2.COLOR_BGR2GRAY).astype(np.int16)
        gb = cv2.cvtColor(B, cv2.COLOR_BGR2GRAY).astype(np.int16)
        W = ga.shape[1]
        changed = np.abs(ga - gb) > 22
        if changed.sum() < 80:
            self.r.notes.append("nothing moved on the probe pull"); return None
        best = (0, 0, None)
        for sh in range(2, W // 2):
            hit = changed[:, :W - sh] & (np.abs(ga[:, :W - sh] - gb[:, sh:]) < 12)
            n = int(hit.sum())
            if n > best[0]: best = (n, sh, hit)
        n, sh, hit = best
        if n < 60:
            self.r.notes.append("probe motion not rigid"); return None
        # keep only pixels whose moved copy is also explained the other way round: drops background
        # that merely looks alike at x and x+sh (flat areas next to the piece)
        back = changed[:, sh:] & (np.abs(gb[:, sh:] - ga[:, :W - sh]) < 12)   # B pixels = shifted A pixels, at x-sh
        m = np.zeros(ga.shape, np.uint8); m[:, :W - sh] = hit & back & changed[:, sh:]
        m = vision.piece_hull(m)
        if m is None:
            self.r.notes.append("probe motion: no compact piece"); return None
        ys, xs = np.where(m)
        x0, y0 = xs.min(), ys.min()
        mask = m[y0:ys.max() + 1, x0:xs.max() + 1]
        self._save("mask", mask.astype(np.uint8) * 255)
        g = vision.find_gap(A, mask, int(y0), x_min=int(x0 + mask.shape[1] * 0.6))
        self.r.method, self.r.gap_margin = "screenshot", round(g.margin, 2)
        return dict(mask=mask, x=float(x0), y=float(y0), target_S=float(g.x - x0), shift=sh)

    def _measure(self, model, bgb, pb, fS, shotA):
        """Piece displacement in CSS px since the start: DOM box if it moves, else find it in a screenshot."""
        if pb:
            b = self._settled_box(self.p.piece)
            if b and abs(b["x"] - pb["x"]) > 0.5: return b["x"] - pb["x"]
        if model is None or bgb is None: return None
        S = _shot(self.page, bgb)
        mask = model["mask"]; h, w = mask.shape
        x0, y0 = int(round(model["x"])), int(round(model["y"]))
        tmpl = shotA[y0:y0 + h, x0:x0 + w]
        if tmpl.shape[:2] != mask.shape: return None
        band = S[max(0, y0 - 3): y0 + h + 3]
        x, y, score = vision.locate(tmpl, band, mask)
        if score < 0.6: return None
        return (x - x0) / fS

    def _settled_box(self, sel, timeout=0.6):
        """Element box once it stopped moving (pieces often trail the handle through a CSS transition)."""
        prev, t0 = _box(self.p.frame, sel), time.time()
        while prev and time.time() - t0 < timeout:
            time.sleep(0.04)
            cur = _box(self.p.frame, sel)
            if not cur or abs(cur["x"] - prev["x"]) < 0.3: return cur
            prev = cur
        return prev

    def _handle_x(self):
        b = self._settled_box(self.p.handle)
        return b["x"] if b else None

    def run(self) -> DragReport:
        P, m = self.p, self.mouse
        hb = _box(P.frame, P.handle)
        if not hb: raise RuntimeError("slider handle not found")
        bgb, pb, tb = _box(P.frame, P.bg), _box(P.frame, P.piece), _box(P.frame, P.track)
        gb = _box(P.frame, P.goal)
        handle_mode = gb is not None and not (bgb and pb)   # no puzzle: the handle itself must hit the goal
        shotA = fS = model = None
        target = None                      # CSS px the piece must travel
        if bgb:
            shotA = _shot(self.page, bgb); fS = shotA.shape[1] / bgb["width"]
            self._save("before", shotA)
            if pb and not self.screenshot_only:
                try:
                    model = self._model_from_images(bgb, pb, shotA, fS)
                    if model: target = model["target"]
                except Exception as e:
                    self.r.notes.append(f"image path failed: {type(e).__name__}: {e}"[:160])

        gx = hb["x"] + hb["width"] * random.uniform(0.35, 0.65)
        gy = hb["y"] + hb["height"] * random.uniform(0.35, 0.65)
        m.place()
        m.reach(gx, gy)
        time.sleep(human.pause(0.12, 0.35))
        m.down()
        time.sleep(human.pause(0.08, 0.2))
        # some widgets shift the piece on press (GeeTest v4: -4 px): measure it, the mapping is affine
        d0 = 0.0
        if pb and not handle_mode:
            b0 = self._settled_box(P.piece)
            if b0: d0 = b0["x"] - pb["x"]

        # probe pull: learn the handle->piece ratio (and, without images, the piece's shape)
        pull = min(max(0.35 * target, 15), 45) if target else random.uniform(26, 38)
        m.play(human.drag_steps(gx, gy, gx + pull, gy, random.uniform(0.18, 0.32)))
        time.sleep(human.pause(0.12, 0.25))
        pulled = m.x - gx
        ratio = None
        if bgb and model is None:
            shotB = _shot(self.page, bgb); self._save("probe", shotB)
            mm = self._model_from_motion(shotA, shotB)
            if mm:
                model = mm
                target = mm["target_S"] / fS
                ratio = (mm["shift"] / fS) / pulled
        if handle_mode:
            hx = self._handle_x()
            if hx is not None and hx - hb["x"] > 1: ratio = (hx - hb["x"]) / pulled
            target = (gb["x"] + gb["width"] / 2) - (hb["x"] + hb["width"] / 2) + random.uniform(-2.5, 2.5)
            self.r.method = "goal"
        if ratio is None and not handle_mode:
            d = self._measure(model, bgb, pb, fS, shotA)
            if d is not None and d - d0 > 1: ratio = (d - d0) / pulled
        if ratio is None or not 0.2 < ratio < 5:
            self.r.notes.append(f"ratio unknown ({ratio}); assuming 1")
            ratio = 1.0
        self.r.ratio = round(ratio, 3)
        if d0: self.r.notes.append(f"piece offset on press {d0:+.1f}px")

        if target is None and bgb and self.vlm:
            try:
                target = self.vlm(shotA, pb or hb, bgb, fS)
                if target is not None: self.r.method = "vlm"
            except Exception as e:
                self.r.notes.append(f"vlm failed: {e}"[:120])
        if target is None:
            # plain "slide to the end" slider
            end = (tb["x"] + tb["width"]) if tb else (bgb["x"] + bgb["width"] if bgb else hb["x"] + 300)
            ratio = 1.0
            target = (end - hb["x"] - hb["width"]) + random.uniform(2, 6)
            self.r.method = self.r.method or "track-end"
        self.r.target_px = round(float(target), 1)

        # main stroke: handle distance = piece distance / ratio, with overshoot + correction
        m.play(human.drag(m.x, m.y, gx + (target - d0) / ratio, gy))
        # look again; nudge if the piece is off by more than ~1.5 px (only with a trusted measurement)
        if handle_mode or model is not None or (pb and self.r.method != "track-end"):
            for _ in range(2):
                time.sleep(human.pause(0.08, 0.18))
                if handle_mode:
                    hx = self._handle_x(); d = None if hx is None else hx - hb["x"]
                else:
                    d = self._measure(model, bgb, pb, fS, shotA)
                if d is None: break
                err = target - d
                self.r.final_err_px = round(err, 1)
                if abs(err) <= 1.5 or abs(err) > 25: break
                m.play(human.segment(m.x, m.y, m.x + err / ratio, m.y + random.uniform(-0.6, 0.6),
                                     random.uniform(0.12, 0.25), tremor=0.1))
        time.sleep(human.pause(0.1, 0.3))
        m.up()
        try:
            area = bgb or (tb and dict(x=tb["x"] - 40, y=tb["y"] - 80, width=tb["width"] + 80, height=tb["height"] + 120))
            if area: self._save("released", _shot(self.page, area))
            time.sleep(0.8)
            if area: self._save("released+0.8s", _shot(self.page, area))
        except Exception:
            pass
        return self.r
