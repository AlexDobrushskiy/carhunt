"""reCAPTCHA v2 image challenge (bframe): 3x3 static/dynamic grids and 4x4 "squares".

One call = one challenge attempt, which may span several rounds (Google often asks 2-4 grids).
10-27: 19/19 runs got a token (lane 14/14, plain-chrome 4/4); 33 grids shown, 19 accepted, 10 "please
try again", 4 extra rounds. ~25 s per round, ~2 min worst case.
The audio path is gone on purpose: whisper transcribed fine, but Google answered "automated queries" in
lanes and closed the popup after every answer in plain-chrome (0/5, 10-27).
"""
from __future__ import annotations

import random
import re
import time
from pathlib import Path

import cv2

from . import grid, human, vision

MAX_ROUNDS = 6


def _vis(f, sel):
    try:
        loc = f.locator(sel).first
        return loc.count() > 0 and loc.is_visible()
    except Exception:
        return False


def _click(mouse, box, rx=(0.3, 0.7), ry=(0.3, 0.7)):
    mouse.reach(box["x"] + box["width"] * random.uniform(*rx), box["y"] + box["height"] * random.uniform(*ry))
    time.sleep(human.pause(0.05, 0.15))
    mouse.down()
    time.sleep(human.pause(0.05, 0.12))
    mouse.up()


def _tile_imgs(page, f):
    tds = f.locator("td.rc-imageselect-tile").all()
    boxes = [td.bounding_box() for td in tds]
    imgs = [vision.decode_png(page.screenshot(clip=b, scale="device"))[:, :, :3] for b in boxes]
    return boxes, imgs


def _frame_open(f):
    try:
        return f.frame_element().is_visible()
    except Exception:
        return False


def _state(f):
    """What the bframe shows after a verify: wrong / more / grid / blocked / closed / other.
    "closed" = Google shut the popup and left the box unticked: the answer was rejected (risk), not graded."""
    if not _frame_open(f):
        return "closed"
    if _vis(f, ".rc-doscaptcha-header"):
        return "blocked"
    if _vis(f, ".rc-imageselect-incorrect-response"):
        return "wrong"
    for s in (".rc-imageselect-error-select-more", ".rc-imageselect-error-dynamic-more", ".rc-imageselect-error-select-something"):
        if _vis(f, s):
            return "more"
    return "grid" if _vis(f, "table[class*=rc-imageselect-table]") else "other"


def solve_grid(page, mouse, f, shots: Path | None, token_ok, *, vlm=None, owl: bool = False) -> dict:
    """Play image rounds until a token appears. Returns {rounds, wrong, extra, outcome, log, notes}."""
    rep = dict(rounds=0, wrong=0, extra=0, log=[], notes=[])

    def yes(tile, target):
        if vlm is not None:
            return vlm.tile_yes(tile, target)
        return grid.owl_tile_score(tile, target) >= 0.2

    for rnd in range(MAX_ROUNDS):
        if token_ok():
            rep["outcome"] = "solved"
            return rep
        if not _frame_open(f) or not _vis(f, "table[class*=rc-imageselect-table]"):
            rep["outcome"] = _state(f)
            return rep
        rep["rounds"] += 1
        desc = f.locator(".rc-imageselect-desc-wrapper").first.inner_text().strip()
        cls = f.locator("table[class*=rc-imageselect-table]").first.get_attribute("class")
        m = re.search(r"table-(\d)(\d)", cls)
        rows, cols = int(m.group(1)), int(m.group(2))
        target = grid.target_of(desc)
        dynamic = "none left" in desc.lower()
        tb = f.locator("table[class*=rc-imageselect-table]").first.bounding_box()
        table_img = vision.decode_png(page.screenshot(clip=tb, scale="device"))[:, :, :3]
        boxes, tiles = _tile_imgs(page, f)
        if shots is not None:
            shots.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(shots / f"round{rnd + 1}.jpg"), grid.numbered(table_img, rows, cols))
        time.sleep(human.pause(0.8, 1.6))  # look at it
        sel = grid.choose(tiles, table_img, rows, cols, target, vlm=vlm, owl=owl, notes=rep["notes"])
        rep["log"].append(dict(target=target, grid=f"{rows}x{cols}", dynamic=dynamic, picked=sorted(sel)))
        order = sorted(sel)
        if random.random() < 0.3:
            random.shuffle(order)
        mouse.place()
        for i in order:
            _click(mouse, boxes[i])
            time.sleep(human.pause(0.25, 0.7))
        if dynamic:  # clicked tiles refill (fade in over ~4 s): re-check only those
            pending = set(sel)
            for _ in range(6):
                if not pending:
                    break
                time.sleep(random.uniform(4.0, 5.0))
                boxes, tiles = _tile_imgs(page, f)
                new = set()
                for i in pending:
                    try:
                        if yes(tiles[i], target):
                            new.add(i)
                    except Exception:
                        pass
                rep["log"][-1].setdefault("refills", []).append(sorted(new))
                for i in sorted(new):
                    _click(mouse, boxes[i])
                    time.sleep(human.pause(0.25, 0.7))
                pending = new
        time.sleep(human.pause(0.4, 1.0))
        _click(mouse, f.locator("#recaptcha-verify-button").first.bounding_box())
        time.sleep(random.uniform(2.0, 3.0))
        if token_ok():
            rep["outcome"] = "solved"
            return rep
        st = _state(f)
        rep["log"][-1]["after"] = st
        if st in ("blocked", "closed"):
            rep["outcome"] = st
            return rep
        if st in ("wrong", "more"):
            rep["wrong"] += 1
        elif st == "grid":
            rep["extra"] += 1
    rep["outcome"] = "rounds-exhausted"
    return rep
