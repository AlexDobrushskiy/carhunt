"""ingest against a stub cardb: upsert without photos → resolve by URL → photos; re-runs write nothing."""
from carhunt.discover import normalize as n, quality
from carhunt.discover.ingest import Ingest
from carhunt.discover.tests.conftest import StubDB
from carhunt.sites.model import RawAd, Seller


def listing(ref="s01", photos=3, phones=("+351 555 000 001",), price=30000):
    ad = RawAd(url=f"https://x.example.invalid/ad/{ref}", site="x", site_ref=ref, make="Volkswagen", model="ID.4",
               title="ID.4 Pro", price=price, km=1000, first_registration="2024-01", country="PT", vin="SYN000000000001",
               photos=[f"https://img.example.invalid/{ref}-{i}.jpg" for i in range(photos)], phones=list(phones),
               seller=Seller(type="dealer", city="Testville"), extra={"stock_ref": "SYN-STOCK-1"})
    return n.from_ad(ad)


def test_upsert_then_resolve_by_url_then_photos(db, cfg):
    x = listing()
    quality.assess(x, cfg)
    r = Ingest(db).write(x)
    assert r.action == "created" and r.photos_added == 3
    kinds = [k for k, _ in db.calls]
    first_photo = kinds.index("photo")
    assert kinds[0] == "upsert" and "find" in kinds[1:first_photo]      # resolved by URL before any photo
    body = db.calls[0][1]
    assert "photo_urls" not in body
    assert body["vin"] == "SYN000000000001" and body["facts"]["dealer_stock_ref"]["value"] == "SYN-STOCK-1"
    assert body["seller"]["contacts"] == [{"kind": "phone", "value": "351555000001"}]
    assert {p[2] for p in db.photos} == {db.listings[x.url]["id"]}
    assert body["facts"]["ad_quality"]["value"] == "thin"           # 3 photos < 8


def test_known_unchanged_is_free_and_price_change_is_minimal(db):
    ing = Ingest(db)
    ing.write(listing())
    n_writes = len(db.writes())
    existing = ing.known(listing().url)
    assert ing.sighting(listing(), existing).action == "unchanged"
    assert len(db.writes()) == n_writes
    r = ing.sighting(listing(price=28900), existing, price_changed=True)
    assert r.action == "updated"
    assert db.calls[-1] == ("upsert", {"url": listing().url, "price": 28900, "price_vat": "gross"})


def test_removed_listing_seen_again_is_a_sighting(db):
    ing = Ingest(db)
    ing.write(listing())
    db.listings[listing().url]["status"] = "removed"
    assert ing.sighting(listing(), ing.known(listing().url)).action == "updated"


def test_price_x100_stores_the_car_without_price():
    db = StubDB(reject={listing().url: "price_x100"})
    r = Ingest(db).write(listing())
    assert r.action == "created" and "price held (price_x100)" in r.reason
    first, retry = [b for k, b in db.calls if k == "upsert"]
    assert first["price"] and "price" not in retry and "price_vat" not in retry and "price_x100" in retry["price_note"]


def test_price_lease_is_dropped():
    db = StubDB(reject={listing().url: "price_lease"})
    r = Ingest(db).write(listing())
    assert r.action == "rejected" and "price_lease" in r.reason and not db.photos and not db.listings


def test_bad_field_rejects_one_ad_not_the_run():
    db = StubDB(reject={listing().url: "bad_field"})
    assert Ingest(db).write(listing()).action == "rejected"


def test_phone_owned_elsewhere_falls_back_to_site_chat():
    db = StubDB(steal_phones={"351555000001"})
    r = Ingest(db).write(listing())
    assert r.reason == "phone not attached"
    assert db.facts and db.facts[0][1] == "phone_route"


def test_dry_run_writes_nothing(db):
    r = Ingest(db, dry_run=True).write(listing())
    assert r.action == "would_create" and r.payload["url"] == listing().url and db.writes() == []
