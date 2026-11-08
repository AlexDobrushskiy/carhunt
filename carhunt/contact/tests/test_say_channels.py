"""`say.run` over non-WhatsApp channels: email (fake Gmail) and the guard's email-specific rules."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from carhunt.contact import deps, say
from carhunt.contact.channels.email import Email
from carhunt.contact.ledger import Ledger

from .fakes.fake_gmail import FakeGmail

SELLER = "sales@dealer.example.com"
ME = "owner@example.com"


@pytest.fixture
def env(tmp_path, monkeypatch, stub):
    monkeypatch.setenv("CARHUNT_HOME", str(tmp_path))
    monkeypatch.setenv("CARHUNT_FAKE_NOW", "2026-11-10T11:00:00+00:00")  # Tue, office hours in Madrid
    monkeypatch.delenv("CARHUNT_AGENT", raising=False)
    monkeypatch.delenv("CARDB_AUTHOR", raising=False)
    stub.cars["E1"] = {"status": "contacted", "country": "ES", "seller": {"type": "dealer", "contacts": [
        {"kind": "email", "value": SELLER}]}, "listings": []}
    cfg = {"owner": {"tz": "Europe/Lisbon"},
           "contact": {"email": {"from_name": "Test Owner", "from_address": ME, "plus_tag": "cars", "label": "cars",
                                 "verify_wait_s": 0}}}
    gm = FakeGmail()
    gm.cars = gm.add_label("cars")
    return cfg, gm, deps.Cardb(stub.url, "t"), stub


def test_email_opener_dry_run_then_send(env):
    cfg, gm, db, stub = env
    ch = Email(cfg, gmail=gm, subject="Your car on the site")
    o = say.run(channel="email", text="Hello, is the car still available? Any accidents?", car="E1", mode="opener",
                dry_run=True, cfg=cfg, db=db, ch=ch, ledger=Ledger())
    assert o.code == 0, o.decision
    assert o.payload["headers"]["Reply-To"] == "owner+cars@example.com"
    assert not [c for c in gm.calls if c[0] != "GET"]  # dry run: no Gmail writes
    o = say.run(channel="email", text="Hello, is the car still available? Any accidents?", car="E1", mode="opener",
                cfg=cfg, db=db, ch=ch, ledger=Ledger())
    assert o.code == 0 and o.entry.status == "sent", o.as_dict()
    assert stub.messages[-1]["channel"] == "email" and stub.messages[-1]["dedupe_key"] == o.entry.id


def test_email_outside_seller_hours(env, monkeypatch):
    cfg, gm, db, _ = env
    monkeypatch.setenv("CARHUNT_FAKE_NOW", datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc).isoformat())  # Sat 15:00 Madrid
    o = say.run(channel="email", text="Hello, still available?", car="E1", mode="opener", dry_run=True, cfg=cfg,
                db=db, ch=Email(cfg, gmail=gm, subject="S"), ledger=Ledger())
    assert o.code == 10 and o.decision.rule == "seller-hours", o.decision


def test_email_thread_suffix_matches_contact(env):
    cfg, gm, db, _ = env
    o = say.run(channel="email", text="Hello, still available?", car="E1", to=SELLER + "#T123", mode="opener",
                dry_run=True, cfg=cfg, db=db, ch=Email(cfg, gmail=gm, subject="S", offline=True), ledger=Ledger())
    assert o.code == 0, o.decision
