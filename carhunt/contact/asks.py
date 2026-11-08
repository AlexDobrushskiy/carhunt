"""Questions vet wants asked (cardb events type=ask) and their closing (type=ask_answered).

Outreach agents phrase an open ask as one question in the seller's language, send it with
`carhunt say`, and close it once the seller answers. An ask is open while no ask_answered event
on the same car references its id.
"""
from __future__ import annotations

from typing import Any

from . import deps


def open_asks(db: deps.Cardb, car: str) -> list[dict[str, Any]]:
    evs = db.events(car)
    closed = {str((e.get("data") or {}).get("ask_event")) for e in evs if e.get("type") == "ask_answered"}
    return [e for e in evs if e.get("type") == "ask" and str(e.get("id")) not in closed]


def open_asks_all(db: deps.Cardb, statuses: tuple[str, ...] = ("contacted", "talking")) -> list[dict[str, Any]]:
    out = []
    for st in statuses:
        for c in db.cars(status=st, limit=1000):
            for e in open_asks(db, str(c["id"])):
                out.append({"car": c["id"], **e})
    return out


def close(db: deps.Cardb, car: str, ask_id: str, answer: str) -> dict[str, Any]:
    return db.event(car, "ask_answered", answer[:300] or "answered", data={"ask_event": ask_id},
                    key=f"ask_answered:{ask_id}")
