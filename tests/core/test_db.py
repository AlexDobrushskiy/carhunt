from urllib.parse import unquote

import pytest

from carhunt.core import db


@pytest.fixture
def cardb(fake_http):
    state = {"listings": {}}

    def handle(method, path, headers, body):
        if path == "/healthz":
            return 200, {"ok": True}
        if headers.get("Authorization") != "Bearer tok-1":
            return 401, {"error": "unauthorized"}
        if method == "POST" and path == "/api/v1/listings/upsert":
            state["listings"][body["url"]] = body
            return 200, {"car_id": 1, "listing_id": 7, "listing_created": True}
        if method == "GET" and path.startswith("/api/v1/listings?"):
            q = unquote(path)
            hit = [dict(v, id=7) for k, v in state["listings"].items() if k in q]
            return 200, hit
        if method == "PATCH" and path == "/api/v1/listings/7":
            if headers.get("If-Match") != "3":
                return 412, {"error": "version mismatch"}
            return 200, {"id": 7, **body}
        if method == "GET" and path == "/api/v1/cars/404":
            return 404, {"error": "car not found"}
        if method == "PUT" and path == "/api/v1/cars/1/facts/soh":
            return 200, {"key": "soh", **body}
        if method == "DELETE" and path == "/api/v1/cars/1/verdict":
            return 204, None
        if method == "POST" and path == "/api/v1/cars/1/events":
            return 201, {"id": 5, **body}
        if method == "GET" and path.startswith("/api/v1/queue"):
            return 200, {"total": 0, "items": [], "q": path}
        return 500, {"error": f"unexpected {method} {path}"}

    return fake_http(handle)


def test_client_round_trip(cardb, write_config, monkeypatch):
    write_config({"owner": {"tz": "UTC"}, "cardb": {"url": cardb.url, "token": "secret:cardb_token"}})
    monkeypatch.setenv("CARHUNT_SECRET_CARDB_TOKEN", "tok-1")
    monkeypatch.setenv("CARDB_AUTHOR", "sweep")
    c = db.Client.from_config()
    assert c.health() == {"ok": True}
    url = "https://example.invalid/ad/1"
    assert c.upsert_listing({"url": url, "price": 30000})["listing_id"] == 7
    assert cardb.requests[-1]["headers"]["X-Author"] == "sweep"
    assert c.find_listing(url)["id"] == 7
    with pytest.raises(db.NotFound):
        c.find_listing("https://example.invalid/none")
    assert c.listing_patch(7, {"status": "removed"}, version=3)["status"] == "removed"
    with pytest.raises(db.Conflict):
        c.listing_patch(7, {"status": "removed"}, version=2)
    with pytest.raises(db.NotFound, match="car not found"):
        c.car(404)
    assert c.fact(1, "soh", "94%", source="seller_said")["source"] == "seller_said"
    assert c.verdict(1, "clear") is None
    ev = c.event(1, "ask", "Battery certificate?", data={"topic": "battery"}, key="ask-1")
    assert ev["dedupe_key"] == "ask-1" and "at" not in ev
    assert "tier=1%2C2" in c.queue(tier=[1, 2])["q"]


def test_errors_are_typed(cardb):
    c = db.Client(cardb.url, "wrong")
    with pytest.raises(db.ApiError) as e:
        c.car(1)
    assert e.value.status == 401 and "unauthorized" in str(e.value)
    cardb.close()
    with pytest.raises(db.Unreachable):
        c.health()
