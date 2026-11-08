"""asks: open/close semantics shared with vet (topic counts) — in-memory cardb."""
import pytest

from carhunt.contact import asks


class DB:
    def __init__(self, events, facts=None):
        self.evs, self.facts_, self.written = list(events), list(facts or []), []

    def events(self, car):
        return list(self.evs)

    def car(self, car):
        return {"id": car, "facts": self.facts_}

    def fact(self, car, key, value, source=None):
        self.written.append((key, value, source))

    def event(self, car, type, summary, data=None, key=None):
        e = {"id": 100 + len(self.evs), "type": type, "summary": summary, "data": data, "at": "2026-11-08T12:00:00Z"}
        self.evs.append(e)
        return e


def ask(i, topic, at):
    return {"id": i, "type": "ask", "data": {"topic": topic, "fact": topic}, "at": at}


def test_close_by_topic_writes_topic_ask_event_and_fact():
    db = DB([ask(1, "vin", "2026-11-08T10:00:00Z")])
    e = asks.close(db, "7", topic="vin", answer="SYN00000000000001")
    assert e["data"] == {"ask_event": 1, "topic": "vin", "fact_written": True}
    assert db.written == [("vin", "SYN00000000000001", "seller_said")]
    assert asks.open_asks(db, "7") == []
    with pytest.raises(LookupError):
        asks.close(db, "7", topic="vin", answer="again")


def test_existing_fact_is_kept_and_placeholder_is_filled():
    db = DB([ask(1, "warranty", "2026-11-08T10:00:00Z")], facts=[{"key": "warranty", "value": "2027-03 factory"}])
    assert asks.close(db, "7", ask_id="1", answer="yes")["data"]["fact_written"] is False and db.written == []
    db = DB([ask(1, "warranty", "2026-11-08T10:00:00Z")], facts=[{"key": "warranty", "value": "unknown"}])
    asks.close(db, "7", ask_id="1", answer="until 2027-03")
    assert db.written == [("warranty", "until 2027-03", "seller_said")]


def test_topic_only_close_counts_like_vet():
    evs = [ask(1, "tyres", "2026-11-08T09:00:00Z"), ask(2, "tyres", "2026-11-08T10:00:00Z"),
           {"id": 3, "type": "ask_answered", "data": {"topic": "tyres"}, "at": "2026-11-08T11:00:00Z"}]
    assert [a["id"] for a in asks.open_asks(DB(evs), "7")] == [2]
