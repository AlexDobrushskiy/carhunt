"""Image-grid captchas ("select all images / squares with X"): which tiles show the target?

Measured 10-27 on 25 hand-labelled Google grids (a grid counts only if every chosen tile is right):
  3x3 (9 separate photos): local VLM yes/no per tile -> 16/17
  4x4 (one photo cut in squares): OWLv2 open-vocabulary boxes, tiles = box overlap -> 7/8
  dropped: SigLIP per tile 11/25, whole grid to a VLM <=12/25
Without OWLv2 (config owlv2: false) 4x4 falls back to the VLM per square (not benchmarked).
Tile indices are row-major, 0-based.
"""
from __future__ import annotations

import functools
import re

import cv2
import numpy as np

# reCAPTCHA's usual targets -> phrasings that work better as detector text queries
SYNONYMS = {
    "crosswalks": ["a pedestrian crosswalk with white zebra stripes on the road"],
    "traffic lights": ["a traffic light"], "a fire hydrant": ["a fire hydrant"], "fire hydrants": ["a fire hydrant"],
    "buses": ["a bus"], "bus": ["a bus"], "cars": ["a car"], "motorcycles": ["a motorcycle"],
    "bicycles": ["a bicycle"], "stairs": ["outdoor stairs, steps"], "chimneys": ["a chimney"],
    "bridges": ["a bridge"], "boats": ["a boat"], "tractors": ["a tractor"], "palm trees": ["a palm tree"],
    "mountains or hills": ["mountains or hills"], "taxis": ["a yellow taxi cab"], "parking meters": ["a parking meter"],
}


class NoClassifier(RuntimeError):
    """Neither a VLM nor OWLv2 is available for this grid."""


def target_of(instruction: str) -> str:
    """'Select all images with\\na fire hydrant\\nClick verify ...' -> 'a fire hydrant'."""
    lines = [ln.strip() for ln in instruction.splitlines() if ln.strip()]
    if len(lines) >= 2 and re.match(r"select all (images|squares) with( a| an)?$", lines[0], re.I):
        t = lines[1]
        if re.search(r"with a$", lines[0], re.I):
            t = "a " + t
        return t
    m = re.search(r"(?:images|squares) (?:with|containing|of)\s+(.+?)(?:\.|click|if there|$)", " ".join(lines), re.I)
    return m.group(1).strip() if m else " ".join(lines)


def queries(target: str) -> list[str]:
    t = target.lower().strip()
    return SYNONYMS.get(t) or [t if t.startswith(("a ", "an ")) else f"a {t}"]


def split(grid: np.ndarray, rows: int, cols: int) -> list[np.ndarray]:
    """Row-major tiles; edges are spread so every pixel lands in exactly one tile."""
    H, W = grid.shape[:2]
    return [grid[r * H // rows: (r + 1) * H // rows, c * W // cols: (c + 1) * W // cols]
            for r in range(rows) for c in range(cols)]


def tiles_from_boxes(boxes, H, W, rows, cols, min_frac=0.06) -> set[int]:
    """Tiles a detected box covers by at least min_frac of the tile's area (or 25 % of the box)."""
    sel = set()
    th, tw = H / rows, W / cols
    for x1, y1, x2, y2, _s in boxes:
        ba = max(1.0, (x2 - x1) * (y2 - y1))
        for r in range(rows):
            for c in range(cols):
                ix = max(0, min(x2, (c + 1) * tw) - max(x1, c * tw))
                iy = max(0, min(y2, (r + 1) * th) - max(y1, r * th))
                inter = ix * iy
                if inter >= min_frac * tw * th or inter >= 0.25 * ba:
                    sel.add(r * cols + c)
    return sel


def numbered(grid: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Grid with each tile's 1-based index drawn in its corner (debug screenshots)."""
    g = grid.copy()
    H, W = g.shape[:2]
    for r in range(rows):
        for c in range(cols):
            x, y = c * W // cols, r * H // rows
            cv2.rectangle(g, (x, y), (x + 30, y + 24), (0, 0, 0), -1)
            cv2.putText(g, str(r * cols + c + 1), (x + 4, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            cv2.rectangle(g, (x, y), (x + W // cols - 1, y + H // rows - 1), (255, 255, 255), 2)
    return g


# ---- OWLv2 (optional: torch + transformers; weights ~0.6 GB from Hugging Face on first use) ----

def owl_installed() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("torch", "transformers"))


def _device():
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


@functools.lru_cache(maxsize=1)
def _owl(name="google/owlv2-base-patch16-ensemble"):
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    return Owlv2ForObjectDetection.from_pretrained(name).to(_device()).eval(), Owlv2Processor.from_pretrained(name)


def owl_boxes(img: np.ndarray, target: str, thresh: float = 0.1):
    """[(x1, y1, x2, y2, score)] in img pixels."""
    import torch
    from PIL import Image
    model, proc = _owl()
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    inp = proc(text=[queries(target)], images=im, return_tensors="pt").to(_device())
    with torch.no_grad():
        out = model(**inp)
    side = max(im.size)  # OWLv2 pads to a square
    res = proc.post_process_grounded_object_detection(out, threshold=thresh, target_sizes=torch.tensor([[side, side]]))[0]
    return [(*b.tolist(), float(s)) for b, s in zip(res["boxes"].cpu(), res["scores"].cpu())]


def owl_tile_score(tile: np.ndarray, target: str) -> float:
    big = cv2.resize(tile, (300, 300), interpolation=cv2.INTER_CUBIC)
    return max([s for *_, s in owl_boxes(big, target, thresh=0.01)], default=0.0)


def choose(tiles: list[np.ndarray], table_img: np.ndarray, rows: int, cols: int, target: str, *,
           vlm=None, owl: bool = False, notes: list | None = None) -> set[int]:
    """Tiles to click. vlm: an Ollama client (or None); owl: OWLv2 allowed."""
    notes = notes if notes is not None else []
    if rows * cols != 9 and owl:
        boxes = owl_boxes(table_img, target, thresh=0.2)
        return tiles_from_boxes(boxes, table_img.shape[0], table_img.shape[1], rows, cols)
    if vlm is None:
        raise NoClassifier("grid challenge needs the local VLM (Ollama) or OWLv2 for 4x4")
    if rows * cols != 9:
        notes.append("4x4 without OWLv2: VLM per square (not benchmarked)")
    sel = set()
    for i, t in enumerate(tiles):
        try:
            if vlm.tile_yes(t, target):
                sel.add(i)
        except Exception as e:
            if not owl:
                raise
            notes.append(f"vlm tile failed ({e}); owl fallback")
            if owl_tile_score(t, target) >= 0.2:
                sel.add(i)
    return sel
