"""e2e across modules on a real `cardb serve`: discover sweep (fake site) → vet writes an ask →
outreach lists and closes it (`carhunt asks`) → vet sees the answer and plans the next ask.

Needs a cardb binary: env CARDB_BIN, or `cardb` on PATH (`make -C cardb build`). Skipped otherwise.
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
ADS = Path(__file__).resolve().parents[2] / "discover" / "tests" / "fixtures" / "sweep_ads.json"
REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(not BIN, reason="no cardb binary (set CARDB_BIN)")


@pytest.fixture
def srv(tmp_path):
    home = tmp_path / "carhunt"
    (home / "cardb").mkdir(parents=True)
    cfg = json.loads(json.dumps(CONFIG))
    cfg["search"]["countries"] = ["PT", "ES"]
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    ads = json.loads(ADS.read_text())
    cheap = dict(ads[0], site_ref="e2e108", price=1200, vin="SYN00000000E2e108",  # under the shared price floor (1500)
                 phones=["+351 555 100 108"], created="2026-11-08T07:30:00+00:00")
    (tmp_path / "ads.json").write_text(json.dumps(ads + [cheap]))
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    token, url = secrets.token_hex(16), f"http://127.0.0.1:{port}"
    env = {**os.environ, "CARHUNT_HOME": str(home), "CARHUNT_CONFIG": str(home / "config.yaml"),
           "CARDB_DATA_DIR": str(home / "cardb"), "CARDB_LISTEN": f"127.0.0.1:{port}",
           "CARDB_TOKENS": f"agents:{token}",
           "CARDB_URL": url, "CARHUNT_SECRET_CARDB_TOKEN": token, "CARHUNT_FAKE_SITES": "1",
           "CARHUNT_FAKE_SITES_FIXTURES": str(tmp_path / "ads.json"), "CARHUNT_FAKE_NOW": "2026-11-08T15:00:00"}
    log = open(tmp_path / "cardb.log", "wb")
    proc = subprocess.Popen([BIN, "serve"], env=env, stdout=log, stderr=log)
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("cardb did not start: " + (tmp_path / "cardb.log").read_text()[-500:])
    yield {"url": url, "token": token, "env": env}
    proc.terminate()
    proc.wait(10)
    log.close()


def api(srv, method, path, body=None):
    req = urllib.request.Request(srv["url"] + "/api/v1" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {srv['token']}",
                                          "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read() or b"null")


def cli(srv, *args, author="vet", ok=(0,)):
    p = subprocess.run([sys.executable, "-m", "carhunt", *args], env={**srv["env"], "CARDB_AUTHOR": author},
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    assert p.returncode in ok, (args, p.returncode, p.stdout[-1500:], p.stderr[-1500:])
    return p


def test_sweep_vet_ask_outreach_close_round_trip(srv):
    rep = json.loads(cli(srv, "sweep", "--sites", "fake", "--json", author="discover").stdout)
    site = rep["sites"][0]
    assert site["state"] == "ok" and site["new"] == 5, site
    assert site["rejected"] == 0 and site["dropped"].get("price_sanity") == 1, site   # same floor as cardb: no 422

    cars = api(srv, "GET", "/cars?limit=100")["cars"]
    assert all(c["version"] >= 1 for c in cars)
    car = str(cars[0]["id"])
    api(srv, "POST", f"/cars/{car}/status", {"status": "talking"})

    # vet: evidence pack → first ask (registration_doc), exit 4 = not visit-ready
    st = json.loads(cli(srv, "evidence", car, "--write-asks", "--json", ok=(4,)).stdout)
    assert [a["data"]["topic"] for a in st["asks"]] == ["registration_doc"]

    # outreach: list open asks across cars, close by topic with the seller's answer
    rows = [json.loads(x) for x in cli(srv, "asks", "list", author="outreach").stdout.splitlines()]
    assert [(str(r["car"]), r["data"]["topic"], r["data"]["fact"]) for r in rows] == [
        (car, "registration_doc", "registration_doc")]
    closed = json.loads(cli(srv, "asks", "close", "--car", car, "--topic", "registration_doc",
                            "--answer", "photo of the front page received", author="outreach").stdout)
    assert closed["type"] == "ask_answered"
    assert closed["data"]["ask_event"] == rows[0]["id"] and closed["data"]["topic"] == "registration_doc"
    assert closed["data"]["fact_written"] is True
    cli(srv, "asks", "close", "--car", car, "--topic", "registration_doc", "--answer", "again",
        author="outreach", ok=(1,))                                   # nothing open: refused, no second close
    assert cli(srv, "asks", "list", author="outreach").stdout.strip() == ""

    # vet: the answer counts (fact in, topic closed) → next ask in order, never a re-ask
    st = json.loads(cli(srv, "evidence", car, "--write-asks", "--json", ok=(4,)).stdout)
    items = {i["key"]: i["state"] for i in st["items"]}
    assert items["registration_doc"] == "have" and items["vin"] == "have"
    assert [a["data"]["topic"] for a in st["asks"]] == ["service_history"]
    evs = api(srv, "GET", f"/cars/{car}/events")
    evs = evs.get("events", evs) if isinstance(evs, dict) else evs
    assert [e["type"] for e in evs if e["type"].startswith("ask")].count("ask") == 2
