"""Tiny threaded JSON HTTP server for offline tests (fake Telegram, stub cardb)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeServer:
    """handler(method, path, headers, body_json) -> (status, json_body)."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def _do(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw
                req = {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
                outer.requests.append(req)
                status, out = outer.handler(self.command, self.path, dict(self.headers), body)
                data = json.dumps(out).encode() if out is not None else b""
                self.send_response(status)
                if data:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _do

            def log_message(self, *a):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


import pytest  # noqa: E402


@pytest.fixture
def fake_http():
    """fake_http(handler) -> FakeServer; all closed at teardown."""
    servers = []

    def make(handler):
        s = FakeServer(handler)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()
