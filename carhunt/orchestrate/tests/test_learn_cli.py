import json

from carhunt import cli as cli_main
from carhunt.orchestrate import learn, pause
from carhunt.orchestrate.launch import launch


def test_night_and_morning(home, config, fake, dummy_role):
    sid = launch("dummy", backend=fake, config=config)
    assert learn.night(fake, config) == ["dummy"]
    assert pause.paused() and "lessons/2026-11-08.md" in fake.sent[-1][1]
    learn_sid = learn.start(fake, config)
    assert fake.sessions[learn_sid]["env"]["CARHUNT_AGENT"] == "learning"
    assert learn.night(fake, config) == ["dummy"], "learning itself is not asked for lessons"
    (home / "agents" / "dummy" / "lessons" / "2026-11-08.md").write_text("- worked: x\n")
    assert learn.collect(config=config)["lessons"] == [str(home / "agents/dummy/lessons/2026-11-08.md")]
    assert learn.morning(fake, config) == ["dummy"] and not pause.paused()
    assert fake.sent[-1][0] == sid and "Unpaused" in fake.sent[-1][1]


def test_cli_state_roundtrip(home, config, fake, dummy_role, monkeypatch, capsys):
    sid = launch("dummy", backend=fake, config=config)
    monkeypatch.setenv("CARHUNT_AGENT", "dummy")
    monkeypatch.setenv("AGTERM_SESSION_ID", sid)
    assert cli_main.main(["state", "set", "summary", "sweeping"]) == 0
    assert cli_main.main(["state", "get", "summary"]) == 0
    assert capsys.readouterr().out.strip() == "sweeping"
    assert cli_main.main(["state", "done"]) == 0
    assert cli_main.main(["state", "get", "status"]) == 0
    assert capsys.readouterr().out.strip() == "completed"
    assert cli_main.main(["state", "set", "active_agent", "X"]) == 1
    assert "launch/takeover" in capsys.readouterr().err
    assert cli_main.main(["unpause"]) == 1, "an agent can't unpause"


def test_cli_hooks_dry_run(home, tmp_path, capsys):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"env": {"K": "secret-ish"}}))
    assert cli_main.main(["hooks", "install", "--settings", str(s), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "secret-guard" in out and "secret-ish" not in out
    assert json.loads(s.read_text()) == {"env": {"K": "secret-ish"}}
