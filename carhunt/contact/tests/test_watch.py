"""Watcher: dedupe, cursor store, cardb + inbox logging, /dev/null refusal, WhatsApp poll via fake wacli."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from carhunt.contact import deps
from carhunt.contact.channels.base import Channel, Msg, SendResult
from carhunt.contact.channels.whatsapp import WhatsApp
from carhunt.contact.watch import Cursors, inbox_path, pass_once

from .conftest import FAKE_WACLI, NOW, PT_NUM, REPO, car, msg

T0 = NOW - timedelta(hours=1)


class FakeChannel(Channel):
    name, kind = "fake", "chat"

    def __init__(self, items):
        super().__init__({})
        self.items = items
        self.calls = []

    def poll(self, since):
        self.calls.append(since)
        return [x for x in self.items if x[1].at >= since]

    def send(self, to, text):
        return SendResult(False)

    def read_thread(self, to, limit=50):
        return []


def _db(stub):
    return deps.Cardb(stub.url, "t")


def test_dedupe_and_cursor(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path / "h"))
    stub.cars["A9"] = car(PT_NUM)
    items = [(PT_NUM, Msg(T0, False, "Sim, está disponível", id="W1")),
             (PT_NUM, Msg(T0 + timedelta(minutes=1), True, "our own", id="W2")),
             (PT_NUM, Msg(T0 + timedelta(minutes=2), False, "", id="W3")),  # empty protocolMessage (edit/delete)
             ("351555999999", Msg(T0 + timedelta(minutes=3), False, "Sou o vendedor, novo número", id="W4"))]
    ch = FakeChannel(items)
    cur = Cursors(tmp_path / "cursors.json")
    lines = []
    new = pass_once([ch], db=_db(stub), agent="outreach", cursors=cur, now=NOW, out=lines.append)
    assert [n["external_id"] for n in new] == ["W1", "W4"]
    assert new[0]["car"] == "A9" and "cardb_error" in new[1]  # unknown number still reaches the agent
    assert len(stub.messages) == 1 and stub.messages[0]["direction"] == "in" and stub.messages[0]["text"] == "Sim, está disponível"
    again = pass_once([ch], db=_db(stub), agent="outreach", cursors=cur, now=NOW, out=lines.append)
    assert again == [] and len(stub.messages) == 1
    assert len((inbox_path("outreach")).read_text().splitlines()) == 2
    st = json.loads((tmp_path / "cursors.json").read_text())
    assert st["fake"]["since"].startswith((T0 + timedelta(minutes=3)).isoformat()[:16])
    assert len(lines) == 2


def test_refuses_devnull_stdout(tmp_path):
    r = subprocess.run([sys.executable, "-m", "carhunt.contact", "watch", "--once", "--no-db", "--channels", "whatsapp"],
                       env={"PATH": "/usr/bin:/bin", "CARHUNT_HOME": str(tmp_path), "PYTHONPATH": str(REPO)},
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, cwd=REPO)
    assert r.returncode == 2 and "/dev/null" in r.stderr


def test_whatsapp_poll_via_fake_wacli(tmp_path, monkeypatch):
    root = tmp_path / "wacli"
    (root / "chats").mkdir(parents=True)
    (root / "chats" / f"{PT_NUM}.json").write_text(json.dumps([
        msg(T0, False, "Olá, sim", ChatJID=f"{PT_NUM}@s.whatsapp.net"),
        msg(T0 + timedelta(minutes=1), True, "Obrigado", ChatJID=f"{PT_NUM}@s.whatsapp.net")]))
    (root / "chats" / "grp.json").write_text(json.dumps([msg(T0, False, "group noise", ChatJID="1@g.us")]))  # privacy-check: allow
    monkeypatch.setenv("FAKE_WACLI_ROOT", str(root))
    wa = WhatsApp({}, wacli=str(FAKE_WACLI))
    got = wa.poll(T0 - timedelta(minutes=5))
    assert [(cp, m.text) for cp, m in got] == [(PT_NUM, "Olá, sim")]


def test_cli_once_writes_stdout_line(tmp_path, stub):
    root = tmp_path / "wacli"
    (root / "chats").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    (root / "chats" / f"{PT_NUM}.json").write_text(json.dumps([
        msg(now - timedelta(minutes=10), False, "Tem interesse ainda?", ChatJID=f"{PT_NUM}@s.whatsapp.net")]))
    stub.cars["A9"] = car(PT_NUM)
    env = {"PATH": "/usr/bin:/bin", "CARHUNT_HOME": str(tmp_path / "h"), "PYTHONPATH": str(REPO),
           "CARHUNT_WACLI": str(FAKE_WACLI), "FAKE_WACLI_ROOT": str(root), "CARDB_URL": stub.url,
           "CARHUNT_SECRET_CARDB_TOKEN": "t"}
    r = subprocess.run([sys.executable, "-m", "carhunt.contact", "watch", "--once", "--channels", "whatsapp"],
                       env=env, capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stderr
    item = json.loads(r.stdout.splitlines()[0])
    assert item["text"] == "Tem interesse ainda?" and item["car"] == "A9"
