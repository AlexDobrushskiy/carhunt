"""Pointer input backends. All take main-frame viewport CSS coordinates.

cdp    Input.dispatchMouseEvent through Playwright's page.mouse. Works headed, headless, off-screen.
macos  CGEventPostToPid: native NSEvents posted to the Chrome process only. The global cursor does not
       move and other apps see nothing. Needs the window in a known screen position (any, even off-screen)
       and the posting process to have the "post events" (Accessibility) permission.
"""
from __future__ import annotations

import random
import subprocess
import time

from . import human


class Mouse:
    name = "base"

    def __init__(self, page):
        self.page = page
        vp = page.viewport_size or page.evaluate("({width: innerWidth, height: innerHeight})")
        # Unknown real position: start somewhere a hand would rest (lower right area).
        self.x = vp["width"] * random.uniform(0.55, 0.9)
        self.y = vp["height"] * random.uniform(0.55, 0.9)
        self.pressed = False

    # primitives
    def _move(self, x, y): raise NotImplementedError
    def _down(self): raise NotImplementedError
    def _up(self): raise NotImplementedError

    def play(self, steps: list[human.Step]):
        nxt = time.perf_counter()
        for s in steps:
            nxt += s.dt
            d = nxt - time.perf_counter()
            if d > 0: time.sleep(d)
            self._move(s.x, s.y)
            self.x, self.y = s.x, s.y

    def place(self):
        """Make the backend's notion of the current position real (one move event)."""
        self._move(self.x, self.y)

    def reach(self, x, y):
        self.play(human.reach(self.x, self.y, x, y))

    def down(self):
        self._down(); self.pressed = True

    def up(self):
        self._up(); self.pressed = False

    def click(self, x, y):
        self.reach(x, y)
        time.sleep(human.pause(0.08, 0.25))
        self.down(); time.sleep(human.pause(0.06, 0.14)); self.up()


class CDPMouse(Mouse):
    name = "cdp"

    def _move(self, x, y): self.page.mouse.move(round(x, 1), round(y, 1))
    def _down(self): self.page.mouse.down()
    def _up(self): self.page.mouse.up()


class MacMouse(Mouse):
    """Native AppKit mouse events posted to the browser process (CGEventPostToPid). The global cursor never
    moves. Chrome accepts press / drag / release this way (isTrusted, same event
    fields as a real mouse), but drops plain hover moves to a window that isn't key; those go via CDP.
    The window must be on a screen (macOS clamps plain-chrome's -3000 position to x=0 anyway)."""
    name = "macos"

    def __init__(self, page, port: int):
        import AppKit
        import Quartz as Q
        self.Q, self.AK = Q, AppKit
        super().__init__(page)
        self.pid = browser_pid(port)
        cdp = page.context.new_cdp_session(page)
        tid = cdp.send("Target.getTargetInfo")["targetInfo"]["targetId"]
        cdp.detach()
        self.bs = page.context.browser.new_browser_cdp_session()
        self.window_id_cdp = self.bs.send("Browser.getWindowForTarget", {"targetId": tid})["windowId"]
        self.screen_h = AppKit.NSScreen.screens()[0].frame().size.height
        self._calibrate()

    def _calibrate(self):
        b = self.bs.send("Browser.getWindowBounds", {"windowId": self.window_id_cdp})["bounds"]
        m = self.page.evaluate("({ow: outerWidth, oh: outerHeight, iw: innerWidth, ih: innerHeight})")
        self.ox = b["left"] + (m["ow"] - m["iw"]) / 2
        self.oy = b["top"] + (m["oh"] - m["ih"])
        self.win = cg_window_number(self.pid, b)
        if self.win is None: raise RuntimeError("Chrome window not found for native input")
        on = any(self.AK.NSPointInRect((self.ox + 5, self.screen_h - self.oy - 5), s.frame()) for s in self.AK.NSScreen.screens())
        if not on: raise RuntimeError("window is off-screen; native input needs it on a display (use --input cdp)")

    def _post(self, kind, x, y, pressure):
        AK = self.AK
        sx, sy = self.ox + x, self.oy + y
        ev = AK.NSEvent.mouseEventWithType_location_modifierFlags_timestamp_windowNumber_context_eventNumber_clickCount_pressure_(
            kind, (sx, self.screen_h - sy), 0, AK.NSProcessInfo.processInfo().systemUptime(), self.win, None, 0, 1, pressure)
        self.Q.CGEventPostToPid(self.pid, ev.CGEvent())

    def _move(self, x, y):
        if self.pressed:
            self._post(self.AK.NSEventTypeLeftMouseDragged, x, y, 1.0)
        else:
            self.page.mouse.move(round(x, 1), round(y, 1))  # hover: CDP (native hover is dropped)

    def _down(self): self._post(self.AK.NSEventTypeLeftMouseDown, self.x, self.y, 1.0)
    def _up(self): self._post(self.AK.NSEventTypeLeftMouseUp, self.x, self.y, 0.0)


def browser_pid(port: int) -> int:
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True).stdout
    pids = [int(p) for p in out.split()]
    if not pids: raise RuntimeError(f"no process listening on debug port {port}")
    return pids[0]


def cg_window_number(pid: int, bounds: dict) -> int | None:
    import Quartz as Q
    best = None
    for w in Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionAll, Q.kCGNullWindowID) or []:
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer") != 0: continue
        b = w.get("kCGWindowBounds", {})
        d = abs(b.get("X", 0) - bounds["left"]) + abs(b.get("Y", 0) - bounds["top"]) + \
            abs(b.get("Width", 0) - bounds["width"]) + abs(b.get("Height", 0) - bounds["height"])
        if best is None or d < best[0]: best = (d, w["kCGWindowNumber"])
    return best[1] if best else None


def cursor_pos():
    import Quartz as Q
    p = Q.CGEventGetLocation(Q.CGEventCreate(None))
    return (round(p.x), round(p.y))


def make(page, kind: str = "cdp", port: int | None = None) -> Mouse:
    if kind == "cdp": return CDPMouse(page)
    if kind == "macos":
        if port is None: raise ValueError("macos input needs the CDP port")
        try:
            import AppKit  # noqa: F401
            import Quartz  # noqa: F401
        except ImportError as e:
            raise RuntimeError("--input macos needs pyobjc-framework-Quartz + pyobjc-framework-Cocoa (macOS only); "
                               "use --input cdp") from e
        return MacMouse(page, port)
    raise ValueError(f"unknown input backend {kind!r}")
