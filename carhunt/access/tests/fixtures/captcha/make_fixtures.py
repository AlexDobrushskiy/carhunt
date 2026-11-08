"""Synthetic captcha fixtures (no real captcha screenshots in the repo).

    python make_fixtures.py OUT_DIR [--puzzles N] [--seed S]   # then: carhunt captcha bench --fixtures OUT_DIR

Puzzles: textured background with a jigsaw-shaped gap (shaded copy of the piece outline, like GeeTest /
DataDome canvases) at a known x, plus the piece canvas (RGBA, piece at the left). Grids: 3x3 / 4x4 of
flat-colour tiles with known colours. Walls: hand-written HTML snippets, one per wall kind, fake hosts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

PIECE_X = 6          # where the loose piece sits in its canvas


def piece_mask(size: int = 42, knob: int = 8) -> np.ndarray:
    """Jigsaw-ish piece: rounded square + a knob on the right and on top."""
    h = w = size + knob + 2
    m = np.zeros((h, w), np.uint8)
    top = knob + 1
    cv2.rectangle(m, (1, top), (size, top + size - 1), 1, -1)
    cv2.circle(m, (size + knob // 2, top + size // 2), knob, 1, -1)
    cv2.circle(m, (size // 2, top), knob, 1, -1)
    return m > 0


def background(rng: np.random.Generator, W: int = 320, H: int = 160) -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.stack([60 + 80 * xx / W, 90 + 60 * yy / H, 140 - 50 * xx / W], -1)
    img = base.astype(np.uint8).copy()
    for _ in range(25):  # scene-like clutter: the gap finder must not lock onto these edges
        c = tuple(int(v) for v in rng.integers(30, 230, 3))
        if rng.random() < 0.5:
            cv2.circle(img, (int(rng.integers(0, W)), int(rng.integers(0, H))), int(rng.integers(6, 30)), c, -1)
        else:
            x, y = int(rng.integers(0, W)), int(rng.integers(0, H))
            cv2.rectangle(img, (x, y), (x + int(rng.integers(8, 50)), y + int(rng.integers(8, 40))), c, -1)
    img = cv2.GaussianBlur(img, (5, 5), 0)
    noise = rng.normal(0, 6, img.shape)
    return np.clip(img + noise, 0, 255).astype(np.uint8)


def puzzle(rng: np.random.Generator, W: int = 320, H: int = 160):
    """-> (bg with gap BGR, piece canvas RGBA (H x W), gap_x, piece_y); gap_x / piece_y = the piece's
    opaque bounding box (what a solver measures), not the mask array's origin."""
    clean = background(rng, W, H)
    mask = piece_mask()
    h, w = mask.shape
    gx = int(rng.integers(int(W * 0.35), W - w - 4))
    py = int(rng.integers(4, H - h - 4))
    bg = clean.copy()
    region = bg[py:py + h, gx:gx + w].astype(np.float32)
    region[mask] = region[mask] * 0.45 + 20                      # the gap: a darker copy of the piece shape
    bg[py:py + h, gx:gx + w] = region.astype(np.uint8)
    outline = mask.astype(np.uint8) - cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8))
    bg[py:py + h, gx:gx + w][outline > 0] = (235, 235, 235)       # light rim, as the vendors draw it
    piece = np.zeros((H, W, 4), np.uint8)
    crop = clean[py:py + h, gx:gx + w].copy()
    crop[outline > 0] = (250, 250, 250)
    piece[py:py + h, PIECE_X:PIECE_X + w, :3] = crop
    piece[py:py + h, PIECE_X:PIECE_X + w, 3] = mask.astype(np.uint8) * 255
    ys, xs = np.where(mask)
    return bg, piece, gx + int(xs.min()), py + int(ys.min())


def composite(bg: np.ndarray, piece: np.ndarray, dx: float) -> np.ndarray:
    """What a screenshot shows with the piece moved `dx` px to the right."""
    out = bg.copy()
    sh = np.zeros_like(piece)
    d = int(round(dx))
    if d >= 0:
        sh[:, d:] = piece[:, :piece.shape[1] - d]
    else:
        sh[:, :d] = piece[:, -d:]
    a = sh[:, :, 3:4] / 255.0
    return (out * (1 - a) + sh[:, :, :3] * a).astype(np.uint8)


def grid_image(rng: np.random.Generator, rows: int, cols: int, tile: int = 100):
    """-> (image, colours per tile [B, G, R]); tiles are flat and pairwise far apart."""
    cols_ = []
    while len(cols_) < rows * cols:
        c = rng.integers(0, 256, 3)
        if all(np.abs(c - o).sum() > 90 for o in cols_):
            cols_.append(c)
    img = np.zeros((rows * tile, cols * tile, 3), np.uint8)
    for i, c in enumerate(cols_):
        r, k = divmod(i, cols)
        img[r * tile:(r + 1) * tile, k * tile:(k + 1) * tile] = c
    return img, [[int(v) for v in c] for c in cols_]


# name -> (main html, page url, {iframe src: frame html}, expected kind, status)
WALLS: dict[str, tuple[str, str, dict, str | None, int]] = {
    "normal-page": ("<html><head><title>Used cars</title></head><body><h1>Results</h1><p>"
                    + "Listing text. " * 50 + "</p></body></html>", "https://cars.example.invalid/", {}, None, 200),
    "datadome-slider": ('<html><body><iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=x&t=fe" '
                        'width="400" height="500"></iframe></body></html>', "https://cars.example.invalid/", {
                            "https://geo.captcha-delivery.com/captcha/?initialCid=x&t=fe":
                            '<body><div class="sliderContainer"><div class="slider"></div><div class="sliderTarget"></div>'
                            "</div><p>Slide right to secure your access</p></body>"}, "datadome-slider", 403),
    "datadome-blocked": ('<html><body><iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=x&t=bv"></iframe>'
                         "</body></html>", "https://cars.example.invalid/", {
                             "https://geo.captcha-delivery.com/captcha/?initialCid=x&t=bv":
                             "<body><p>Access is temporarily restricted</p></body>"}, "datadome-blocked", 403),
    "datadome-blocked-text": ('<html><body><iframe src="https://geo.captcha-delivery.com/captcha/?initialCid=x&t=fe"></iframe>'
                              "</body></html>", "https://cars.example.invalid/", {
                                  "https://geo.captcha-delivery.com/captcha/?initialCid=x&t=fe":
                                  "<body><p>You have been blocked.</p></body>"}, "datadome-blocked", 403),
    "datadome-interstitial": ('<html><body><iframe src="https://geo.captcha-delivery.com/interstitial/?x=1"></iframe>'
                              "</body></html>", "https://cars.example.invalid/", {}, "datadome-interstitial", 403),
    "datadome-var": ("<html><head><script>var dd={'rt':'c','cid':'x','hsh':'y','t':'fe','s':1}</script></head>"
                     "<body></body></html>", "https://cars.example.invalid/", {}, "datadome-slider", 403),
    "datadome-var-bv": ("<html><head><script>var dd={'rt':'c','cid':'x','t':'bv','s':1}</script></head><body></body></html>",
                        "https://cars.example.invalid/", {}, "datadome-blocked", 403),
    "geetest": ('<html><body><div class="geetest_holder"><div class="geetest_canvas_bg" style="width:260px;height:160px">'
                '</div><div class="geetest_slider_button"></div></div><p>Drag the slider</p></body></html>',
                "https://shop.example.invalid/login", {}, "geetest-slide", 200),
    "geetest-solved": ('<html><body><div class="geetest_radar_tip"></div><div class="geetest_success"></div></body></html>',
                       "https://shop.example.invalid/login", {}, None, 200),
    "px-hold": ('<html><body><h2>Before we continue...</h2><p>Press &amp; Hold to confirm you are a human</p>'
                '<div id="px-captcha" style="width:250px;height:50px"></div></body></html>',
                "https://cars.example.invalid/", {}, "px-hold", 403),
    "turnstile": ('<html><head><title>Sign in</title></head><body><form>'
                  '<iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/turnstile/if/ov2/av0/x" '
                  'width="300" height="65"></iframe><input type="hidden" name="cf-turnstile-response" value=""></form>'
                  + "<p>" + "page text " * 200 + "</p></body></html>", "https://forum.example.invalid/", {}, "turnstile", 200),
    "turnstile-done": ('<html><body><iframe src="https://challenges.cloudflare.com/cdn-cgi/x" width="300" height="65"></iframe>'
                       '<input type="hidden" name="cf-turnstile-response" value="' + "t" * 40 + '"></body></html>',
                       "https://forum.example.invalid/", {}, None, 200),
    "cf-just-a-moment": ("<html><head><title>Just a moment...</title></head><body><p>Checking your browser</p>"
                         "</body></html>", "https://cars.example.invalid/", {}, "turnstile", 403),
    "recaptcha-checkbox": ('<html><body><form><iframe title="reCAPTCHA" '
                           'src="https://www.google.com/recaptcha/api2/anchor?k=x" width="304" height="78"></iframe>'
                           '<textarea name="g-recaptcha-response" style="display:none"></textarea></form>'
                           + "<p>" + "form text " * 200 + "</p></body></html>", "https://dealer.example.invalid/vin",
                           {}, "recaptcha", 200),
    "recaptcha-grid": ('<html><body><iframe src="https://www.google.com/recaptcha/api2/anchor?k=x" width="304" height="78">'
                       '</iframe><iframe src="https://www.google.com/recaptcha/api2/bframe?k=x" width="400" height="580">'
                       "</iframe></body></html>", "https://dealer.example.invalid/vin", {}, "recaptcha", 200),
    "recaptcha-grid-hidden": ('<html><body><iframe src="https://www.google.com/recaptcha/api2/anchor?k=x" width="304" '
                              'height="78"></iframe><div style="visibility:hidden"><iframe '
                              'src="https://www.google.com/recaptcha/api2/bframe?k=x" width="400" height="580"></iframe>'
                              "</div></body></html>", "https://dealer.example.invalid/vin", {}, "recaptcha", 200),
    "hcaptcha-checkbox": ('<html><body><iframe src="https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html'
                          '#frame=checkbox&id=1" width="303" height="78"></iframe></body></html>',
                          "https://forum.example.invalid/", {}, "hcaptcha", 200),
    "hcaptcha-challenge": ('<html><body><iframe src="https://newassets.hcaptcha.com/captcha/v1/x/static/hcaptcha.html'
                           '#frame=challenge&id=1" width="520" height="570"></iframe></body></html>',
                           "https://forum.example.invalid/", {}, "hcaptcha", 200),
    "akamai": ('<html><head><script src="/_sec/cp_challenge/ak-challenge-3-1.js"></script></head><body>'
               '<div id="sec-if-cpt-container">Please wait</div></body></html>', "https://cars.example.invalid/", {},
               "akamai-interstitial", 200),
    "generic-slider": ('<html><body><div class="captcha-box"><p>Slide to verify you are human</p>'
                       '<div class="slider-track"><div class="slider-handle"></div></div></div></body></html>',
                       "https://shop.example.invalid/", {}, "generic-slider", 200),
    "hard-block": ("<html><head><title>Access Denied</title></head><body><h1>Access Denied</h1>"
                   "<p>Reference #18.abc</p></body></html>", "https://cars.example.invalid/", {}, "hard-block", 403),
    "http-429-captcha-words": ("<html><body><p>Are you a robot?</p></body></html>",
                               "https://cars.example.invalid/", {}, "unknown", 429),
}


def generate(out: Path, n_puzzles: int = 8, seed: int = 7) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    labels: dict = {"puzzles": [], "grids": [], "walls": []}
    for i in range(n_puzzles):
        bg, piece, gx, py = puzzle(rng)
        name = f"puzzle{i:02d}"
        cv2.imwrite(str(out / f"{name}-bg.png"), bg)
        cv2.imwrite(str(out / f"{name}-piece.png"), piece)
        labels["puzzles"].append(dict(name=name, bg=f"{name}-bg.png", piece=f"{name}-piece.png", gap_x=gx, piece_y=py))
    for rows, cols in ((3, 3), (4, 4)):
        img, colours = grid_image(rng, rows, cols)
        name = f"grid{rows}x{cols}"
        cv2.imwrite(str(out / f"{name}.png"), img)
        labels["grids"].append(dict(name=name, image=f"{name}.png", rows=rows, cols=cols, colours=colours))
    for name, (html, url, frames, kind, status) in WALLS.items():
        (out / f"wall-{name}.html").write_text(html)
        fr = {}
        for j, (src, fhtml) in enumerate(frames.items()):
            (out / f"wall-{name}-frame{j}.html").write_text(fhtml)
            fr[src] = f"wall-{name}-frame{j}.html"
        labels["walls"].append(dict(name=name, html=f"wall-{name}.html", url=url, frames=fr, kind=kind, status=status))
    (out / "labels.json").write_text(json.dumps(labels, indent=1))
    return labels


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out")
    ap.add_argument("--puzzles", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    lab = generate(Path(a.out), a.puzzles, a.seed)
    print(f"{len(lab['puzzles'])} puzzles, {len(lab['grids'])} grids, {len(lab['walls'])} walls -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
