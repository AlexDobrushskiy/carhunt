import json

import pytest

from carhunt.orchestrate import hooks

FOREIGN = {
    "env": {"SOME_TOKEN": "do-not-print-me"},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/x/guard.py"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "/opt/x/status.sh done"}]}],
    },
    "statusLine": {"type": "command", "command": "/opt/x/statusline.sh"},
}


@pytest.fixture
def settings(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps(FOREIGN, indent=2))
    return p


def test_install_dry_run_diff_then_idempotent(home, settings):
    before = settings.read_bytes()
    cur, new, diff = hooks.plan(settings, python="/py")
    assert "secret-guard" in diff and "send-guard" in diff and "mailbox" in diff
    assert "do-not-print-me" not in diff, "only the hooks section is diffed"
    assert settings.read_bytes() == before, "plan never writes"
    backup = hooks.write(settings, new)
    assert backup and backup.read_bytes() == before
    _, _, diff2 = hooks.plan(settings, python="/py")
    assert diff2 == "", "second install is a no-op"


def test_foreign_hooks_untouched(home, settings):
    _, new, _ = hooks.plan(settings, python="/py")
    assert new["env"] == FOREIGN["env"] and new["statusLine"] == FOREIGN["statusLine"]
    assert new["hooks"]["PreToolUse"][0] == FOREIGN["hooks"]["PreToolUse"][0]
    assert new["hooks"]["Stop"][0] == FOREIGN["hooks"]["Stop"][0]
    hooks.write(settings, new)
    _, removed, _ = hooks.plan(settings, remove=True)
    assert removed == FOREIGN


def test_refuses_malformed(home, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    with pytest.raises(hooks.HooksError, match="refusing"):
        hooks.plan(p)
    p.write_text(json.dumps({"hooks": {"PreToolUse": {"oops": 1}}}))
    with pytest.raises(hooks.HooksError, match="refusing"):
        hooks.plan(p)


def test_skips_mailbox_where_foreign_receiver(home):
    stop = {"Stop": [{"hooks": [{"command": "/x/other-mailbox claude-hook", "asyncRewake": True}]}]}
    for cur, also in ((stop, None), ({}, stop)):  # in the target, or in the user settings (both load)
        cmds = json.dumps(hooks.desired(cur, python="/py", also=also))
        assert "carhunt_hook.py mailbox" not in cmds and "secret-guard" in cmds
    assert "carhunt_hook.py mailbox" in json.dumps(hooks.desired({}, python="/py"))


# a personal identity stack on other MCP names (no carhunt prefix): guards other browsers, kept as is
PERSONAL = {"matcher": "mcp__identity(-[a-d])?__.*",
            "hooks": [{"type": "command", "command": "$HOME/.claude/browsers/pw-identity hook pre"}]}


def test_identity_lease_block_from_browsers(home, tmp_path):
    from carhunt.access import mcp

    from .conftest import REPO
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"hooks": {"PreToolUse": [PERSONAL]}}))
    _, new, _ = hooks.plan(p, python="/py")
    m = mcp.identity_tool_matcher()
    assert m == "mcp__ch-identity(-[a-h])?__.*"
    ident = {ev: [h["command"] for g in gs if g.get("matcher") == m for h in g["hooks"]]
             for ev, gs in new["hooks"].items()}
    lease = str(REPO / "browsers" / "bin" / "pw-identity")
    assert ident["PreToolUse"] == [f"{lease} hook pre"]
    assert ident["PostToolUse"] == ident["PostToolUseFailure"] == [f"{lease} hook post"]
    assert new["hooks"]["PreToolUse"][0] == PERSONAL, "personal stack untouched and doesn't suppress ours"
    hooks.write(p, new)
    assert hooks.plan(p, python="/py")[2] == "", "idempotent"
    assert any("identity lease" in line for line in hooks.describe(new["hooks"]))
    _, removed, _ = hooks.plan(p, remove=True)
    assert removed == {"hooks": {"PreToolUse": [PERSONAL]}}


def test_cli_install_targets_agent_settings_only(home, monkeypatch, capsys):
    from carhunt.cli import main
    user = hooks.user_settings_path()
    assert str(user).startswith(str(home.parent)), "tests never see the real ~/.claude"
    target = home / "claude" / "settings.json"
    target.unlink()
    assert main(["hooks", "install", "--yes"]) == 0
    data = json.loads(target.read_text())
    assert "secret-guard" in json.dumps(data) and "pw-identity hook pre" in json.dumps(data)
    assert not user.exists()
    assert (home / "hooks" / "guards.json").is_file()
    assert main(["hooks", "show"]) == 0
    assert "PreToolUse: secret-guard" in capsys.readouterr().out


def test_statusline_probe(home, tmp_path):
    from .conftest import REPO
    assert hooks.probe_statusline(str(REPO / "hooks" / "statusline.sh"))
    assert not hooks.probe_statusline("echo plain")
