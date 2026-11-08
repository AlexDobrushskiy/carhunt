"""CLI: site list/search/live on the fake site, dry-run refuses reveals, doctor runs."""
import argparse
import json

import pytest

from carhunt.sites import base, cli, doctor


def run(argv, capsys):
    ap = argparse.ArgumentParser()
    cli.register(ap.add_subparsers(dest="group"))
    a = ap.parse_args(argv)
    code = a.func(a)
    return code, [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


@pytest.fixture
def fake():
    with base.fake_sites():
        yield


def test_list(fake, capsys):
    code, rows = run(["site", "list"], capsys)
    assert code == 0 and "fake" in {r["site"] for r in rows}


def test_search_and_live(fake, capsys):
    code, rows = run(["site", "fake", "search", "--make", "Volkswagen", "--seller", "private", "--max", "1"], capsys)
    assert code == 0 and [r["site_ref"] for r in rows] == ["fk1001"]
    code, rows = run(["site", "fake", "live", "https://fake.example.invalid/ad/fk1003"], capsys)
    assert code == 0 and rows[0]["state"] == "removed"
    code, rows = run(["site", "fake", "ad", "https://fake.example.invalid/ad/fk1003"], capsys)
    assert code == cli.EXIT_GONE and rows[0]["gone"]


def test_blocked_exit(fake, capsys, monkeypatch):
    monkeypatch.setenv("CARHUNT_FAKE_SITES_BLOCK", "search")
    code, rows = run(["site", "fake", "search"], capsys)
    assert code == cli.EXIT_BLOCKED and rows[0]["blocked"] == "fake-wall"


def test_dry_run_refuses_reveal(fake, capsys):
    code, _ = run(["site", "fake", "phone", "--reveal", "--dry-run", "https://fake.example.invalid/ad/fk1001"], capsys)
    assert code == 1


def test_plist_renders(capsys):
    assert run(["liveness", "--plist", "--at", "04:30"], capsys)[0] == 0


def test_doctor_has_no_failures():
    res = {c.name: c.status for c in doctor.checks()}
    assert res["sites: site.yaml schema"] == "ok"
