"""Email channel + Gmail client, offline against FakeGmail (and a fake urlopen for the transport)."""
from __future__ import annotations

import io
import json
import socket
import urllib.error
from datetime import timedelta

import pytest

from carhunt.contact.channels.base import DELIVERED, FAILED, UNKNOWN
from carhunt.contact.channels.email import Email
from carhunt.contact.gmail import Gmail, GmailNetworkError, consent_url, exchange_code
from carhunt.contact.tests.fakes.fake_gmail import NOW, FakeGmail

SELLER = "sales@dealer.test"
ME = "owner@example.com"
PLUS = "owner+cars@example.com"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def cfg():
    return {"owner": {"tz": "Europe/Lisbon"},
            "contact": {"email": {"from_name": "Test Owner", "from_address": ME, "plus_tag": "cars",
                                  "label": "cars", "verify_wait_s": 0}}}


@pytest.fixture
def gm():
    g = FakeGmail()
    g.cars = g.add_label("cars")
    return g


def seller_thread(gm, **kw):
    """Our opener + the seller's reply, both labelled cars."""
    ours = gm.add(frm=f"Test Owner <{ME}>", to=SELLER, subject="VW ID.4", labels=["SENT", gm.cars],
                  minutes_ago=120, message_id="<open@mail.example.com>")
    reply = gm.add(frm=f"Dealer <{SELLER}>", to=PLUS, subject="Re: VW ID.4", thread=ours["threadId"],
                   labels=[gm.cars, "UNREAD"], minutes_ago=30, message_id="<reply@dealer.test>",
                   references="<open@mail.example.com>", **kw)
    return ours["threadId"], reply


def sends(gm):
    return [c for c in gm.calls if c[:2] == ("POST", "messages/send")]


# -- dry run ------------------------------------------------------------------------------------

def test_dry_run_new_thread_headers_no_writes(cfg, gm):
    out = Email(cfg, gmail=gm, subject="Your VW ID.4").dry_run(SELLER, "Hello, still available?")
    h = out["headers"]
    assert h["From"] == f"Test Owner <{ME}>"
    assert h["Reply-To"] == PLUS
    assert h["Subject"] == "Your VW ID.4"
    assert "In-Reply-To" not in h and out["thread"] is None
    assert gm.writes() == []


def test_dry_run_existing_thread_threads_reply(cfg, gm):
    tid, _ = seller_thread(gm)
    out = Email(cfg, gmail=gm).dry_run(SELLER, "Thanks!")
    h = out["headers"]
    assert out["thread"] == tid
    assert h["In-Reply-To"] == "<reply@dealer.test>"
    assert h["References"] == "<open@mail.example.com> <reply@dealer.test>"
    assert h["Subject"] == "Re: VW ID.4"
    assert gm.writes() == []


def test_dry_run_offline_makes_no_calls(cfg, gm):
    out = Email(cfg, gmail=gm, subject="S", offline=True).dry_run(SELLER, "hi")
    assert out["headers"]["Reply-To"] == PLUS
    assert gm.calls == []


def test_new_thread_without_subject_is_refused(cfg, gm):
    out = Email(cfg, gmail=gm).dry_run(SELLER, "hi")
    assert "needs a subject" in out["error"]
    r = Email(cfg, gmail=gm).send(SELLER, "hi")
    assert not r.ok and sends(gm) == []


# -- send / verify ------------------------------------------------------------------------------

def test_send_reply_into_thread_labels_and_verifies(cfg, gm):
    tid, _ = seller_thread(gm)
    ch = Email(cfg, gmail=gm)
    r = ch.send(SELLER, "Thanks, any accidents?")
    assert r.ok and r.raw["thread"] == tid
    sent = gm.msgs[r.external_id]
    assert sent["threadId"] == tid and gm.cars in sent["labelIds"]
    e = sent["email"]
    assert e["Reply-To"] == PLUS and e["In-Reply-To"] == "<reply@dealer.test>" and e["To"] == SELLER
    assert ch.verify(SELLER, "x", r) == DELIVERED


def test_send_new_thread_with_attachment(cfg, gm, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4 synthetic")
    ch = Email(cfg, gmail=gm, subject="Car documents", attach=[str(f)])
    r = ch.send("New.Seller@Dealer.test", "See attached.")
    assert r.ok
    e = gm.msgs[r.external_id]["email"]
    assert e["To"] == "new.seller@dealer.test" and e["Subject"] == "Car documents"
    assert [p.get_filename() for p in e.iter_attachments()] == ["doc.pdf"]
    assert ch.read_thread("new.seller@dealer.test")[0].media == "doc.pdf"


def test_send_creates_missing_label(cfg):
    gm = FakeGmail()
    r = Email(cfg, gmail=gm, subject="S").send(SELLER, "hi")
    assert r.ok and "cars" in gm.label_names.values()


def test_reply_to_thread_only_derives_recipient(cfg, gm):
    tid, _ = seller_thread(gm, reply_to="Person <person@dealer.test>")
    r = Email(cfg, gmail=gm).send(f"#{tid}", "ok")
    assert r.raw["to"] == ["person@dealer.test"]
    assert gm.msgs[r.external_id]["email"]["To"] == "person@dealer.test"


def test_new_thread_opt_skips_latest_thread(cfg, gm):
    seller_thread(gm)
    r = Email(cfg, gmail=gm, subject="Second car", new_thread=True).send(SELLER, "hi")
    assert r.raw["thread"] not in {m["threadId"] for m in gm.msgs.values() if m["id"] != r.external_id}


def test_pre_request_network_error_retried_then_delivered(cfg, gm):
    gm.fail("POST messages/send", "before", times=2)
    ch = Email(cfg, gmail=gm, subject="S")
    r = ch.send(SELLER, "hi")
    assert r.ok and len(gm.sent()) == 1
    assert gm.sleeps == [20.0, 20.0]
    assert ch.verify(SELLER, "hi", r) == DELIVERED


def test_pre_request_errors_exhausted_is_failed_not_sent(cfg, gm):
    gm.fail("POST messages/send", "before", times=4)
    ch = Email(cfg, gmail=gm, subject="S")
    r = ch.send(SELLER, "hi")
    assert not r.ok and r.raw["maybe_sent"] is False
    assert len(sends(gm)) == 4 and gm.sent() == []
    assert ch.verify(SELLER, "hi", r) == FAILED


def test_post_request_error_checks_sent_no_double_send(cfg, gm):
    gm.fail("POST messages/send", "after")  # Gmail stored it, the response was lost
    ch = Email(cfg, gmail=gm, subject="S")
    r = ch.send(SELLER, "hi")
    assert len(sends(gm)) == 1 and len(gm.sent()) == 1
    assert r.ok and r.external_id == gm.sent()[0]["id"] and "recovered_from" in r.raw
    assert gm.cars in gm.sent()[0]["labelIds"]
    assert ch.verify(SELLER, "hi", r) == DELIVERED


def test_post_request_error_not_in_sent_is_unknown(cfg, gm):
    gm.fail("POST messages/send", "http", status=503)
    ch = Email(cfg, gmail=gm, subject="S")
    r = ch.send(SELLER, "hi")
    assert not r.ok and r.raw["maybe_sent"] is True
    assert len(sends(gm)) == 1
    assert ch.verify(SELLER, "hi", r) == UNKNOWN
    assert len(sends(gm)) == 1  # verify never re-sends


def test_http_4xx_is_failed(cfg, gm):
    gm.fail("POST messages/send", "http", status=400)
    ch = Email(cfg, gmail=gm, subject="S")
    r = ch.send(SELLER, "hi")
    assert ch.verify(SELLER, "hi", r) == FAILED


# -- read ---------------------------------------------------------------------------------------

def test_read_thread_from_me_detection(cfg, gm):
    tid, _ = seller_thread(gm)
    gm.add(frm=PLUS, to=SELLER, subject="Re: VW ID.4", thread=tid, labels=[gm.cars], minutes_ago=10)
    gm.add(frm="other@elsewhere.test", to=ME, subject="unrelated", minutes_ago=5)
    msgs = Email(cfg, gmail=gm).read_thread(SELLER)
    assert [m.from_me for m in msgs] == [True, False, True]
    assert msgs[1].sender == SELLER and msgs[1].text == "hi"
    assert msgs[0].at < msgs[1].at < msgs[2].at
    assert [m.from_me for m in Email(cfg, gmail=gm).read_thread(f"#{tid}")] == [True, False, True]


# -- poll ---------------------------------------------------------------------------------------

def test_poll_after_epoch_label_or_plus(cfg, gm):
    _, reply = seller_thread(gm)  # labelled, 30 min ago
    plus_only = gm.add(frm="form@marketplace.test", to=PLUS, subject="New message", labels=["INBOX"], minutes_ago=10)
    gm.add(frm="news@shop.test", to=ME, subject="Sale", labels=["INBOX"], minutes_ago=5)  # to: matches, +tag doesn't
    gm.add(frm=PLUS, to=SELLER, labels=[gm.cars, "SENT"], minutes_ago=4)  # our own
    gm.add(frm="old@dealer.test", to=PLUS, labels=[gm.cars], minutes_ago=60 * 24)  # before since-overlap
    since = NOW - timedelta(hours=1)
    got = Email(cfg, gmail=gm).poll(since)
    assert [m.id for _, m in got] == [reply["id"], plus_only["id"]]
    assert [who for who, _ in got] == [SELLER, "form@marketplace.test"]
    qs = [c[2]["q"] for c in gm.calls if c[1] == "messages"]
    start = int((since - timedelta(seconds=900)).timestamp())
    assert qs == [f"{{label:cars to:{PLUS}}} after:{start}"]
    assert all("in:inbox" not in q and "newer_than" not in q for q in qs)


def test_poll_overlap_catches_late_label(cfg, gm):
    m = gm.add(frm=SELLER, to=ME, labels=[gm.cars], minutes_ago=5)  # labelled by mailroute later
    got = Email(cfg, gmail=gm).poll(NOW - timedelta(minutes=2))
    assert [x.id for _, x in got] == [m["id"]]


# -- Gmail transport (real client, fake urlopen) --------------------------------------------------

class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Wire:
    """Scripted urlopen: each entry is a dict (JSON reply) or an exception to raise."""

    def __init__(self, *script):
        self.script, self.reqs = list(script), []

    def __call__(self, req, timeout=None):
        self.reqs.append(req)
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return Resp(json.dumps(step).encode())


TOKEN = {"access_token": "at", "expires_in": 3600}


@pytest.fixture
def token_env(monkeypatch):
    monkeypatch.setenv("CARHUNT_SECRET_GMAIL_TOKEN", json.dumps(
        {"client_id": "cid", "client_secret": "cs", "refresh_token": "rt"}))


def dns():
    return urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))


def test_client_refreshes_and_retries_pre_request_post(token_env):
    w = Wire(TOKEN, dns(), dns(), {"id": "m1", "threadId": "t1"})
    g = Gmail(urlopen=w, sleep=lambda s: None)
    assert g.send_raw(b"raw")["id"] == "m1"
    assert w.reqs[0].full_url.endswith("/token") and b"refresh_token=rt" in w.reqs[0].data
    assert w.reqs[-1].get_header("Authorization") == "Bearer at"
    assert "rt" not in repr(g) and "at" not in repr(g).replace("Gmail", "")


def test_client_post_timeout_not_retried(token_env):
    w = Wire(TOKEN, TimeoutError("read timed out"), {"id": "dup"})
    g = Gmail(urlopen=w, sleep=lambda s: None)
    with pytest.raises(GmailNetworkError) as e:
        g.send_raw(b"raw")
    assert e.value.maybe_sent is True and len(w.script) == 1


def test_client_get_retries_any_network_error_and_401_refresh(token_env):
    w = Wire(TOKEN, TimeoutError("slow"), urllib.error.HTTPError("u", 401, "x", {}, None),
             TOKEN, {"labels": [{"id": "L1", "name": "cars"}]})
    g = Gmail(urlopen=w, sleep=lambda s: None)
    assert g.label_id("cars") == "L1"


def test_client_missing_secret_is_auth_error(monkeypatch):
    monkeypatch.setattr("carhunt.contact.deps.secret", lambda name: None)
    from carhunt.contact.gmail import GmailAuthError

    with pytest.raises(GmailAuthError):
        Gmail(urlopen=Wire()).labels()


def test_consent_url_and_code_exchange():
    client = {"installed": {"client_id": "cid", "client_secret": "cs"}}
    u = consent_url(client, ["https://www.googleapis.com/auth/gmail.modify"], "http://127.0.0.1:9/", "st")
    assert "access_type=offline" in u and "gmail.modify" in u and "state=st" in u
    w = Wire({"refresh_token": "rt2", "access_token": "a"})
    assert exchange_code(client, "code1", "http://127.0.0.1:9/", urlopen=w)["refresh_token"] == "rt2"
    assert b"code=code1" in w.reqs[0].data
