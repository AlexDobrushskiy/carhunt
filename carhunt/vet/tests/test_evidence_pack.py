"""Evidence pack against a stub cardb: missing items -> asks; all present -> visit-ready."""
from carhunt.vet import evidence_pack as ep
from carhunt.vet import vin

GOOD_VIN = "WVWZZZ1KZLW000001"  # privacy-check: allow (synthetic VIN)
REQUIRED_FACTS = ["registration_doc", "service_history", "soh", "recall_status", "odometer_photo",
                  "warranty", "accidents", "vin_check"]


class StubDB:
    def __init__(self, car):
        self.cars = {"7": car}
        self.events = []

    def car(self, ref):
        return self.cars[ref]

    def event(self, ref, *, type, summary, data=None, key=None):
        ev = {"type": type, "summary": summary, "data": data, "dedupe_key": key}
        self.events.append(ev)
        self.cars[ref].setdefault("events", []).insert(0, ev)
        return ev


def car(**kw):
    base = {"id": 7, "vin": GOOD_VIN, "reg_date": "2020-05", "powertrain": {"fuel": "BEV"},
            "facts": [], "events": []}
    base.update(kw)
    return base


def facts(keys, value="ok (doc photo)"):
    return [{"key": k, "value": value, "source": "seller_said"} for k in keys]


def test_empty_car_not_ready_first_ask_is_registration_doc():
    db = StubDB(car())
    st = ep.run(db, "7", write_asks=True)
    assert not st.visit_ready
    assert "registration_doc" in st.missing and "vin" not in st.missing
    assert st.todo_self == ["vin_check"]
    assert len(db.events) == 1
    ev = db.events[0]
    assert ev["type"] == "ask" and ev["data"]["topic"] == "registration_doc"
    assert ev["dedupe_key"] == "ask:7:registration_doc:1"


def test_open_ask_blocks_next_until_answered():
    db = StubDB(car())
    ep.run(db, "7", write_asks=True)
    st = ep.run(db, "7", write_asks=True)        # ask still open -> nothing new
    assert len(db.events) == 1
    assert {s.key: s.state for s in st.items}["registration_doc"] == "asked"
    db.cars["7"]["events"].insert(0, {"type": "ask_answered", "data": {"topic": "registration_doc"}})
    db.cars["7"]["facts"] = facts(["registration_doc"])
    ep.run(db, "7", write_asks=True)
    assert db.events[-1]["data"]["topic"] == "service_history"   # fixed order, skips own checks


def test_all_present_is_visit_ready_and_writes_nothing():
    db = StubDB(car(facts=facts(REQUIRED_FACTS)))
    st = ep.run(db, "7", write_asks=True)
    assert st.visit_ready, st.missing
    assert st.missing == [] and db.events == []
    states = {s.key: s.state for s in st.items}
    assert states["charging_inlet"] == "n/a" and states["tyres"] == "missing"   # optional


def test_dry_run_plans_but_does_not_write():
    db = StubDB(car())
    st = ep.run(db, "7", write_asks=False, max_asks=3)
    assert len(st.asks) == 3 and db.events == []
    assert [a["data"]["topic"] for a in st.asks] == ["registration_doc", "service_history", "battery_health"]


def test_refusal_is_red_flag_and_not_reasked():
    f = facts(REQUIRED_FACTS)
    f = [x if x["key"] != "soh" else dict(x, value="refused: no test allowed") for x in f]
    db = StubDB(car(facts=f))
    st = ep.run(db, "7", write_asks=True)
    assert not st.visit_ready
    assert any("refused" in r for r in st.red_flags)
    assert db.events == []


def test_ice_car_skips_battery_and_inlet():
    f = [x for x in facts(REQUIRED_FACTS) if x["key"] != "soh"]
    st = ep.assess(car(powertrain={"fuel": "ICE"}, facts=f))
    assert st.visit_ready
    assert {s.key: s.state for s in st.items}["battery_health"] == "n/a"


def test_china_vin_needs_inlet_photo_and_is_red():
    china = vin.with_check_digit("LFV" + "BA24G0" + "N" + "3" + "000001")
    st = ep.assess(car(vin=china, facts=facts(REQUIRED_FACTS)))
    assert "charging_inlet" in st.missing
    assert any("China-market" in r for r in st.red_flags)
    assert not st.visit_ready


def test_unknown_marker_values_count_as_missing_and_conflicts_block():
    f = facts(REQUIRED_FACTS) + [{"key": "pano_conflict", "value": "ad says yes, photo no"}]
    f = [x if x["key"] != "warranty" else dict(x, value="unknown") for x in f]
    st = ep.assess(car(facts=f))
    assert "warranty" in st.missing
    assert "conflict: pano_conflict" in st.red_flags


def test_vin_check_event_satisfies_self_check():
    f = [x for x in facts(REQUIRED_FACTS) if x["key"] != "vin_check"]
    st = ep.assess(car(facts=f, events=[{"type": "vin_check", "summary": "clean"}]))
    assert st.visit_ready


def test_render_mentions_state():
    st = ep.assess(car())
    out = ep.render(st)
    assert "visit-ready: no" in out and "Registration document" in out


def test_battery_soh_is_the_health_fact_and_asks_name_their_fact():
    f = [x for x in facts(REQUIRED_FACTS) if x["key"] != "soh"]
    st = ep.assess(car(facts=f + facts(["battery_soh"], "94 % (dealer cert, 2026-11)")))
    assert st.visit_ready
    st = ep.run(StubDB(car()), "7")
    assert st.asks[0]["data"]["fact"] == "registration_doc"


def test_unknown_fuel_stays_conservative_and_lowercase_cardb_fuel_works():
    f = [x for x in facts(REQUIRED_FACTS) if x["key"] != "soh"]
    assert "battery_health" in ep.assess(car(powertrain={"fuel": "unknown"}, facts=f)).missing
    assert "battery_health" in ep.assess(car(powertrain={"fuel": "bev"}, facts=f)).missing
    assert ep.assess(car(powertrain={"fuel": "petrol"}, facts=f)).visit_ready
    assert ep.fuel_of({"powertrain": {"battery_net_kwh": 77}}) == "BEV"
