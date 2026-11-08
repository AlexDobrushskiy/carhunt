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


def test_skips_ours_where_foreign_covers(home):
    cur = {"PreToolUse": [{"matcher": "mcp__identity.*", "hooks": [{"command": "$HOME/b/pw-identity hook pre"}]}],
           "Stop": [{"hooks": [{"command": "/x/other-mailbox claude-hook", "asyncRewake": True}]}]}
    want = hooks.desired(cur, python="/py")
    cmds = json.dumps(want)
    assert "identity-pre" not in cmds and "mailbox" not in cmds and "secret-guard" in cmds


def test_statusline_probe(home, tmp_path):
    from .conftest import REPO
    assert hooks.probe_statusline(str(REPO / "hooks" / "statusline.sh"))
    assert not hooks.probe_statusline("echo plain")
