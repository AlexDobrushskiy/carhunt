"""Shared harness: temp CARHUNT_HOME, fake wacli, cardb stub over HTTP, frozen clock.
`Tree.run(...)` runs the real CLI (`python -m carhunt.contact say …`) in a subprocess."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

from .fakes.cardb_stub import CardbStub

REPO = Path(__file__).resolve().parents[3]
FAKE_WACLI = Path(__file__).parent / "fakes" / "fake_wacli.py"

HOME_ME, AB_ME = "HOME-SESSION", "ABROAD-SESSION"
HOME_ROLE, AB_ROLE = "outreach-home", "outreach-abroad"
PT_NUM, ES_NUM = "351555111111", "34555222222"
NOW = datetime(2026, 11, 10, 11, 0, tzinfo=UTC)  # Tue 11:00 Lisbon, 12:00 Madrid
VAG = ["VW ID.4", "VW ID.5", "Audi Q4", "Skoda Enyaq"]

TEST_CONFIG: dict[str, Any] = {
    "owner": {"name": "owner", "tz": "Europe/Lisbon"},
    "contact": {
        "nudge": {
            "exclude": [
                {"field": "model_family", "in": ["BMW iX1", "Mercedes EQB", "Toyota bZ4X"],
                 "why": "goes quiet even with a thumbs-up"},
                {"all": [{"field": "model_family", "in": VAG}, {"field": "power_hp", "between": [195, 210]}],
                 "why": "VAG 204 hp goes quiet"},
            ],
        },
    },
}


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def msg(dt: datetime, me: bool, text: str, **kw: Any) -> dict[str, Any]:
    d = {"ChatJID": "x@s.whatsapp.net", "Timestamp": iso(dt), "FromMe": me, "Text": text, "ReactionEmoji": "",  # privacy-check: allow (synthetic JID)
         "MediaType": "", "Revoked": False, "ID": f"M{int(dt.timestamp())}{int(me)}"}
    d.update(kw)
    return d


def car(num: str, **kw: Any) -> dict[str, Any]:
    d = {"status": "talking", "model_family": "VW ID.4", "power_kw": 210, "verdict": None, "good_deal": False,
         "tier": 1, "seller": {"type": "private", "contacts": [{"kind": "whatsapp", "value": num}]},
         "listings": [{"url": "https://example.invalid/ad/1", "site": "fake.site", "status": "live"}]}
    d.update(kw)
    return d


def sent(dt: datetime, to: str, text: str, kind: str = "reply", channel: str = "whatsapp", **kw: Any) -> dict:
    d = {"channel": channel, "to": to, "text": text, "status": "sent", "t": dt.timestamp(), "car": "A9",
         "kind": kind, "by": HOME_ROLE, "err": "", "external_id": "", "id": f"snd:{dt.timestamp()}:{to[-4:]}"}
    d.update(kw)
    return d


class Tree:
    def __init__(self, tmp: Path, stub: CardbStub, url: str):
        self.tmp, self.stub, self.url = tmp, stub, url
        self.home = tmp / "carhunt"
        (tmp / "wacli" / "chats").mkdir(parents=True)
        self.config = json.loads(json.dumps(TEST_CONFIG))
        self.ledger: list[dict] = []
        self.chats: dict[str, list[dict]] = {}
        self.active = {HOME_ROLE: HOME_ME, AB_ROLE: AB_ME}
        stub.cars.clear()
        stub.cars.update({"A9": car(PT_NUM), "77": car(ES_NUM, seller={"type": "dealer", "contacts": [
            {"kind": "whatsapp", "value": ES_NUM}]})})

    @property
    def ledger_path(self) -> Path:
        return self.home / "contact" / "ledger.jsonl"

    def write(self) -> None:
        (self.home / "contact").mkdir(parents=True, exist_ok=True)
        (self.home / "config.yaml").write_text(yaml.safe_dump(self.config))
        self.ledger_path.write_text("".join(json.dumps(r) + "\n" for r in self.ledger))
        for role, sid in self.active.items():
            (self.home / "agents" / role).mkdir(parents=True, exist_ok=True)
            (self.home / "agents" / role / "state.json").write_text(json.dumps({"active_agent": sid}))
        for k, v in self.chats.items():
            (self.tmp / "wacli" / "chats" / f"{k}.json").write_text(json.dumps(v))

    def env(self, me: str = HOME_ME, role: str = HOME_ROLE, now: datetime = NOW, **extra: str) -> dict[str, str]:
        e = dict(os.environ, CARHUNT_HOME=str(self.home), CARHUNT_FAKE_NOW=now.isoformat(),
                 CARHUNT_WACLI=str(FAKE_WACLI), FAKE_WACLI_ROOT=str(self.tmp / "wacli"), CARDB_URL=self.url,
                 CARHUNT_SECRET_CARDB_TOKEN="test-token", AGTERM_SESSION_ID=me, CARHUNT_AGENT=role,
                 PYTHONPATH=str(REPO))
        e.pop("CARHUNT_CONFIG", None)
        e.update(extra)
        return e

    def run(self, *args: str, me: str = HOME_ME, role: str = HOME_ROLE, now: datetime = NOW, dry: bool = True,
            **extra: str) -> tuple[int, str]:
        self.write()
        r = subprocess.run([sys.executable, "-m", "carhunt.contact", "say", *args] + (["--dry-run"] if dry else []),
                           env=self.env(me, role, now, **extra), capture_output=True, text=True, cwd=REPO)
        return r.returncode, r.stdout + r.stderr

    def popen(self, *args: str, **extra: str) -> subprocess.Popen:
        return subprocess.Popen([sys.executable, "-m", "carhunt.contact", "say", *args],
                                env=self.env(**extra), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, cwd=REPO)

    def ledger_rows(self) -> list[dict]:
        return [json.loads(x) for x in self.ledger_path.read_text().splitlines() if x.strip()]

    def wacli_sends(self) -> list[dict]:
        p = self.tmp / "wacli" / "sends.txt"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def stub():
    s = CardbStub()
    url = s.start()
    s.url = url  # type: ignore[attr-defined]
    yield s
    s.stop()


@pytest.fixture
def tree(tmp_path: Path, stub: CardbStub) -> Tree:
    return Tree(tmp_path, stub, stub.url)  # type: ignore[attr-defined]


def nudge_tree(t: Tree, num: str = PT_NUM, car_id: str = "A9") -> Tree:
    """Happy path: opener 4 days ago, seller replied, our question 50 h ago unanswered."""
    o, q = NOW - timedelta(days=4), NOW - timedelta(hours=50)
    t.ledger = [sent(o, num, "Olá, ainda está disponível?", kind="opener", car=car_id),
                sent(q, num, "Teve algum acidente?", car=car_id)]
    t.chats[num] = [msg(o, True, "Olá, ainda está disponível?"), msg(o + timedelta(minutes=20), False, "Sim, está."),
                    msg(q, True, "Teve algum acidente?")]
    return t
