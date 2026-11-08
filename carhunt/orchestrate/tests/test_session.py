import json
import subprocess
import time

from carhunt.orchestrate import msg, session, state
from carhunt.orchestrate.launch import launch

SID = "11111111-2222-3333-4444-555555555555"
TREE = {"result": {"workspaces": [{"sessions": [{"id": SID, "name": "carhunt-dummy",
                                                 "surfaces": [{"kind": "left", "paneID": "PANE-1"}]}]}]}}


class Ctl:
    def __init__(self, screen="❯ \n x | ctx:47% \n"):
        self.calls = []
        self.screen = screen

    def __call__(self, args, stdin=None, timeout=30):
        self.calls.append((args[1:], stdin))
        sub = args[1:3]
        out = ""
        if sub == ["window", "list"]:
            out = json.dumps({"result": {"windows": [{"id": "W", "open": True}]}})
        elif sub[0] == "tree":
            out = json.dumps(TREE)
        elif sub == ["session", "new"]:
            out = json.dumps({"result": {"id": SID}})
        elif sub == ["session", "text"]:
            out = self.screen
        return subprocess.CompletedProcess(args, 0, out, "")


def test_spawn_command_and_env(home):
    ctl = Ctl()
    be = session.AgtermBackend(ctl="agtermctl", runner=ctl, shell="/bin/zsh")
    sid = be.spawn("carhunt-x", "/tmp/a b", ["claude", "Read and execute /tmp/a b/brief.md."],
                   {"CARHUNT_AGENT": "x"}, after="ANCHOR")
    assert sid == SID
    args = ctl.calls[-1][0]
    assert args[:2] == ["session", "new"] and "--no-select" in args and args[args.index("--after") + 1] == "ANCHOR"
    command = args[args.index("--command") + 1]
    assert command.startswith("/bin/zsh -lc ") and "export CARHUNT_AGENT=x" in command and "exec claude" in command


def test_ctx_file_beats_screen(home):
    be = session.AgtermBackend(runner=Ctl())
    assert be.ctx_percent(SID) == 47
    session.ctx_file(SID).parent.mkdir(parents=True)
    session.ctx_file(SID).write_text(json.dumps({"pct": 61, "ts": time.time()}))
    assert be.ctx_percent(SID) == 61
    session.ctx_file(SID).write_text(json.dumps({"pct": 61, "ts": time.time() - 3600}))
    assert be.ctx_percent(SID) == 47


def test_send_mailbox_when_receiver_listens(home, monkeypatch):
    ctl = Ctl()
    be = session.AgtermBackend(runner=ctl)
    monkeypatch.setattr(session.time, "sleep", lambda s: None)
    assert be.send(SID, "hello") == "type"  # no receiver marker -> typing fallback
    assert any(c[0][:2] == ["session", "type"] and c[1] == "hello" for c in ctl.calls)
    session.mailbox_marker(SID).parent.mkdir(parents=True)
    import os
    session.mailbox_marker(SID).write_text(json.dumps({"pid": os.getpid()}))
    assert be.send(SID, "hi again") == "mailbox"
    assert ctl.calls[-1][0][:2] == ["msg", "send"] and f"{SID}:PANE-1" in ctl.calls[-1][0]


def test_msg_resolves_role_to_active_agent(home, config, fake, dummy_role):
    sid = launch("dummy", backend=fake, config=config)
    out = msg.send("dummy", "check queue", backend=fake, sender="overseer")
    assert out["session"] == sid and fake.sent[-1][1] == "[carhunt from overseer] check queue"
    state.done("dummy")
    state.cleanup(fake)
    import pytest
    with pytest.raises(msg.MsgError, match="not open"):
        msg.send("dummy", "hello?", backend=fake)
