"""Minimal page driver over raw CDP, for bot walls that catch Playwright once it is attached.

Playwright enables Runtime/Page/Network on every page it touches; bot scripts see side effects of that
(Imperva on coches.net flags every such browser on the IP). This driver talks to ONE page target
and never enables a domain: Runtime.evaluate, Page.navigate, Input.* and Target.* work without *.enable.

    from carhunt.access.rawcdp import Page
    pg = Page(port, target)               # from `plain-chrome open` ({"port", "target"})
    pg.navigate(url); pg.wait_ready()
    pg.eval("document.title")
    pg.click("button[type=submit]")       # trusted mouse events at the element's centre
    pg.type_into("textarea", "Hola")      # focus + Input.insertText (trusted input)
    pg.close()
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any


def _connect(url: str):
    import websocket  # websocket-client
    # suppress_origin: Chrome refuses DevTools websockets that carry an Origin header
    return websocket.create_connection(url, timeout=60, suppress_origin=True)


class _Conn:
    def __init__(self, ws_url: str):
        self.ws = _connect(ws_url)
        self._id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:  # no domain is enabled, so only our replies arrive
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


class Page(_Conn):
    def __init__(self, port: int, target: str):
        self.port, self.target = port, target
        super().__init__(f"ws://127.0.0.1:{port}/devtools/page/{target}")

    def eval(self, expr: str, await_promise: bool = False) -> Any:
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("text", "eval error"))
        return r.get("result", {}).get("value")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})

    def wait_ready(self, timeout: float = 30, settle: float = 2.0) -> None:
        t0 = time.time()
        time.sleep(0.5)
        while time.time() - t0 < timeout:
            try:
                if self.eval("document.readyState") == "complete":
                    break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(settle)

    def _center(self, selector: str):
        js = (f"(()=>{{const e=document.querySelector({json.dumps(selector)}); if(!e) return null;"
              "e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect();"
              "return [r.left+r.width/2, r.top+r.height/2, r.width>0&&r.height>0];})()")
        return self.eval(js)

    def click(self, selector: str) -> None:
        c = self._center(selector)
        if not c or not c[2]:
            raise RuntimeError(f"not clickable: {selector}")
        time.sleep(0.3)
        x, y = c[0], c[1]
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        time.sleep(0.08)
        for t in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(0.06)

    def type_into(self, selector: str, text: str) -> None:
        """Insert text as typed. Newlines go in as text: Enter resets some forms (coches.net)."""
        self.click(selector)
        sel = json.dumps(selector)
        self.eval(f"(()=>{{const e=document.querySelector({sel}); e.focus(); e.select&&e.select();}})()")
        self.send("Input.insertText", {"text": text})


def browser_ws(port: int) -> str:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
        return json.load(r)["webSocketDebuggerUrl"]


def browser_send(port: int, method: str, params: dict | None = None) -> dict:
    """One browser-level command (Browser.close, Browser.setWindowBounds…) without attaching to any page."""
    c = _Conn(browser_ws(port))
    try:
        return c.send(method, params)
    finally:
        c.close()


def pages(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
        return [t for t in json.load(r) if t.get("type") == "page"]
