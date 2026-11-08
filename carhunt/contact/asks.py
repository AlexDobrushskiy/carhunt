"""Questions vet/buy want asked (cardb events type=ask) and their closing (type=ask_answered).

Outreach agents phrase an open ask as one question in the seller's language, send it with
`carhunt say`, and close it once the seller answers (or refuses: the answer text says so).

Contract with vet (`carhunt evidence`): an ask carries `data.topic`; vet counts a topic open while
it has more `ask` than `ask_answered` events. So every close writes `data.topic` (vet's view) and
`data.ask_event` (which ask). An ask_answered without `ask_event` (written by hand or by vet) closes
the oldest open ask of its topic, the same count rule vet uses.

Vet decides "have" from facts, not from closes: a closed ask with the fact still empty gets re-asked,
and a re-ask is what made sellers call us scammers (11-01). So close also writes the answer into the
ask's `data.fact` key (source seller_said) when the car has no value there yet.
"""
from __future__ import annotations

from typing import Any

from . import deps

# Statuses where vet/buy asks are live: before the opener (fold the ask in), while talking, and
# pre-visit / pre-purchase (buy writes asks too).
STATUSES = ("to_contact", "contacted", "talking", "ready_to_visit", "visited")


def _topic(e: dict[str, Any]) -> str | None:
    t = (e.get("data") or {}).get("topic")
    return str(t) if t else None


def open_asks(db: deps.Cardb, car: str) -> list[dict[str, Any]]:
    evs = sorted(db.events(car), key=lambda e: (str(e.get("at") or ""), int(e.get("id") or 0)))
    asks = [e for e in evs if e.get("type") == "ask"]
    done = [e for e in evs if e.get("type") == "ask_answered"]
    closed = {str((e.get("data") or {}).get("ask_event")) for e in done if (e.get("data") or {}).get("ask_event")}
    loose: dict[str, int] = {}  # topic → closes that name no ask
    for e in done:
        if not (e.get("data") or {}).get("ask_event") and _topic(e):
            loose[_topic(e)] = loose.get(_topic(e), 0) + 1  # type: ignore[index]
    out = []
    for a in asks:
        if str(a.get("id")) in closed:
            continue
        t = _topic(a)
        if t and loose.get(t):
            loose[t] -= 1
            continue
        out.append(a)
    return out


def open_asks_all(db: deps.Cardb, statuses: tuple[str, ...] = STATUSES) -> list[dict[str, Any]]:
    out = []
    page = 1000  # cardb's list cap
    for st in statuses:
        off = 0
        while True:
            rows = db.cars(status=st, limit=page, offset=off)
            for c in rows:
                out += [{"car": c["id"], **e} for e in open_asks(db, str(c["id"]))]
            if len(rows) < page:
                break
            off += page
    return out


PLACEHOLDERS = ("unknown", "pending", "asked", "missing", "n/a", "?")  # vet counts these as not in


def _record_fact(db: deps.Cardb, car: str, key: str, answer: str) -> bool:
    facts = (db.car(car) or {}).get("facts") or []
    rows = {f.get("key"): f for f in facts} if isinstance(facts, list) else facts
    cur = rows.get(key)
    val = str(cur.get("value") if isinstance(cur, dict) else cur or "").strip().lower()
    if val and not val.startswith(PLACEHOLDERS):
        return False  # keep richer evidence already recorded
    db.fact(car, key, answer[:500], source="seller_said")
    return True


def close(db: deps.Cardb, car: str, *, ask_id: str | None = None, topic: str | None = None,
          answer: str = "", record_fact: bool = True) -> dict[str, Any]:
    """Close one open ask (by event id, or the oldest open one of `topic`) with `ask_answered`;
    the answer also fills the ask's `data.fact` when that fact is still empty."""
    opened = open_asks(db, car)
    if ask_id:
        hit = next((a for a in opened if str(a.get("id")) == str(ask_id)), None)
    else:
        hit = next((a for a in opened if _topic(a) == topic), None)
    if hit is None:
        raise LookupError(f"no open ask {'id ' + str(ask_id) if ask_id else 'on topic ' + str(topic)} on car {car}")
    answer = answer.strip()
    fact = (hit.get("data") or {}).get("fact")
    data: dict[str, Any] = {"ask_event": hit["id"], "topic": _topic(hit)}
    if record_fact and fact and answer:
        data["fact_written"] = _record_fact(db, car, str(fact), answer)
    return db.event(car, "ask_answered", answer[:300] or "answered",
                    data={k: v for k, v in data.items() if v is not None}, key=f"ask_answered:{hit['id']}")
