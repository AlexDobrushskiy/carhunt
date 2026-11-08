"""Offline benchmark over a fixtures dir (labels.json from tests/fixtures/captcha/make_fixtures.py, or your
own labelled set in the same shape): puzzle gap error, grid tiling, wall classification. No browser, no model."""
from __future__ import annotations

import json
from pathlib import Path

TOLERANCE_PX = 3


def run(fixtures: Path, tolerance: int = TOLERANCE_PX) -> dict:
    import cv2
    import numpy as np

    from . import grid, vision
    from .detect import classify
    from .static import StaticPage
    d = Path(fixtures)
    lab = json.loads((d / "labels.json").read_text())
    out: dict = {"puzzles": {"ok": 0, "n": 0, "errors_px": []}, "grids": {"ok": 0, "n": 0},
                 "walls": {"ok": 0, "n": 0, "wrong": []}}
    for p in lab.get("puzzles", []):
        bg = cv2.imread(str(d / p["bg"]), cv2.IMREAD_UNCHANGED)
        piece = cv2.imread(str(d / p["piece"]), cv2.IMREAD_UNCHANGED)
        g, _, _ = vision.gap_from_images(bg, piece)
        err = int(g.x) - int(p["gap_x"])
        out["puzzles"]["n"] += 1
        out["puzzles"]["errors_px"].append(err)
        out["puzzles"]["ok"] += abs(err) <= tolerance
    for gl in lab.get("grids", []):
        img = cv2.imread(str(d / gl["image"]))
        tiles = grid.split(img, gl["rows"], gl["cols"])
        means = [t.reshape(-1, 3).mean(0) for t in tiles]
        good = len(tiles) == len(gl["colours"]) and all(
            np.abs(m - np.array(c)).max() < 2 for m, c in zip(means, gl["colours"]))
        out["grids"]["n"] += 1
        out["grids"]["ok"] += good
    for w in lab.get("walls", []):
        frames = {src: (d / f).read_text() for src, f in w.get("frames", {}).items()}
        info = classify(StaticPage((d / w["html"]).read_text(), w["url"], frames, w.get("status", 200)).static_snapshot())
        got = info.kind if info else None
        out["walls"]["n"] += 1
        if got == w["kind"]:
            out["walls"]["ok"] += 1
        else:
            out["walls"]["wrong"].append({"name": w["name"], "want": w["kind"], "got": got})
    return out
