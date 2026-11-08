import argparse

from carhunt.vet import cli


def parse(argv):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    cli.register(sub)
    return ap.parse_args(argv)


def test_vin_decode_exit_codes(capsys):
    a = parse(["vin", "decode", "WVG" + "ZZZE2Z" + "S" + "P" + "000001", "--reg", "2024-10"])
    assert a.func(a) == 0
    assert "Volkswagen" in capsys.readouterr().out
    a = parse(["vin", "decode", "SYN123"])
    assert a.func(a) == 2


def test_check_digit_cli(capsys):
    a = parse(["vin", "check-digit", "SYN" + "00000" + "0" + "ABC" + "12345"])
    assert a.func(a) == 0
    assert capsys.readouterr().out.startswith("0")


def test_prcodes_cli(capsys):
    a = parse(["vin", "prcodes", "3FU", "9M3"])
    assert a.func(a) == 0
    out = capsys.readouterr().out
    assert "cardb opt CAR" in out and "heat_pump=yes:vin_pr_code:9M3" in out


def test_evidence_parser():
    a = parse(["evidence", "7", "--write-asks", "--max-asks", "2"])
    assert a.car == "7" and a.write_asks and a.max_asks == 2
    assert parse(["evidence", "7"]).max_asks is None


def test_evidence_cli_end_to_end_with_stub_core(monkeypatch, capsys):
    """Runs the real `carhunt evidence` handler against stub core.config/core.db modules."""
    import sys
    import types

    from carhunt.vet.tests.test_evidence_pack import StubDB, car

    stub = StubDB(car())
    cfg = types.SimpleNamespace(get=lambda k, d=None: {"vet.max_open_asks": 2}.get(k, d))
    core = types.ModuleType("carhunt.core")
    core.config = types.SimpleNamespace(load=lambda: cfg)
    core.db = types.SimpleNamespace(Client=types.SimpleNamespace(from_config=lambda c: stub))
    monkeypatch.setitem(sys.modules, "carhunt.core", core)
    monkeypatch.setitem(sys.modules, "carhunt.core.config", core.config)
    monkeypatch.setitem(sys.modules, "carhunt.core.db", core.db)

    a = parse(["evidence", "7", "--write-asks"])
    assert a.func(a) == 4
    assert [e["data"]["topic"] for e in stub.events] == ["registration_doc", "service_history"]
    assert "visit-ready: no" in capsys.readouterr().out
