"""cursor strategies: stop points, sponsored rows, width-aware numeric ids, merge-on-commit."""
from carhunt.discover.cursor import Cursor, Store, strategy_for
from carhunt.sites.model import Card


def c(ref, created=None, sponsored=False, price=30000):
    return Card(url=f"https://x.example.invalid/ad/{ref}", site="x", site_ref=ref, created=created,
                sponsored=sponsored, price=price)


def test_first_seen_stops_on_old_head_even_if_known():
    cur = Cursor("first_seen", {"first_id": "b", "created": "2026-11-01T00:00:00+00:00"})
    assert not cur.stop(c("a", "2026-11-07T00:00:00+00:00"))
    assert cur.stop(c("b", "2026-11-07T00:00:00+00:00"))


def test_first_seen_created_boundary_and_sponsored():
    cur = Cursor("first_seen", {"first_id": "zz", "created": "2026-11-05T00:00:00+00:00"})
    assert not cur.stop(c("old-promo", "2026-10-01T00:00:00+00:00", sponsored=True))
    assert cur.stop(c("old", "2026-11-04T23:00:00+00:00"))


def test_first_seen_head_is_first_eligible_organic():
    cur = Cursor("first_seen", {}, eligible=lambda card: card.price <= 40000)
    for card in (c("promo", sponsored=True), c("pricey", price=90000), c("h", "2026-11-08T09:00:00+00:00"), c("n")):
        cur.observe(card)
    assert cur.committed("2026-11-08T10:00:00")["first_id"] == "h"


def test_newest_id_width_aware():
    cur = Cursor("newest_id", {"max_id_by_width": {"10": 5000000000}})
    assert cur.stop(c("4999999999"))
    assert not cur.stop(c("5000000001"))
    assert not cur.stop(c("53860000000001"))         # a 14-digit mirror id has its own cut
    cur.observe(c("5000000001"))
    cur.observe(c("53860000000001"))
    assert cur.committed("t")["max_id_by_width"] == {"10": 5000000001, "14": 53860000000001}


def test_full_never_stops():
    cur = Cursor("full", {"last_run": "x"})
    assert not cur.stop(c("1")) and cur.new(c("1"))


def test_commit_keeps_old_value_when_nothing_eligible():
    old = {"first_id": "keep", "created": "2026-11-01T00:00:00+00:00"}
    cur = Cursor("first_seen", old)
    cur.observe(c("promo", sponsored=True))
    assert cur.committed("2026-11-08")["first_id"] == "keep"


def test_store_roundtrip(tmp_path):
    s = Store(tmp_path / "d" / "cursors.json")
    s.put("x", "PT|VW|ID.4|any", {"first_id": "a"})
    assert Store(tmp_path / "d" / "cursors.json").get("x", "PT|VW|ID.4|any") == {"first_id": "a"}


def test_strategy_resolution():
    assert strategy_for({"site": "s", "cursor": {"strategy": "full"}}, {}) == "full"
    assert strategy_for({"site": "s"}, {"cursor": {"s": "newest_id"}}) == "newest_id"
    assert strategy_for({"site": "s"}, {}) == "first_seen"
    # sites vocabulary (site.schema.json): newest_first + key
    assert strategy_for({"site": "s", "cursor": {"strategy": "newest_first", "key": "site_ref"}}, {}) == "newest_id"
    assert strategy_for({"site": "s", "cursor": {"strategy": "newest_first", "key": "created"}}, {}) == "first_seen"
    # config override wins over site.yaml
    assert strategy_for({"site": "s", "cursor": {"strategy": "full"}}, {"cursor": {"s": "newest_id"}}) == "newest_id"


def test_every_site_yaml_cursor_resolves():
    from carhunt.sites import base

    for sid, meta in base.metas().items():
        assert strategy_for(meta, {}) in ("newest_id", "first_seen", "full"), sid
