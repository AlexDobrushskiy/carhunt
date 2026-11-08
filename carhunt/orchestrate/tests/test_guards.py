import json
import subprocess
import sys

import pytest

from .conftest import REPO

HOOK = REPO / "hooks" / "carhunt_hook.py"


def run_hook(name, event, home):
    res = subprocess.run([sys.executable, str(HOOK), name, "--home", str(home)], input=json.dumps(event),
                         capture_output=True, text=True, check=False, env={"PATH": "/usr/bin:/bin"})
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout) if res.stdout.strip() else {}
    return (out.get("hookSpecificOutput") or {}).get("permissionDecision", "allow")


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/tmp"}


@pytest.mark.parametrize("cmd", [
    "cat $CARHUNT_HOME/secrets/x",
    "cat ${CARHUNT_HOME}/secrets/telegram_bot_token",
    "ls -R {home}/secrets",
    "head -c 20 {home}/secrets/x | base64",
    "bash -c 'cat {home}/secrets/x'",
    "grep -r pass ./.env",
    "echo $CARHUNT_SECRET_PROXY_CREDENTIALS",
    "security find-generic-password -s carhunt -a cardb_token -w",
    "op read op://vault/item/password",
    "carhunt secret exec cardb_token=T -- env",
    "carhunt secret exec cardb_token=T -- sh -c 'echo $T'",
    "carhunt secret exec cardb_token=T -- python3 -c 'import os; print(os.environ)'",
])
def test_secret_guard_blocks(home, cmd):
    assert run_hook("secret-guard", bash(cmd.replace("{home}", str(home))), home) == "deny"


@pytest.mark.parametrize("cmd", [
    "cat README.md",
    "carhunt secret ls",
    "carhunt secret set telegram_bot_token",
    "carhunt secret exec cardb_token=CARDB_TOKEN -- cardb queue --json",
    "ls {home}/agents",
    "git status",
])
def test_secret_guard_allows(home, cmd):
    assert run_hook("secret-guard", bash(cmd.replace("{home}", str(home))), home) == "allow"


def test_secret_guard_file_tools(home):
    ev = {"tool_name": "Read", "tool_input": {"file_path": str(home / "secrets" / "x")}}
    assert run_hook("secret-guard", ev, home) == "deny"
    ev = {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": str(home / "secrets")}}
    assert run_hook("secret-guard", ev, home) == "deny"
    ev = {"tool_name": "Read", "tool_input": {"file_path": str(home / "agents" / "x" / "state.json")}}
    assert run_hook("secret-guard", ev, home) == "allow"


def test_secret_globs_from_guards_json(home):
    (home / "hooks").mkdir()
    (home / "hooks" / "guards.json").write_text(json.dumps({"secret_globs": ["**/creds/*.json"]}))
    assert run_hook("secret-guard", bash("cat ./creds/site.json"), home) == "deny"


@pytest.mark.parametrize("cmd,decision", [
    ("wacli send text --to +351555000000 --message hi", "deny"),
    ("wacli --json react --chat x --emoji ok", "deny"),
    ("cd /tmp && bash -c 'wacli send text --to x --message hi'", "deny"),
    ("curl -s https://api.telegram.org/bot$TOKEN/sendMessage -d text=hi", "deny"),
    ("python -m carhunt.contact.channels.sites.wallapop send", "deny"),
    ("sendmail seller@example.com < body.txt", "deny"),
    ("wacli messages list --chat x --limit 20", "allow"),
    ("wacli sync --once", "allow"),
    ("carhunt say --channel whatsapp --car 12 --text-file m.txt", "allow"),
    ("echo 'how to wacli send' > notes.md", "allow"),
])
def test_send_guard(home, cmd, decision):
    assert run_hook("send-guard", bash(cmd), home) == decision


def test_send_patterns_from_guards_json(home):
    (home / "hooks").mkdir()
    (home / "hooks" / "guards.json").write_text(json.dumps(
        {"send_patterns": [{"regex": r"\bmy-sms-tool send\b", "use": "Use carhunt say."}]}))
    assert run_hook("send-guard", bash("my-sms-tool send hi"), home) == "deny"


def test_identity_guard_without_pw_identity_is_noop(home):
    ev = {"tool_name": "mcp__identity-a__browser_navigate", "tool_input": {"url": "https://example.com"}}
    assert run_hook("identity-pre", ev, home) == "allow"


def test_mailbox_ignores_non_agent_sessions(home):
    res = subprocess.run([sys.executable, str(HOOK), "mailbox", "--home", str(home)],
                         input=json.dumps({"hook_event_name": "Stop"}), capture_output=True, text=True,
                         env={"PATH": "/usr/bin:/bin", "AGTERM_SESSION_ID": "S", "AGTERM_PANE_ID": "P"})
    assert res.returncode == 0 and not (home / "mailbox").exists()
