"""Image processing for puzzle sliders: where is the gap the piece must slide into?

The gap is drawn into the background as a shaded copy of the piece's outline. We match the piece's
boundary against the background's edge map (a chamfer-style score), restricted to the piece's rows and
to x positions right of where the piece starts. No ML.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import cv2
import numpy as np


SHADE_W = 1.0
CONTENT_W = 1.0


@dataclass
class Gap:
    x: int          # left edge of the gap in background-image pixels (same frame as piece_x)
    score: float    # boundary edge strength at the best x
    margin: float   # best score / second-best peak (>1.15 = confident)


def decode_data_url(url: str) -> np.ndarray:
    raw = base64.b64decode(url.split(",", 1)[1])
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)


def decode_png(data: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)


def _gray(img):
    if img.ndim == 2: return img
    return cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)


def piece_from_rgba(rgba: np.ndarray, alpha_min=40):
    """Crop a piece canvas (transparent around the piece) to the piece. Returns (bgr, mask, x, y)."""
    a = rgba[:, :, 3]
    ys, xs = np.where(a > alpha_min)
    if len(xs) == 0: raise ValueError("piece image is fully transparent")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return rgba[y0:y1, x0:x1, :3], (a[y0:y1, x0:x1] > alpha_min), int(x0), int(y0)


def boundary(mask: np.ndarray, inset: int = 3) -> np.ndarray:
    """Pixels on/just inside the piece outline (where the gap's shading edge sits)."""
    m = mask.astype(np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    outer = m - cv2.erode(m, k)
    inner = cv2.erode(m, k, iterations=1) - cv2.erode(m, k, iterations=inset)
    return (outer + inner * 0) > 0  # outline only; inner band kept for experiments


def edge_map(bgr: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(_gray(bgr).astype(np.float32), (3, 3), 0)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    mag = cv2.GaussianBlur(mag, (5, 5), 1.2)  # tolerance of ~1-2 px
    return mag / (np.percentile(mag, 99.5) + 1e-6)


def find_gap(bg: np.ndarray, mask: np.ndarray, piece_y: int, x_min: int = 0, x_max: int | None = None,
             piece_bgr: np.ndarray | None = None) -> Gap:
    """bg: background (BGR), the piece NOT drawn over the candidate area. mask: piece shape (bool h×w).
    piece_y: top row of the piece in bg. Returns the best gap x (left edge)."""
    h, w = mask.shape
    H, W = bg.shape[:2]
    piece_y = int(np.clip(piece_y, 0, H - h))
    x_max = min(W - w, x_max if x_max is not None else W - w)
    E = edge_map(bg)[piece_y:piece_y + h]
    B = boundary(mask).astype(np.float32)
    B /= B.sum()
    # correlation of the edge band with the outline, at every x
    scores = cv2.matchTemplate(E, B, cv2.TM_CCORR)[0]  # shape: W-w+1
    # shading term: the gap is a uniform brightness shift inside the outline vs. a ring just outside
    sh = _shade_scores(bg, mask, piece_y)
    total = scores / (scores.max() + 1e-6) + SHADE_W * sh / (np.abs(sh).max() + 1e-6)
    if piece_bgr is not None and piece_bgr.shape[:2] == mask.shape:
        # the piece was cut out of the picture at the gap: its content reappears there, shaded
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        inner = cv2.erode(mask.astype(np.uint8), k, iterations=1)
        if inner.sum() > 30:
            band = _gray(bg)[piece_y:piece_y + h]
            c = cv2.matchTemplate(band, _gray(piece_bgr), cv2.TM_CCOEFF_NORMED, mask=inner * 255)[0]
            c = np.nan_to_num(c, nan=0.0, posinf=0.0, neginf=0.0)
            total = total + CONTENT_W * np.clip(c, 0, 1)
    total[: max(0, x_min)] = -1
    total[x_max + 1:] = -1
    best = int(np.argmax(total))
    second = np.max(np.concatenate([total[: max(0, best - w // 2)], total[best + w // 2 + 1:]]) if len(total) > w else [1e-6])
    return Gap(best, float(total[best]), float(total[best] / max(second, 1e-6)))


def _bands(mask, d0=1, d1=4):
    """Thin bands just inside and just outside the piece outline."""
    m = mask.astype(np.uint8)
    pad = d1 + 1
    mp = cv2.copyMakeBorder(m, pad, pad, pad, pad, cv2.BORDER_CONSTANT, 0)
    din = cv2.distanceTransform(mp, cv2.DIST_L2, 3)
    dout = cv2.distanceTransform(1 - mp, cv2.DIST_L2, 3)
    inner = ((din > d0) & (din <= d1)).astype(np.float32)
    outer = ((dout > d0) & (dout <= d1)).astype(np.float32)
    return inner, outer, pad


def _shade_scores(bg, mask, piece_y):
    """Uniform shading step across the outline: (mean outside band - mean inside band) / band texture.
    The gap is a darker/lighter copy of the piece shape, so the step is large and consistent; text or
    texture edges crossing the outline give a small mean step with a high spread."""
    h, w = mask.shape
    inner, outer, pad = _bands(mask)
    g = _gray(bg).astype(np.float32)
    y0 = piece_y - pad
    gp = cv2.copyMakeBorder(g, pad, pad, pad, pad, cv2.BORDER_REPLICATE)[y0 + pad: y0 + pad + h + 2 * pad]
    def stats(k):
        k = k / max(k.sum(), 1)
        m1 = cv2.matchTemplate(gp, k, cv2.TM_CCORR)[0]
        m2 = cv2.matchTemplate(gp * gp, k, cv2.TM_CCORR)[0]
        return m1, np.sqrt(np.maximum(m2 - m1 * m1, 0))
    mi, si = stats(inner)
    mo, so = stats(outer)
    return np.abs(mo - mi) / (si + so + 6.0)


def locate(template: np.ndarray, img: np.ndarray, mask: np.ndarray | None = None) -> tuple[int, int, float]:
    """Find a piece image inside a bigger image (normalized cross-correlation on grayscale)."""
    t, i = _gray(template), _gray(img)
    m = None if mask is None else mask.astype(np.uint8) * 255
    r = cv2.matchTemplate(i, t, cv2.TM_CCORR_NORMED if m is not None else cv2.TM_CCOEFF_NORMED, mask=m)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return loc[0], loc[1], float(mx)


def piece_hull(hits: np.ndarray, max_frac: float = 0.45):
    """Piece region from scattered motion hits (mostly its outline and textured parts): keep the densest
    compact cluster and take its convex hull. Jigsaw knobs are small, so the hull is a fair shape."""
    m = cv2.morphologyEx(hits.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    big = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(big)
    if n < 2: return None
    # the cluster with the most hit pixels
    best = max(range(1, n), key=lambda i: int(m[lab == i].sum()))
    ys, xs = np.where((lab == best) & (m > 0))
    if len(xs) < 40: return None
    if xs.max() - xs.min() > hits.shape[1] * max_frac: return None
    hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.int32))
    out = np.zeros_like(m)
    cv2.fillConvexPoly(out, hull, 1)
    return out > 0


def gap_from_images(bg: np.ndarray, piece_rgba: np.ndarray) -> tuple[Gap, int, int]:
    """Gap for a puzzle given as its own images: background (with the gap) + piece canvas with alpha, both
    in the same pixel frame (GeeTest v3 canvases, DataDome puzzle canvases). Returns (gap, piece_x, piece_y)."""
    _, mask, x0, y0 = piece_from_rgba(piece_rgba)
    if bg.ndim == 3 and bg.shape[2] == 4:  # transparent areas -> white
        a = bg[:, :, 3:4] / 255.0
        bg = (bg[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    elif bg.ndim == 2:
        bg = cv2.cvtColor(bg, cv2.COLOR_GRAY2BGR)
    return find_gap(bg, mask, y0, x_min=int(x0 + mask.shape[1] * 0.6)), x0, y0
