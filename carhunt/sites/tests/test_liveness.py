"""Liveness: classifier (cases from real ads, synthetic URLs) and the cardb-writing runner."""
import pytest

from carhunt.sites import base, liveness
from carhunt.sites.live import classify

AS = "https://www.autoscout24.es/anuncios/volkswagen-id-4-pro-cat-11111111-aaaa-4bbb-8ccc-000000000001"
COCHES = "https://www.coches.net/volkswagen-id4-pro-2025-en-madrid-55500001-covo.aspx"
CJ = "https://www.custojusto.pt/lisboa/veiculos/carros-usados/suv-tt/kia-ev6-55500002"


def aid(url):
    import re
    for rx in (r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", r"-(\d{6,})-covo", r"-(\d{6,})$"):
        m = re.search(rx, url)
        if m:
            return m.group(1)


class TestClassify:
    def test_gone(self):
        assert classify(AS, 410, None, {})[0] == "gone"
        assert classify(AS, 404, None, {"title": "Dieses Fahrzeug ist nicht verfügbar"})[0] == "gone"
        assert classify(CJ, 200, CJ.rsplit("/", 1)[0] + "?gone=55500002", {},
                        rules={"gone_redirect": r"[?&]gone="}, ad_id=aid)[0] == "gone"
        assert classify(COCHES, 302, "https://www.coches.net/volkswagen/id4/segunda-mano/", {},
                        rules={"gone_redirect": "/segunda-mano/"}, ad_id=aid)[0] == "gone"
        assert classify(AS, 200, None, {"sold": True, "has_id": True})[0] == "gone"
        assert classify(AS, 200, None, {"gone_text": True, "has_id": True})[0] == "gone"

    def test_soft(self):
        assert classify("https://www.example.invalid/ad-55500003.htm", 200, "https://www.example.invalid/list/",
                        {}, ad_id=aid)[0] == "gone_soft"

    def test_live_and_moved(self):
        assert classify(AS, 200, None, {"has_id": True})[0] == "live"
        assert classify(AS, 308, AS.replace("pro-cat", "pro-x-cat"), {}, ad_id=aid)[0] == "follow"

    def test_never_gone_on_block(self):
        for st in (401, 403, 429, 503):
            assert classify(AS, st, None, {})[0] == "blocked"
        assert classify(COCHES, 200, None, {"bot": True})[0] == "blocked"
        assert classify(COCHES, 200, None, {"has_id": False})[0] == "unknown"
        assert classify(COCHES, 0, None, {})[0] == "unknown"


class FakeDB:
    def __init__(self, listings, cars=None):
        self.ls = listings
        self.cs = cars or {}
        self.patches, self.events, self.sightings = [], [], []

    def listings(self, status):
        return [dict(x) for x in self.ls if x["status"] == status]

    def cars(self):
        return self.cs

    def patch_status(self, lid, status):
        self.patches.append((lid, status))
        for x in self.ls:
            if x["id"] == lid:
                x["status"] = status

    def event(self, car, lid, summary, key, data):
        self.events.append((car, lid, key, data["verdict"]))

    def sighting(self, url, price=None):
        self.sightings.append((url, price) if price is not None else url)


def fake_url(ref):
    return f"https://fake.example.invalid/ad/{ref}"


@pytest.fixture
def fake():
    with base.fake_sites():
        yield


PRICES = {"fk1001": 31900, "fk1002": 41000, "fk1003": 36900, "fk1004": 24900}


def listings():
    return [{"id": i, "car_id": 100 + i, "site": "fake", "url": fake_url(ref), "status": "live", "price": PRICES[ref]}
            for i, ref in enumerate(["fk1001", "fk1002", "fk1003", "fk1004"], start=1)]


def test_run_writes_through_cardb(fake):
    db = FakeDB(listings())
    s = liveness.run(db=db)
    by = {r["listing"]: (r["verdict"], r["action"]) for r in s["results"]}
    # 1: price dropped 31900 → 30900 on the live page; 2: cardb holds 41000 but the page shows a net price → skipped
    assert by == {1: ("live", "price"), 2: ("live", "seen"), 3: ("gone", "removed"), 4: ("gone_soft", "soft")}
    assert db.patches == [(3, "removed")]
    assert db.events == [(103, 3, db.events[0][2], "gone")] and db.events[0][2].startswith("liveness:3:gone:")
    assert db.sightings == [(fake_url("fk1001"), 30900), fake_url("fk1002")]


def test_soft_needs_two_signals_an_hour_apart(fake):
    db = FakeDB(listings())
    from carhunt.access import _core
    st = liveness.State(_core.path("sites", "liveness.db"))
    lst = db.listings("live")[3]
    assert liveness.apply(db, st, lst, "gone_soft", "redirect", dry=False, now=1000.0) == "soft"
    assert liveness.apply(db, st, lst, "gone_soft", "redirect", dry=False, now=1000.0 + 600) == "soft"
    assert db.patches == []
    assert liveness.apply(db, st, lst, "gone_soft", "redirect", dry=False, now=1000.0 + 3700) == "removed"
    assert db.patches == [(4, "removed")]


def test_relists_only_own_removals(fake):
    db = FakeDB([{"id": 1, "car_id": 101, "site": "fake", "url": fake_url("fk1001"), "status": "removed"},
                 {"id": 2, "car_id": 102, "site": "fake", "url": fake_url("fk1002"), "status": "live"}])
    from carhunt.access import _core
    st = liveness.State(_core.path("sites", "liveness.db"))
    # listing 1 was removed by someone else → not even re-checked
    liveness.run(db=db)
    assert (1, "live") not in db.patches
    # now listing 2 removed by us, then the ad is back
    st.put(2, removed_by_us=1)
    db.ls[1]["status"] = "removed"
    s = liveness.run(db=db)
    assert (2, "live") in db.patches and any(r["action"] == "relisted" for r in s["results"])


def test_block_stops_site_and_writes_nothing(fake, monkeypatch):
    monkeypatch.setenv("CARHUNT_FAKE_SITES_BLOCK", "live")
    db = FakeDB(listings())
    s = liveness.run(db=db)
    assert [r["verdict"] for r in s["results"]] == ["blocked"]
    assert "blocked" in s["sites"]["fake"]["stopped"]
    assert db.patches == [] and db.events == [] and db.sightings == []


def test_dry_run_writes_nothing(fake):
    db = FakeDB(listings())
    s = liveness.run(db=db, dry=True)
    assert {r["verdict"] for r in s["results"]} == {"live", "gone", "gone_soft"}
    assert db.patches == db.events == db.sightings == []


def test_car_exit_codes():
    assert liveness.car_exit([{"verdict": "live"}, {"verdict": "gone"}]) == 0
    assert liveness.car_exit([{"verdict": "gone"}, {"verdict": "gone_soft"}]) == 4
    assert liveness.car_exit([{"verdict": "blocked"}]) == 5
    assert liveness.car_exit([]) == 5


def test_daily_due_and_priority(fake):
    db = FakeDB(listings(), cars={101: {"id": 101, "verdict": "down"}, 102: {"id": 102, "verdict": "up"}})
    from carhunt.access import _core
    st = liveness.State(_core.path("sites", "liveness.db"))
    now = 1_700_000_000.0
    st.put(3, last_at=now - 3600)
    by, _ = liveness.plan(db, st, daily=True, now=now)
    assert [x["id"] for _, x in by["fake"]] == [2, 1, 4]   # 3 checked an hour ago; liked first, no car record last


def test_price_from_page_without_extra_requests():
    """Liveness reads the current price from the page it already fetched (coches page route, leboncoin)."""
    import importlib

    from carhunt.sites.testing import FakeNet
    for pkg in ("coches_net", "leboncoin_fr"):
        tm = importlib.import_module(f"carhunt.sites.tests.test_{pkg}")
        s = base.get(pkg, net=FakeNet(pkg))
        urls = [v for v in vars(tm).values() if isinstance(v, str) and v.startswith("https://") and s.ad_id(v)]
        pages = [p for p in (base.ROOT / "tests" / "fixtures" / pkg).glob("ad*.html")]
        found = [ad.price for u in urls for p in pages if (ad := s.ad_from_page(u, p.read_text()))]
        assert found and all(found), pkg
        assert s.net.calls == [], "no request: the page is parsed from memory"
