"""mailroute: inbox → car label by address/domain/thread only, offline against FakeGmail."""
from __future__ import annotations

import time
import xml.dom.minidom

import pytest

from carhunt.contact import mailroute
from carhunt.contact.ledger import FAILED, SENT, Entry, Ledger
from carhunt.contact.mailroute import Rules, filters_xml, is_freemail, launchd_plist, run_once
from carhunt.contact.tests.fakes.fake_gmail import FakeGmail

ME = "owner@example.com"
PLUS = "owner+cars@example.com"
FREE = "gmail.com"  # built-in freemail host (kept out of address literals for the privacy check)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def cfg():
    return {"contact": {
        "email": {"from_address": ME, "plus_tag": "cars", "label": "cars"},
        "mailroute": {"domains": ["marketplace.test", "autohaus.test"],
                      "never_touch": ["friend@autohaus.test", "family.test"],
                      "freemail": ["freemail.test"]}}}


@pytest.fixture
def gm():
    g = FakeGmail()
    g.cars = g.add_label("cars")
    return g


class FakeDb:
    def __init__(self, cars):
        self._cars = cars

    def cars(self, **_):
        return [{"id": c["id"], "status": c.get("status", "contacted"), "message_count": 1} for c in self._cars]

    def car(self, cid):
        return next(c for c in self._cars if c["id"] == cid)


class DownDb:
    def cars(self, **_):
        raise ConnectionError("cardb down")


DB = FakeDb([{"id": 7, "seller": {"name": "P. Seller", "email": "pseller@freemail.test"}},
             {"id": 8, "notes": "dealer contact: info@dealer-one.test"},
             {"id": 9, "status": "new", "seller": {"email": "untouched@never-contacted.test"}}])


def labels(gm, m):
    return gm.msgs[m["id"]]["labelIds"]


def moved(gm, m):
    return "INBOX" not in labels(gm, m) and gm.cars in labels(gm, m)


def stayed(gm, m):
    return "INBOX" in labels(gm, m) and gm.cars not in labels(gm, m)


def test_moves_known_seller_dealer_domain_and_thread(cfg, gm, tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append(Entry(channel="email", to="x@thread-only.test#tKNOWN", text="hi", status=SENT, t=time.time()))
    seller = gm.add(frm="P. Seller <pseller@freemail.test>", to=ME, subject="Re: your question")
    dealer_db = gm.add(frm="Sales <person@dealer-one.test>", to=ME, subject="Offer")  # domain from a cardb address
    site = gm.add(frm="noreply@mail.marketplace.test", to=ME, subject="New message")  # config domain, subdomain
    known_thread = gm.add(frm="someone@unrelated.test", to=ME, subject="Re: car", thread="tKNOWN")
    plus = gm.add(frm="form@anything.test", to=PLUS, subject="Contact form")
    other = gm.add(frm="shop@unrelated.test", to=ME, subject="Your order")

    s = run_once(cfg, gmail=gm, db=DB, ledger=led)

    for m in (seller, dealer_db, site, known_thread, plus):
        assert moved(gm, m), gm.msgs[m["id"]]
    assert stayed(gm, other)
    assert "UNREAD" in labels(gm, seller)  # never marks read
    assert s["moved"] == 5 and s["threads_moved"] == 5 and not s["dry_run"]
    whys = {mv["thread"]: mv["why"] for mv in s["moves"]}
    assert whys[known_thread["threadId"]] == "known thread"
    assert whys[plus["threadId"]] == "to plus-address"
    assert "mailroute.log" in {p.name for p in (tmp_path / "contact").iterdir()}


def test_sent_car_mail_gets_label_and_later_reply_follows(cfg, gm):
    ours = gm.add(frm=ME, to="info@autohaus.test", labels=["SENT"], minutes_ago=200)
    reply = gm.add(frm="other.person@elsewhere.test", to=ME, thread=ours["threadId"])
    run_once(cfg, gmail=gm, db=None, ledger=None)
    assert gm.cars in labels(gm, ours) and "SENT" in labels(gm, ours)
    assert moved(gm, reply)


def test_does_not_move_unknown_freemail_even_if_domain_listed(cfg, gm):
    cfg["contact"]["mailroute"]["domains"].append(FREE)  # a mistaken freemail domain rule
    stranger = gm.add(frm=f"stranger@{FREE}", to=ME)
    stranger2 = gm.add(frm="someone@freemail.test", to=ME)  # same host as a known seller
    known_seller = gm.add(frm="pseller@freemail.test", to=ME)
    s = run_once(cfg, gmail=gm, db=DB, ledger=None)
    assert stayed(gm, stranger) and stayed(gm, stranger2)
    assert moved(gm, known_seller)
    assert FREE not in Rules(cfg).domains and s["moved"] == 1


def test_never_touch_wins_over_dealer_domain(cfg, gm):
    friend = gm.add(frm="Friend <friend@autohaus.test>", to=ME, subject="dinner?")
    fam_cc = gm.add(frm="sales@autohaus.test", to=ME, cc="me@family.test", subject="Offer")
    dealer = gm.add(frm="sales@autohaus.test", to=ME, subject="Offer")
    s = run_once(cfg, gmail=gm, db=None, ledger=None)
    assert stayed(gm, friend) and stayed(gm, fam_cc)
    assert moved(gm, dealer) and s["vetoed"] == 2


def test_car_words_alone_never_move(cfg, gm):
    m = gm.add(frm="newsletter@unrelated.test", to=ME, subject="VW ID.4 for sale, accident-free, mobile.de",
               body="autoscout24 car dealer price VIN")
    assert run_once(cfg, gmail=gm, db=None, ledger=None)["moved"] == 0
    assert stayed(gm, m)


def test_never_deletes_and_only_removes_inbox(cfg, gm):
    gm.add(frm="sales@autohaus.test", to=ME)
    run_once(cfg, gmail=gm, db=None, ledger=None)
    mods = [c for c in gm.writes() if "odify" in c[1]]
    assert mods and all(c[3]["removeLabelIds"] in ([], ["INBOX"]) for c in mods)
    assert not any("trash" in c[1] or c[0] == "DELETE" for c in gm.calls)


def test_dry_run_makes_no_writes(cfg, gm):
    m = gm.add(frm="sales@autohaus.test", to=ME)
    s = run_once(cfg, gmail=gm, db=DB, ledger=None, dry_run=True)
    assert s["dry_run"] and s["moved"] == 1
    assert gm.writes() == [] and stayed(gm, m)


def test_failed_ledger_rows_are_not_known(cfg, gm, tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.append(Entry(channel="email", to="never.sent@nowhere.test", text="x", status=FAILED, t=time.time()))
    led.append(Entry(channel="email", to="was.sent@somewhere.test", text="x", status=SENT, t=time.time()))
    a = gm.add(frm="never.sent@nowhere.test", to=ME)
    b = gm.add(frm="was.sent@somewhere.test", to=ME)
    run_once(cfg, gmail=gm, db=None, ledger=led)
    assert stayed(gm, a) and moved(gm, b)


def test_cardb_down_reuses_last_good_set(cfg, gm):
    run_once(cfg, gmail=gm, db=DB, ledger=None)
    m = gm.add(frm="pseller@freemail.test", to=ME)
    s = run_once(cfg, gmail=gm, db=DownDb(), ledger=None)
    assert s["db_error"] and moved(gm, m)


def test_window_respected_and_validated(cfg, gm):
    old = gm.add(frm="sales@autohaus.test", to=ME, minutes_ago=10 * 24 * 60)
    run_once(cfg, gmail=gm, window="3d")
    assert stayed(gm, old)
    run_once(cfg, gmail=gm, window=mailroute.DEEP_WINDOW)
    assert moved(gm, old)
    with pytest.raises(ValueError):
        run_once(cfg, gmail=gm, window="2h")  # Gmail has no hours/minutes unit


def test_concurrent_pass_is_skipped(cfg, gm):
    held = mailroute._lock()
    try:
        assert "skipped" in run_once(cfg, gmail=gm)
    finally:
        held.close()


def test_freemail_detection():
    assert is_freemail(FREE) and is_freemail("mail.web.de") and is_freemail("outlook.pt")
    assert not is_freemail("autohaus.test") and not is_freemail("dealer.co.uk")


# -- filters + launchd --------------------------------------------------------------------------

def test_filters_xml(cfg):
    known = ["pseller@freemail.test", "info@dealer-one.test", "friend@autohaus.test", ME]
    x = filters_xml(cfg, known)
    xml.dom.minidom.parseString(x)  # well-formed
    assert f'name="to" value="{PLUS}"' in x
    for t in ("marketplace.test", "autohaus.test", "dealer-one.test", "pseller@freemail.test"):
        assert t in x
    assert "friend@" not in x and "family.test" not in x and "freemail.test OR" not in x
    assert f'value="{ME}"' not in x and "shouldMarkAsRead" not in x
    assert x.count('name="label" value="cars"') == x.count("<entry>") == 2


def test_filters_xml_splits_long_lists(cfg):
    cfg["contact"]["mailroute"]["domains"] = [f"dealer{i:03d}.test" for i in range(200)]
    x = filters_xml(cfg, [], max_chars=500)
    froms = [ln for ln in x.split("<entry>") if "hasTheWord" in ln]
    assert len(froms) > 3 and all(f"dealer{i:03d}.test" in x for i in range(200))


def test_launchd_plist_renders(cfg, home):
    p = launchd_plist(cfg, carhunt_bin="/opt/carhunt/bin/carhunt")
    assert "{" not in p and "}" not in p
    xml.dom.minidom.parseString(p)
    assert "<string>com.carhunt.mailroute</string>" in p and "<integer>180</integer>" in p
    assert "<string>mailroute</string>" in p and str(home) in p
    d = launchd_plist(cfg, deep=True, carhunt_bin="/opt/carhunt/bin/carhunt")
    assert "com.carhunt.mailroute-deep" in d and "<string>--deep</string>" in d and "<key>Hour</key><integer>4</integer>" in d
    assert "{" not in d
