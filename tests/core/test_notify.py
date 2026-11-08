import json

import pytest

from carhunt.core import notify

TOKEN = "123456789:" + "A" * 35  # synthetic, bot-token shaped
CHAT = "555000"


class FakeTelegram:
    def __init__(self, fake_http):
        self.next_id = 100
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.callbacks: list[dict] = []
        self.fail = None
        self.srv = fake_http(self.handle)

    def handle(self, method, path, headers, body):
        prefix = f"/bot{TOKEN}/"
        if not path.startswith(prefix):
            return 404, {"ok": False, "description": "Not Found"}
        if self.fail:
            return self.fail
        name = path[len(prefix):]
        if name == "sendMessage":
            self.next_id += 1
            self.sent.append({**body, "message_id": self.next_id})
            return 200, {"ok": True, "result": {"message_id": self.next_id}}
        if name == "getUpdates":
            off = body.get("offset") or 0
            return 200, {"ok": True, "result": [u for u in self.updates if u["update_id"] >= off]}
        if name == "answerCallbackQuery":
            self.callbacks.append(body)
            return 200, {"ok": True, "result": True}
        return 404, {"ok": False, "description": "no method"}

    def reply(self, uid, text, to=None, chat=CHAT):
        m = {"message_id": 900 + uid, "chat": {"id": int(chat)}, "text": text}
        if to:
            m["reply_to_message"] = {"message_id": to}
        self.updates.append({"update_id": uid, "message": m})

    def press(self, uid, to, data, chat=CHAT):
        self.updates.append({"update_id": uid, "callback_query": {
            "id": f"cb{uid}", "data": data, "message": {"message_id": to, "chat": {"id": int(chat)}}}})


@pytest.fixture
def tg(fake_http, write_config, monkeypatch):
    t = FakeTelegram(fake_http)
    write_config({"owner": {"tz": "Europe/Paris"},
                  "notify": {"backend": "telegram", "quiet_hours": "21:30-09:30",
                             "telegram": {"bot_token": "secret:telegram_bot_token",
                                          "chat_id": "secret:telegram_chat_id", "api_base": t.srv.url}}})
    monkeypatch.setenv("CARHUNT_SECRET_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("CARHUNT_SECRET_TELEGRAM_CHAT_ID", CHAT)
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T12:00")
    return t


@pytest.mark.parametrize("kind", ["fyi", "info", "progress", ""])
def test_fyi_and_unknown_kinds_refused(tg, kind):
    with pytest.raises(notify.Refused):
        notify.send("sent the opener", agent="outreach", kind=kind)
    assert tg.sent == []


def test_refuses_buttons_off_ask_and_secret_shaped_text(tg):
    with pytest.raises(notify.Refused, match="buttons only"):
        notify.send("x", agent="a", kind="digest", buttons=["A"])
    with pytest.raises(notify.Refused, match="secret"):
        notify.send(f"token is {TOKEN}", agent="a", kind="urgent")
    with pytest.raises(notify.Refused, match="secret"):
        notify.send("login ok, password: hunter2", agent="a", kind="ask")
    assert tg.sent == []


def test_ask_with_buttons_and_free_ask(tg):
    ref = notify.send("Offer 31k or wait?", agent="outreach", kind="ask", buttons=["Offer", "Wait", "Drop"])
    assert ref == "telegram:101"
    kb = tg.sent[0]["reply_markup"]["inline_keyboard"]
    assert [b["text"] for b in kb[0]] == ["Offer", "Wait", "Drop"]
    assert "disable_notification" not in tg.sent[0]
    notify.send("Which day suits the viewing?", agent="vet", kind="ask")
    assert tg.sent[1]["reply_markup"]["force_reply"] is True


def test_quiet_hours_hold_digest_and_ask_silence_urgent(tg, monkeypatch):
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T23:00")
    r = notify.deliver("evening digest", agent="overseer", kind="digest")
    assert r.status == "held" and (r.until.hour, r.until.minute, r.until.day) == (9, 30, 9)
    assert notify.deliver("decide?", agent="outreach", kind="ask", buttons=["Y", "N"]).status == "held"
    r = notify.deliver("cardb down, restart failed", agent="overseer", kind="urgent")
    assert r.status == "sent" and r.silent
    assert len(tg.sent) == 1 and tg.sent[0]["disable_notification"] is True
    # still night: nothing flushed
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-09T07:00")
    assert notify.flush() == 0
    # morning: held ones go out (in order) before the next message
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-09T09:31")
    notify.send("morning digest", agent="overseer", kind="digest")
    assert [m["text"] for m in tg.sent[1:]] == ["evening digest", "decide?", "morning digest"]
    assert tg.sent[2]["reply_markup"]["inline_keyboard"]


def test_quiet_mode_override(tg, write_config, monkeypatch):
    import yaml

    from carhunt.core import paths
    cfg = yaml.safe_load(paths.config_file().read_text())
    cfg["notify"]["quiet"] = {"ask": "silent"}
    write_config(cfg)
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T23:00")
    assert notify.deliver("decide?", agent="a", kind="ask").silent


def test_replies_route_to_the_sending_agent(tg):
    a = int(notify.send("Seller asks for a deposit. OK?", agent="outreach-pt", kind="ask",
                        buttons=["No deposit", "Up to 500"]).split(":")[1])
    b = int(notify.send("Which import route?", agent="vet", kind="ask").split(":")[1])
    tg.reply(1, "Go with route B", to=b)
    tg.press(2, a, "1")
    tg.reply(3, "how is it going?")                 # unthreaded -> default agent
    tg.reply(4, "spam", chat="777")                 # other chat -> ignored
    assert notify.poll(timeout=0) == 3
    vet = notify.inbox("vet").list()
    assert [(i["id"], i["text"], i["kind"]) for i in vet] == [("tg-1", "Go with route B", "text")]
    assert vet[0]["re_text"].startswith("Which import route")
    pt = notify.inbox("outreach-pt").list()
    assert pt[0]["text"] == "Up to 500" and pt[0]["kind"] == "button"
    assert tg.callbacks[0]["callback_query_id"] == "cb2"
    assert [i["text"] for i in notify.inbox("overseer").list()] == ["how is it going?"]
    # offset persisted: a second poll adds nothing
    assert notify.poll(timeout=0) == 0
    assert tg.srv.requests[-1]["body"]["offset"] == 5


def test_inbox_ack_and_wait(tg):
    ref = int(notify.send("Pick one", agent="vet", kind="ask").split(":")[1])
    box = notify.inbox("vet")
    assert box.wait(timeout=0.2, poll=True) == []
    tg.reply(10, "the blue one", to=ref)
    items = box.wait(timeout=5)  # drives the poller itself
    assert [i["text"] for i in items] == ["the blue one"]
    assert box.ack("tg-10", "tg-999") == ["tg-999"]
    assert box.list() == [] and len(box.list(unacked=False)) == 1
    assert box.add({"id": "tg-10", "text": "dup"}) is False


def test_errors_never_leak_the_token(tg):
    tg.fail = (401, {"ok": False, "description": f"Unauthorized bot{TOKEN}"})
    with pytest.raises(notify.NotifyError) as e:
        notify.send("x", agent="a", kind="urgent")
    assert TOKEN not in str(e.value) and "401" in str(e.value)
    tg.srv.close()  # connection refused
    with pytest.raises(notify.NotifyError) as e:
        notify.send("x", agent="a", kind="urgent")
    assert TOKEN not in str(e.value) and "123456789" not in str(e.value)


def test_long_text_split_buttons_on_last_part(tg):
    notify.send("line\n" * 1500, agent="overseer", kind="ask", buttons=["ok"])
    assert len(tg.sent) == 2 and "reply_markup" not in tg.sent[0] and "reply_markup" in tg.sent[1]
    # a reply to either part reaches the agent
    rec = json.loads((notify.paths.home() / "notify" / "sent.jsonl").read_text().splitlines()[0])
    assert rec["ids"] == [101, 102]


def test_stdout_and_none_backends(write_config, capsys, monkeypatch):
    write_config({"owner": {"tz": "UTC"}, "notify": {"backend": "stdout"}})
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-08T12:00")
    assert notify.deliver("digest text", agent="overseer", kind="digest").status == "sent"
    assert "digest text" in capsys.readouterr().out
    write_config({"owner": {"tz": "UTC"}, "notify": {"backend": "none"}})
    assert notify.deliver("digest text", agent="overseer", kind="digest").status == "dropped"


def test_cli_send_exit_codes(tg, capsys):
    from carhunt import cli
    assert cli.main(["notify", "send", "--agent", "a", "--kind", "fyi", "done"]) == 10
    assert cli.main(["notify", "send", "--agent", "a", "--kind", "ask", "--buttons", "Y|N", "go?"]) == 0
    assert "sent ref=telegram:101" in capsys.readouterr().out
    tg.reply(1, "Y please", to=101)
    assert cli.main(["notify", "poll", "--once"]) == 0
    assert cli.main(["notify", "inbox", "list", "--agent", "a", "--json"]) == 0
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["text"] == "Y please"
    assert cli.main(["notify", "inbox", "ack", "--agent", "a", "tg-1"]) == 0
    assert cli.main(["notify", "inbox", "wait", "--agent", "a", "--timeout", "0.1", "--no-poll"]) == 1


def test_wait_without_telegram_does_not_spin(write_config, monkeypatch):
    import time
    write_config({"owner": {"tz": "UTC"}, "notify": {"backend": "none"}})
    calls = []
    monkeypatch.setattr(notify, "poll", lambda *a, **k: calls.append(1) or 0)
    t = time.monotonic()
    assert notify.inbox("x").wait(timeout=0.5, interval=0.1) == []
    assert calls == [] and time.monotonic() - t >= 0.5
    from carhunt import cli
    assert cli.main(["notify", "poll"]) == 0  # returns instead of looping
