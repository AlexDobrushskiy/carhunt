"""runner with scripted sites: blocked mid-run → site skipped, budget respected, gone ≠ blocked, re-run = 0 writes."""
from carhunt.discover import runner
from carhunt.discover.tests.conftest import ScriptedSite, ad_dict


def sweep(cfg, db, sites, **kw):
    by_id = {s.id: s for s in sites}
    sw = runner.Sweep(cfg, db, site_factory=lambda sid: by_id[sid], **kw)
    plans = [runner.Plan(s.id, s.meta, True) for s in sites]
    return sw.run(plans), sw


def states(report):
    return {s["site"]: (s["state"], s["new"]) for s in report["sites"]}


def test_blocked_mid_run_skips_site_and_continues(cfg, db):
    a = ScriptedSite("a", [ad_dict("a01"), ad_dict("a02"), ad_dict("a03")], block_on_ad="a02")
    b = ScriptedSite("b", [ad_dict("b01"), ad_dict("b02")])
    report, sw = sweep(cfg, db, [a, b])
    assert states(report) == {"a": ("blocked", 1), "b": ("ok", 2)}
    assert "test-wall" in report["sites"][0]["detail"]
    assert a.closed and b.closed
    assert sw.store.get("a", "PT|Volkswagen|ID.4|any") == {}          # blocked query: cursor not advanced
    assert sw.store.get("b", "PT|Volkswagen|ID.4|any")["first_id"] == "b01"


def test_budget_respected(cfg, db):
    cfg["discover"]["max_loads_per_site"] = 4
    s = ScriptedSite("a", [ad_dict(f"a{i:02d}") for i in range(10)])
    report, _ = sweep(cfg, db, [s])
    site = report["sites"][0]
    assert site["state"] == "budget" and site["loads"] <= 4 and site["new"] == 3


def test_gone_is_not_a_block(cfg, db):
    s = ScriptedSite("a", [ad_dict("a01"), ad_dict("a02"), ad_dict("a03")], gone={"a02"})
    report, _ = sweep(cfg, db, [s])
    site = report["sites"][0]
    assert (site["state"], site["new"], site["gone"]) == ("ok", 2, 1)


def test_rerun_writes_nothing(cfg, db):
    ads = [ad_dict(f"a{i:02d}") for i in range(4)]
    sweep(cfg, db, [ScriptedSite("a", ads)])
    first = len(db.writes())
    report, _ = sweep(cfg, db, [ScriptedSite("a", ads)])
    assert len(db.writes()) == first
    assert report["sites"][0]["new"] == 0


def test_rerun_with_a_new_ad_on_top(cfg, db):
    ads = [ad_dict(f"a{i:02d}") for i in range(3)]
    sweep(cfg, db, [ScriptedSite("a", ads)])
    s2 = ScriptedSite("a", [ad_dict("a99", created="2026-11-08T09:00:00+00:00")] + ads)
    report, _ = sweep(cfg, db, [s2])
    assert report["sites"][0]["new"] == 1 and s2.ad_calls == 1          # stops at the old head


def test_scope_prefilter_saves_detail_loads(cfg, db):
    s = ScriptedSite("a", [ad_dict("a01", price=90000), ad_dict("a02", km=200000), ad_dict("a03")])
    report, _ = sweep(cfg, db, [s])
    site = report["sites"][0]
    assert site["new"] == 1 and s.ad_calls == 1 and site["dropped"] == {"price": 1, "km": 1}


def test_detail_scope_drop_after_read(cfg, db):
    s = ScriptedSite("a", [ad_dict("a01", description="Leasingübernahme möglich"), ad_dict("a02")])
    report, _ = sweep(cfg, db, [s])
    assert report["sites"][0]["dropped"] == {"flag": 1}
    assert len(db.listings) == 1


def test_card_only_tiers(cfg, db):
    cfg["discover"]["detail_tiers"] = [1]
    q4 = ad_dict("a01", make="Audi", model="Q4 e-tron", title="Audi Q4 40 e-tron")
    s = ScriptedSite("a", [q4])
    report, _ = sweep(cfg, db, [s])
    assert report["sites"][0]["new"] == 1 and s.ad_calls == 0           # card only, no detail read
    body = db.calls[[k for k, _ in db.calls].index("upsert")][1]
    assert body["facts"]["ad_quality"]["value"] == "card-only" and not db.photos


def test_max_new(cfg, db):
    s = ScriptedSite("a", [ad_dict(f"a{i:02d}") for i in range(6)])
    report, _ = sweep(cfg, db, [s], max_new=2)
    assert report["sites"][0]["state"] == "max" and len(db.listings) == 2


def test_dry_run_writes_nothing_and_keeps_cursors(cfg, db):
    s = ScriptedSite("a", [ad_dict("a01")])
    report, sw = sweep(cfg, db, [s], dry_run=True)
    assert db.writes() == [] and report["writes"][0]["action"] == "would_create"
    assert sw.store.get("a", "PT|Volkswagen|ID.4|any") == {}


def test_plan_sends_before_reads(cfg, monkeypatch):
    from datetime import datetime
    from carhunt.sites import base
    metas = {"chat": {"site": "chat", "pace": {"read_after": "12:00"}}, "plain": {"site": "plain"}}
    monkeypatch.setattr(base, "metas", lambda: metas)
    cfg["sites"]["enabled"] = ["chat", "plain", "nope"]
    morning = datetime(2026, 11, 8, 9, 0)
    p = {x.site: (x.run, x.why) for x in runner.plan(cfg, now=morning)}
    assert p["plain"] == (True, "") and not p["chat"][0] and "12:00" in p["chat"][1]
    assert p["nope"] == (False, "no plugin registered")
    p = {x.site: x.run for x in runner.plan(cfg, now=datetime(2026, 11, 8, 14, 0))}
    assert p == {"chat": True, "plain": True, "nope": False}
    p = {x.site: x.run for x in runner.plan(cfg, window="morning", now=datetime(2026, 11, 8, 14, 0))}
    assert p["chat"] is False


def test_queries_per_model_and_country(cfg):
    cfg["search"]["private_sellers_abroad"] = False
    qs = runner.queries({"site": "s", "countries": ["PT", "ES", "PL"]}, cfg, "first_seen")
    keys = {runner.query_key(q) for q, _ in qs}
    assert "PT|Volkswagen|ID.4|any" in keys and "ES|Skoda|Enyaq|dealer" in keys
    assert not any(k.startswith("PL|") for k in keys) and len(keys) == 6
    assert all(q.fuel == "bev" and q.sort == "newest" for q, _ in qs)


def test_price_change_rereads_and_updates_once(cfg, db):
    cfg["discover"]["cursor"] = {"a": "full"}       # newest-first cursors stop before old ads; full coverage sees them
    ads = [ad_dict("a01", country="ES", price=31000,
                   description="PVP CONTADO: 32.400 €. PVP FINANCIADO: 31.000 €.")]
    sweep(cfg, db, [ScriptedSite("a", ads)])
    assert db.listings["https://a.example.invalid/ad/a01"]["price"] == 32400     # cash ask, not the headline
    n = len(db.writes())
    sweep(cfg, db, [ScriptedSite("a", ads)])
    assert len(db.writes()) == n                                                  # headline ≠ stored, still free
    ads[0].update(price=30000, description="PVP CONTADO: 31.400 €. PVP FINANCIADO: 30.000 €.")
    s = ScriptedSite("a", ads)
    report, _ = sweep(cfg, db, [s])
    assert report["sites"][0]["updated"] == 1 and s.ad_calls == 1
    assert db.listings["https://a.example.invalid/ad/a01"]["price"] == 31400
