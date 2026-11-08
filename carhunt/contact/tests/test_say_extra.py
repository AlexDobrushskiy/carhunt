"""Guard/pipeline cases beyond the EV scenarios: lock, opener rules, caps, failures, cardb, reconcile."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from .conftest import AB_ME, AB_ROLE, ES_NUM, NOW, PT_NUM, REPO, car, msg, sent

PT2 = "351555333333"
OPEN = ["--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Olá, ainda está disponível? Teve algum acidente?",
        "--opener"]


def test_lock_prevents_two_concurrent_openers(tree):
    """EV bug: two openers 4 s apart (2026-11-04). Two processes race; exactly one may send."""
    tree.stub.cars["B1"] = car(PT2)
    tree.write()
    a = tree.popen(*OPEN, FAKE_WACLI_SEND_DELAY="1.5")
    b = tree.popen("--channel", "whatsapp", "--car", "B1", "--to", PT2, "--text", "Bom dia, ainda está disponível?",
                   "--opener", FAKE_WACLI_SEND_DELAY="1.5")
    outs = [(p.wait(timeout=30), p.stdout.read()) for p in (a, b)]
    codes = sorted(c for c, _ in outs)
    assert codes == [0, 10], outs
    assert len(tree.wacli_sends()) == 1
    assert any("spacing" in o for c, o in outs if c == 10), outs
    assert len(tree.ledger_rows()) == 1


def test_dry_run_sends_nothing_and_prints_payload(tree):
    code, out = tree.run(*OPEN)
    assert code == 0 and "would send" in out and '"to": "+351555111111"' in out, out
    assert not tree.wacli_sends() and not tree.ledger_path.read_text()


def test_opener_url_refused(tree):
    code, out = tree.run(*OPEN[:-2], "Olá, ainda está disponível? https://example.invalid/ad/1", "--opener")
    assert code == 10 and "URL in an opener" in out, out


def test_opener_specs_refused(tree):
    code, out = tree.run(*OPEN[:-2], "Olá, o carro com 45000 km ainda está disponível?", "--opener")
    assert code == 10 and "specs in an opener" in out, out


def test_opener_too_many_questions(tree):
    code, out = tree.run(*OPEN[:-2], "Olá? Disponível? Acidentes? Fotos?", "--opener")
    assert code == 10 and "questions" in out, out


def test_opener_window_is_seller_local(tree):
    early = datetime(2026, 11, 10, 8, 50, tzinfo=timezone.utc)  # 08:50 Lisbon, 09:50 Madrid
    code, out = tree.run(*OPEN, now=early)
    assert code == 10 and "seller-local" in out, out
    code, out = tree.run("--channel", "whatsapp", "--car", "77", "--to", ES_NUM, "--text", "Hola, ¿sigue disponible?",
                         "--opener", me=AB_ME, role=AB_ROLE, now=early)
    assert code == 0, out


def _openers(n, start=NOW - timedelta(hours=2)):
    return [sent(start + timedelta(minutes=11 * i - 200), f"3515559{i:05d}", f"opener {i}", kind="opener") for i in range(n)]


def test_daily_opener_cap_and_home_reserve(tree):
    tree.ledger = _openers(16)
    es = ["--channel", "whatsapp", "--car", "77", "--to", ES_NUM, "--text", "Hola, ¿sigue disponible?", "--opener"]
    code, out = tree.run(*es, me=AB_ME, role=AB_ROLE)
    assert code == 10 and "outreach-home's until 15:00" in out, out
    code, out = tree.run(*OPEN)  # the home agent may take them
    assert code == 0, out
    late = datetime(2026, 11, 10, 15, 30, tzinfo=timezone.utc)
    assert tree.run(*es, me=AB_ME, role=AB_ROLE, now=late)[0] == 0
    tree.ledger = _openers(20)
    code, out = tree.run(*OPEN)
    assert code == 10 and "openers-daily: cap 20" in out, out


def test_cap_override_file(tree):
    tree.ledger = _openers(20)
    tree.write()
    (tree.home / "contact" / "cap_override.json").write_text(
        json.dumps({"date": "2026-11-10", "limits": {"openers-daily": 25}}))
    assert tree.run(*OPEN)[0] == 0


def test_pause_file(tree):
    tree.write()
    (tree.home / "PAUSE").write_text("")
    code, out = tree.run(*OPEN)
    assert code == 10 and "PAUSE" in out


def test_duplicate_text_refused(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(days=1), True, "Teve algum acidente?"),
                          msg(NOW - timedelta(hours=5), False, "Desculpe, não percebi")]
    tree.ledger = [sent(NOW - timedelta(days=1), PT_NUM, "Teve algum acidente?")]
    code, out = tree.run("--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Teve algum acidente?")
    assert code == 10 and "already sent" in out, out


def test_owner_typing_backoff(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=30), False, "Olá"),
                          msg(NOW - timedelta(minutes=5), True, "Respondo já"),
                          msg(NOW - timedelta(minutes=4), False, "Ok")]
    code, out = tree.run("--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Tem fotos do interior?")
    assert code == 10 and "owner wrote" in out, out


def test_group_chat_refused(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=30), False, "Olá", ChatJID="123@g.us")]  # privacy-check: allow
    code, out = tree.run("--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Olá")
    assert code == 10 and "group chat" in out, out


def test_unlisted_target_refused(tree):
    code, out = tree.run("--channel", "whatsapp", "--car", "A9", "--to", "351555999999", "--text", "x", "--opener")
    assert code == 10 and "is not a contact" in out, out


def test_failed_send_exit_11_and_not_counted(tree):
    code, out = tree.run(*OPEN, dry=False, FAKE_WACLI_FAIL="1")
    assert code == 11 and "number not on WhatsApp" in out, out
    assert tree.ledger_rows()[-1]["status"] == "failed"
    tree.ledger = tree.ledger_rows()
    tree.stub.cars["B1"] = car(PT2)
    code, out = tree.run("--channel", "whatsapp", "--car", "B1", "--to", PT2, "--text", "Olá, ainda está disponível?",
                         "--opener")
    assert code == 0, out  # a failed attempt doesn't stamp spacing (EV 2026-11-03)


def test_cardb_down_never_blocks_then_reconcile(tree):
    tree.chats[PT_NUM] = [msg(NOW - timedelta(minutes=10), False, "Olá")]
    tree.stub.fail_posts = True
    code, out = tree.run("--channel", "whatsapp", "--car", "A9", "--to", PT_NUM, "--text", "Tem o livro de revisões?",
                         dry=False)
    assert code == 0 and "reconcile" in out, out
    assert not tree.stub.messages
    tree.stub.fail_posts = False
    for _ in range(2):  # idempotent: the second run writes nothing new
        r = subprocess.run([sys.executable, "-m", "carhunt.contact", "ledger", "reconcile"], env=tree.env(),
                           capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, r.stderr
    assert len(tree.stub.messages) == 1
    assert tree.stub.messages[0]["dedupe_key"] == tree.ledger_rows()[0]["id"]
    assert tree.stub.messages[0]["direction"] == "out" and tree.stub.messages[0]["delivery"] == "sent"


def test_stale_agent_after_handover(tree):
    tree.active["outreach-home"] = "SUCCESSOR"
    code, out = tree.run(*OPEN)
    assert code == 10 and "not the active" in out


def test_owner_run_without_role(tree):
    code, out = tree.run(*OPEN, role="", CARDB_AUTHOR="")
    assert code == 0, out
