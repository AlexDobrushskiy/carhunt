"""hCaptcha challenge frame (opt-in: config browsers.captcha.hcaptcha_vlm).

Current hCaptcha tasks are drawn on one canvas ("click the letter of group STU" under dot noise, "match
the example and count"), not tile grids; the only general local approach is VLM click points. 0/3 measured
(10-27): adversarial canvas tasks beat a 4B VLM, hence off by default (status `unsupported`).
"""
from __future__ import annotations

import random
import time
from pathlib import Path

import cv2

from . import human, vision


def _vis(f, sel):
    try:
        loc = f.locator(sel).first
        return loc.count() > 0 and loc.is_visible()
    except Exception:
        return False


def points_for(vlm, img, prompt: str) -> list[tuple[float, float]]:
    """Click points (img pixels) the VLM proposes for an hCaptcha prompt."""
    return vlm.points(img, f"This is a captcha puzzle. Instruction: \"{prompt}\". Decide which objects in the image "
                           "must be clicked to complete the instruction. Answer with JSON only: "
                           '[{"point_2d": [x, y], "label": "..."}]')


def solve_challenge(page, mouse, f, shots: Path | None, token_ok, *, vlm) -> dict:
    rep = dict(rounds=0, log=[], notes=[])
    for rnd in range(4):
        if token_ok():
            rep["outcome"] = "solved"
            return rep
        if not _vis(f, ".prompt-text"):
            rep["outcome"] = "no-challenge"
            return rep
        rep["rounds"] += 1
        prompt = f.locator(".prompt-text").first.inner_text().strip()
        cb = f.locator("canvas").first.bounding_box()
        img = vision.decode_png(page.screenshot(clip=cb, scale="css"))[:, :, :3]
        if shots is not None:
            shots.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(shots / f"hc-round{rnd + 1}.jpg"), img)
        time.sleep(human.pause(0.8, 1.5))
        pts = points_for(vlm, img, prompt)
        rep["log"].append(dict(prompt=prompt, points=[[round(x), round(y)] for x, y in pts]))
        mouse.place()
        for x, y in pts:
            if 0 <= x < cb["width"] and 0 <= y < cb["height"]:
                mouse.click(cb["x"] + x, cb["y"] + y)
                time.sleep(human.pause(0.3, 0.8))
        sb = f.locator(".button-submit").first.bounding_box()
        mouse.click(sb["x"] + sb["width"] * random.uniform(0.3, 0.7), sb["y"] + sb["height"] * random.uniform(0.3, 0.7))
        time.sleep(random.uniform(2.5, 3.5))
    rep["outcome"] = "solved" if token_ok() else "failed"
    return rep
