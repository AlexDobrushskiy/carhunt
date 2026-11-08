"""e2e: real `cardb serve` on temp data + `carhunt sweep --sites fake --max 5` → 5 cars; re-run = 0 writes.

Needs a cardb binary: env CARDB_BIN, or `cardb` on PATH (build: `cd cardb && go build ./cmd/cardb`). Skipped otherwise.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
import yaml

from carhunt.discover.tests.conftest import CONFIG

BIN = os.environ.get("CARDB_BIN") or shutil.which("cardb")
FIXTURES = Path(__file__).parent / "fixtures" / "sweep_ads.json"
REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(not BIN, reason="no cardb binary (set CARDB_BIN)")


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path):
    home = tmp_path / "carhunt"
    (home / "cardb").mkdir(parents=True)
    cfg = json.loads(json.dumps(CONFIG))
    cfg["search"]["countries"] = ["PT", "ES"]
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    token, port = secrets.token_hex(16), _port()
    env = {**os.environ, "CARHUNT_HOME": str(home), "CARHUNT_CONFIG": str(home / "config.yaml"),
           "CARDB_DATA_DIR": str(home / "cardb"), "CARDB_LISTEN": f"127.0.0.1:{port}",
           "CARDB_TOKENS": f"agents:{token}"}
    log = open(tmp_path / "cardb.log", "wb")
    proc = subprocess.Popen([BIN, "serve"], env=env, stdout=log, stderr=log)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/v1/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("cardb did not start: " + (tmp_path / "cardb.log").read_text()[-500:])
    yield {"url": url, "token": token, "home": home, "env": env}
    proc.terminate()
    proc.wait(10)
    log.close()


def _get(srv, path):
    req = urllib.request.Request(srv["url"] + "/api/v1" + path, headers={"Authorization": f"Bearer {srv['token']}"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def _sweep(srv, *args):
    env = {**srv["env"], "CARHUNT_FAKE_SITES": "1", "CARHUNT_FAKE_SITES_FIXTURES": str(FIXTURES),
           "CARDB_URL": srv["url"], "CARHUNT_SECRET_CARDB_TOKEN": srv["token"], "CARDB_AUTHOR": "discover-e2e",
           "CARHUNT_FAKE_NOW": "2026-11-08T15:00:00"}
    p = subprocess.run([sys.executable, "-m", "carhunt.discover", "sweep", "--sites", "fake", *args, "--json"],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads(p.stdout)


def _cars(srv) -> list[dict]:
    res = _get(srv, "/cars?limit=100")
    return res["cars"] if isinstance(res, dict) else res


def test_sweep_fake_into_cardb_then_rerun_is_free(server):
    rep = _sweep(server, "--max", "5")
    site = rep["sites"][0]
    assert (site["new"], site["state"]) == (5, "ok"), site      # 7 fixture ads: 5 in scope, 1 lease, 1 over km
    assert site["dropped"] == {"flag": 1}                           # the km one never leaves the site filter
    cars = _cars(server)
    assert len(cars) == 5
    before = {c["id"]: _get(server, f"/cars/{c['id']}") for c in cars}     # full detail: events, facts, listings
    one = _get(server, f"/cars/{cars[0]['id']}")
    assert one["listings"][0]["url"].startswith("https://fake.example.invalid/ad/")
    assert any(f["key"] == "ad_quality" for f in one["facts"])

    rep2 = _sweep(server, "--max", "5")
    s2 = rep2["sites"][0]
    assert s2["new"] == 0 and s2["updated"] == 0 and rep2["writes"] == []
    assert {c["id"]: _get(server, f"/cars/{c['id']}") for c in _cars(server)} == before   # nothing written


def test_dry_run_prints_payloads_writes_nothing(server):
    rep = _sweep(server, "--dry-run", "--max", "2")
    assert [w["action"] for w in rep["writes"]] == ["would_create", "would_create"]
    assert rep["writes"][0]["upsert"]["url"].startswith("https://fake.example.invalid/ad/")
    assert _cars(server) == []
