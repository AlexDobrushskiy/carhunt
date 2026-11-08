"""Fake site photos through a real sweep into a real cardb (cardb downloads every photo URL itself).

Without CARHUNT_FAKE_PHOTO_BASE the fake emits no photos (fake.example.invalid gave one 422 per photo);
with it, a local image server stands in for the site's CDN — no network either way."""
import hashlib
import json
import struct
import subprocess
import sys
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from carhunt.discover.tests.test_e2e import FIXTURES, REPO, _cars, _get, server  # noqa: F401  (fixture)


def _png(seed: str, n: int = 32) -> bytes:
    """A distinct noise PNG per name: same-looking photos would make cardb auto-merge different cars."""
    raw, h = b"", hashlib.sha256(seed.encode()).digest()
    for y in range(n):
        row = b"\x00"
        for x in range(n):
            h = hashlib.sha256(h).digest() if (x + y * n) % 10 == 0 else h
            row += bytes(h[(x * 3) % 30:(x * 3) % 30 + 3])
        raw += row

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def images():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            body = _png(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", hits
    srv.shutdown()
    srv.server_close()


def _sweep(srv, **env):
    env = {**srv["env"], "CARHUNT_FAKE_SITES": "1", "CARHUNT_FAKE_SITES_FIXTURES": str(FIXTURES),
           "CARDB_URL": srv["url"], "CARHUNT_SECRET_CARDB_TOKEN": srv["token"], "CARDB_AUTHOR": "sites-e2e",
           "CARHUNT_FAKE_NOW": "2026-11-08T15:00:00", **env}
    p = subprocess.run([sys.executable, "-m", "carhunt.discover", "sweep", "--sites", "fake", "--max", "5", "--json"],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    rep = json.loads(p.stdout)
    return rep, [e for w in rep["writes"] for e in w.get("photo_errors") or []]


def test_sweep_without_photo_base_is_clean(server):
    rep, errors = _sweep(server)
    assert rep["sites"][0]["new"] == 5 and errors == []
    assert all(w.get("photos_added", 0) == 0 for w in rep["writes"])


def test_sweep_with_local_photo_server_stores_photos(server, images):
    base, hits = images
    rep, errors = _sweep(server, CARHUNT_FAKE_PHOTO_BASE=base)
    assert errors == [] and hits and all(h.startswith("/img/") for h in hits)
    added = sum(w.get("photos_added", 0) for w in rep["writes"])
    assert added == len(set(hits)) > 0
    cars = _cars(server)
    assert len(cars) == 5   # distinct photos: no photo-based merge of different cars
    assert sum(len(_get(server, f"/cars/{c['id']}/photos") or []) for c in cars) == added
