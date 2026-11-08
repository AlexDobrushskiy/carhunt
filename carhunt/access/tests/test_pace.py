import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from carhunt.access import pace
from carhunt.access.errors import PaceExceeded

FIXTURES = Path(__file__).parent / "fixtures" / "access-sites"


@pytest.fixture
def env(carhunt_home, monkeypatch):
    monkeypatch.setenv("CARHUNT_SITES_DIR", str(FIXTURES))
    monkeypatch.delenv("CARHUNT_FAKE_NOW", raising=False)
    return carhunt_home


HAMMER = """
import os, sys
from carhunt.access import pace
from carhunt.access.errors import PaceExceeded
ok = 0
for _ in range(int(sys.argv[3])):
    try:
        pace.acquire(sys.argv[1], sys.argv[2], who=f"proc{os.getpid()}")
        ok += 1
    except PaceExceeded:
        pass
print(ok)
"""


@pytest.mark.parametrize("kind,cap", [("load", 7), ("phone", 3)])
def test_two_processes_never_exceed_cap(env, kind, cap):
    # real OS processes (not threads) racing on the shared SQLite ledger
    repo = Path(__file__).resolve().parents[3]
    penv = {**os.environ, "PYTHONPATH": str(repo)}
    procs = [subprocess.Popen([sys.executable, "-c", HAMMER, "pacefix", kind, "25"], env=penv,
                              stdout=subprocess.PIPE, text=True) for _ in range(2)]
    outs = [p.communicate(timeout=60)[0] for p in procs]
    assert all(p.returncode == 0 for p in procs)
    assert sum(int(o) for o in outs) == cap
    assert pace.check("pacefix", kind).allowed is False


def test_day_cap_resets_at_owner_local_midnight(env, monkeypatch):
    (env / "config.yaml").write_text("owner: {tz: Pacific/Auckland}\n")
    # 10:58 UTC = 23:58 in Auckland (NZDT, +13) on 2026-11-08
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T10:58:00+00:00")
    for _ in range(3):
        pace.acquire("pacefix", "phone")
    with pytest.raises(PaceExceeded) as e:
        pace.acquire("pacefix", "phone", wait=True)  # day caps never wait
    assert "day cap 3" in e.value.reason
    assert e.value.retry_at == datetime(2026, 11, 9, 0, 0, tzinfo=ZoneInfo("Pacific/Auckland"))
    # 11:01 UTC: still 2026-11-08 in UTC, but a new day in Auckland
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T11:01:00+00:00")
    pace.acquire("pacefix", "phone")
    st = pace.check("pacefix", "phone")
    assert st.used_today == 1 and st.allowed


def test_min_gap_refuses_then_wait_sleeps_through(env):
    pace.acquire("gapfix", "load")
    with pytest.raises(PaceExceeded) as e:
        pace.acquire("gapfix", "load")
    assert "min gap" in e.value.reason and e.value.retry_at is not None
    t0 = time.monotonic()
    pace.acquire("gapfix", "load", wait=True)
    assert time.monotonic() - t0 >= 0.3


def test_run_cap_is_per_who_and_never_waits(env):
    pace.acquire("runfix", "load", who="a")
    pace.acquire("runfix", "load", who="a")
    with pytest.raises(PaceExceeded) as e:
        pace.acquire("runfix", "load", who="a", wait=True, max_wait_s=1)
    assert "run cap" in e.value.reason
    pace.acquire("runfix", "load", who="b")


def test_via_has_own_rate_budget_but_shares_day_caps(env):
    for _ in range(7):
        pace.acquire("pacefix", "load")
    with pytest.raises(PaceExceeded):
        pace.acquire("pacefix", "load")
    pace.acquire("pacefix", "load", via="fr")  # other exit IP, other budget
    pace.acquire("pacefix", "send", via="fr")
    pace.acquire("pacefix", "send")
    with pytest.raises(PaceExceeded):
        pace.acquire("pacefix", "send", via="es")  # per-account day cap: 2 across exits


def test_refund_and_reset_day(env):
    tickets = [pace.acquire("pacefix", "phone") for _ in range(3)]
    with pytest.raises(PaceExceeded):
        pace.acquire("pacefix", "phone")
    pace.refund(tickets[0])
    pace.acquire("pacefix", "phone")
    assert pace.reset_day("pacefix", "phone") == 3
    assert pace.check("pacefix", "phone").used_today == 0


def test_defaults_and_config_override(env):
    lim = pace.limits("unmeasured.example.invalid", "load")
    assert (lim.min_gap_s, lim.per_hour, lim.per_run) == (12, 30, 60)
    assert pace.limits("unmeasured.example.invalid", "phone").per_day == 5
    assert pace.limits("unmeasured.example.invalid", "send").per_day == 10
    assert pace.limits("unmeasured.example.invalid", "login").per_day == 3
    (env / "config.yaml").write_text("owner: {tz: UTC}\nsites:\n  overrides:\n    pacefix: {caps: {phone_per_day: 9}}\n")
    assert pace.limits("pacefix", "phone").per_day == 9
    assert pace.limits("pacefix", "send").per_day == 2  # rest of site.yaml kept
    assert pace.limits("pacefix.example.invalid", "load").per_hour == 7  # matched by name:


def test_cli_take_and_status(env, capsys):
    assert pace.main(["take", "sesscap", "load"]) == 0
    assert pace.main(["take", "sesscap", "load"]) == 3
    assert '"ok": false' in capsys.readouterr().out
    assert pace.main(["status", "sesscap"]) == 0
    assert '"used_hour": 1' in capsys.readouterr().out
    assert pace.main(["reset-day", "sesscap"]) == 0


def test_ledger_lives_under_carhunt_home(env):
    pace.acquire("sessfix", "load")
    assert (env / "access" / "pace.sqlite").exists()


def test_shipped_site_yaml_feed_the_ledger(carhunt_home, monkeypatch):
    """Every shipped site.yaml resolves by dir name, id and host to one ledger key, and carries what access reads."""
    from carhunt.access.accounts import sms
    monkeypatch.delenv("CARHUNT_SITES_DIR", raising=False)
    files = sorted(pace.REPO_SITES.glob("*/site.yaml"))
    assert len(files) >= 10
    for f in files:
        import yaml
        d = yaml.safe_load(f.read_text())
        sid = d["site"]
        assert pace.canonical(f.parent.name) == sid == pace.canonical(sid.upper())
        assert pace.limits(sid, "load").min_gap_s == d["pace"]["min_gap_s"]
        assert pace.limits(sid, "load").per_hour == d["pace"].get("max_loads_per_hour")  # measured: no default cap
        for kind in pace.KINDS:
            pace.limits(sid, kind)
        v = d["account"]["verification"]
        assert sms.policy(sid).allowed == (v == "sms-once"), sid
        assert "renting needs an explicit" not in sms.policy(sid).reason, f"{sid}: verification {v!r} unknown to sms"
    assert pace.canonical("www.autoscout24.de") == "autoscout24"   # host regex
    assert pace.canonical("coches_net") == "coches.net"


def test_api_kind_defaults_to_load_gap_without_load_caps(env, tmp_path, monkeypatch):
    d = tmp_path / "apifix"
    d.mkdir()
    (d / "site.yaml").write_text("site: apifix\npace: {min_gap_s: 7, max_loads_per_hour: 2, max_loads_per_run: 3}\n")
    monkeypatch.setenv("CARHUNT_SITES_DIR", str(tmp_path))
    lim = pace.limits("apifix", "api")
    assert (lim.min_gap_s, lim.per_hour, lim.per_run) == (7, None, None)
    (d / "site.yaml").write_text("site: apifix\npace: {min_gap_s: 7, api_min_gap_s: 12, max_api_per_hour: 20}\n")
    lim = pace.limits("apifix", "api")
    assert (lim.min_gap_s, lim.per_hour) == (12, 20)
