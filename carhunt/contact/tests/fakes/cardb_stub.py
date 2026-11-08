"""Tiny in-process cardb stand-in (the REST calls contact uses), for e2e tests over HTTP."""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class CardbStub:
    def __init__(self) -> None:
        self.cars: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.fail_posts = False
        self._srv: ThreadingHTTPServer | None = None

    # --- data helpers ---
    def car_messages(self, car: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if str(m.get("car")) == str(car)]

    def _resolve(self, body: dict[str, Any]) -> str | None:
        if body.get("car"):
            return str(body["car"])
        cp = body.get("counterpart") or ""
        digits = "".join(c for c in cp if c.isdigit())
        hits = [cid for cid, c in self.cars.items()
                for x in (c.get("seller") or {}).get("contacts") or []
                if x.get("value") in (cp, digits, cp.lower())]
        return hits[0] if len(set(hits)) == 1 else None

    # --- server ---
    def start(self) -> str:
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _send(self, code: int, obj: Any) -> None:
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self) -> None:
                u = urllib.parse.urlparse(self.path)
                parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
                q = dict(urllib.parse.parse_qsl(u.query))
                if parts[0] == "cars" and len(parts) == 1:
                    st = q.get("status")
                    return self._send(200, [dict(c, id=k) for k, c in stub.cars.items() if not st or c.get("status") == st])
                if parts[0] == "cars" and len(parts) >= 2:
                    car = stub.cars.get(parts[1])
                    if car is None:
                        return self._send(404, {"error": "not found"})
                    if len(parts) == 2:
                        return self._send(200, dict(car, id=parts[1]))
                    if parts[2] == "messages":
                        return self._send(200, stub.car_messages(parts[1]))
                    if parts[2] == "events":
                        return self._send(200, stub.events.get(parts[1], []))
                if parts[0] == "listings":
                    url = q.get("url")
                    for cid, c in stub.cars.items():
                        for li in c.get("listings") or []:
                            if li.get("url") == url:
                                return self._send(200, [dict(li, car_id=cid)])
                    return self._send(200, [])
                self._send(404, {"error": "no route"})

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                parts = self.path.strip("/").split("/")
                if stub.fail_posts:
                    return self._send(500, {"error": "down"})
                if parts == ["messages"]:
                    car = stub._resolve(body)
                    if car is None:
                        return self._send(422, {"error": "counterpart unknown"})
                    for m in stub.messages:  # idempotent on external_id / dedupe_key
                        if (body.get("external_id") and m.get("external_id") == body["external_id"]) or \
                                (body.get("dedupe_key") and m.get("dedupe_key") == body["dedupe_key"]):
                            return self._send(200, dict(m, matched_by="dedupe_key"))
                    row = dict(body, car=car, car_id=car, id=len(stub.messages) + 1)
                    stub.messages.append(row)
                    return self._send(201, row)
                if parts[0] == "cars" and parts[2] == "events":
                    evs = stub.events.setdefault(parts[1], [])
                    for e in evs:
                        if body.get("dedupe_key") and e.get("dedupe_key") == body["dedupe_key"]:
                            return self._send(200, e)
                    row = dict(body, id=1000 + sum(len(v) for v in stub.events.values()))
                    evs.append(row)
                    return self._send(201, row)
                self._send(404, {"error": "no route"})

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self._srv.server_address[1]}"

    def stop(self) -> None:
        if self._srv:
            self._srv.shutdown()
