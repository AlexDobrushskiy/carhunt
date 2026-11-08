"""Human-like pointer paths.

A reaching movement follows a minimum-jerk speed profile (slow start, fast middle, slow end). On top of
that: a slight arc, low-frequency hand tremor, an overshoot past the target and a short correction,
and irregular sample timing (~60-120 Hz, like a real mouse/trackpad report rate).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class Step:
    x: float
    y: float
    dt: float  # seconds to wait before this point


def _minjerk(t: float) -> float:
    return 10 * t**3 - 15 * t**4 + 6 * t**5


def _tremor(n: int, sigma: float) -> list[float]:
    """Smoothed random walk: correlated jitter rather than white noise."""
    out, v, a = [], 0.0, 0.0
    for _ in range(n):
        a = 0.7 * a + random.gauss(0, sigma)
        v = 0.85 * v + 0.15 * a
        out.append(v)
    return out


def segment(x0, y0, x1, y1, duration: float, arc: float = 0.0, tremor: float = 0.4, hz=(65, 125)) -> list[Step]:
    """One sub-movement from (x0,y0) to (x1,y1). arc = max perpendicular bulge in px (signed)."""
    dx, dy = x1 - x0, y1 - y0
    dist = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / dist, dx / dist  # unit normal
    steps, t = [], 0.0
    times = []
    while t < duration:
        t += 1.0 / random.uniform(*hz)
        times.append(min(t, duration))
    jx, jy = _tremor(len(times), tremor), _tremor(len(times), tremor)
    prev = 0.0
    for i, tt in enumerate(times):
        u = tt / duration
        s = _minjerk(u)
        bulge = arc * math.sin(math.pi * s)
        fade = math.sin(math.pi * u) if i < len(times) - 1 else 0.0  # no tremor at the endpoint
        x = x0 + dx * s + nx * bulge + jx[i] * fade
        y = y0 + dy * s + ny * bulge + jy[i] * fade
        steps.append(Step(x, y, tt - prev))
        prev = tt
    return steps


def reach(x0, y0, x1, y1, duration: float | None = None) -> list[Step]:
    """Free pointer movement (approach to a handle/checkbox): Fitts-ish duration, arc, slight miss + settle."""
    dist = math.hypot(x1 - x0, y1 - y0)
    duration = duration or min(1.1, 0.25 + 0.12 * math.log2(1 + dist / 8) + random.uniform(-0.05, 0.12))
    arc = random.choice([-1, 1]) * random.uniform(0.04, 0.12) * dist
    mx, my = x1 + random.gauss(0, 1.8), y1 + random.gauss(0, 1.8)
    path = segment(x0, y0, mx, my, duration, arc=arc, tremor=0.5)
    if math.hypot(mx - x1, my - y1) > 1.0:
        path[-1].dt += random.uniform(0.03, 0.09)
        path += segment(mx, my, x1, y1, random.uniform(0.08, 0.16), tremor=0.2)
    return path


def drag(x0, y0, x1, y1, duration: float | None = None, overshoot: bool = True) -> list[Step]:
    """Slider drag (button held): eased main stroke with a small vertical wander, then overshoot + correction."""
    dist = abs(x1 - x0)
    duration = duration or random.uniform(0.55, 0.95) + dist / random.uniform(900, 1400)
    path: list[Step] = []
    over = random.uniform(3, 9) if overshoot and dist > 40 else 0.0
    sign = 1 if x1 >= x0 else -1
    yend = y1 + random.uniform(-2.5, 2.5)
    xa = x1 + sign * over
    path += segment(x0, y0, xa, yend, duration, arc=random.uniform(-3, 3), tremor=0.35)
    if over:
        path[-1].dt += random.uniform(0.06, 0.18)  # notice the overshoot
        path += segment(xa, yend, x1, yend + random.uniform(-0.8, 0.8), random.uniform(0.15, 0.32), tremor=0.15)
    return path


def drag_steps(x0, y0, x1, y1, duration: float, overshoot: bool = False) -> list[Step]:
    """Partial drag stroke (used for the calibration probe of closed-loop sliders)."""
    return segment(x0, y0, x1, y1 + random.uniform(-1, 1), duration, arc=random.uniform(-1.5, 1.5), tremor=0.3)


def pause(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)
