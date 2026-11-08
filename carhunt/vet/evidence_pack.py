"""Per-car evidence pack: which pre-visit items are in, visit-ready yes/no, asks for contact.

"Visit-ready" = every dealbreaker settled remotely, because a viewing costs a day or a
flight and should end in a purchase (EV run 2026-10-31). Vet never messages sellers:
missing items become cardb `ask` events (one per message, fixed order) that the outreach
agent sends and closes with `ask_answered` (same `data.topic`).

Reads cardb CarDetail (facts, options, events, vin, powertrain). Fact values starting with
`refused` mark a refusal; `unknown|pending|asked|missing` count as not in.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from carhunt.vet import vin as vinmod

ELECTRIC = {"BEV", "PHEV"}
# Same keys as cardb's ranking.health_facts for bev/phev (docs/db.md); vet writes battery_soh.
HEALTH_FACTS = ("battery_soh", "soh", "battery_health", "battery_report", "battery_cert", "battery_test")
NOT_IN = ("unknown", "pending", "asked", "missing", "n/a", "?")


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    facts: tuple[str, ...]
    ask: str | None          # None = vet does it itself (no seller ask)
    why: str
    required: bool = True
    when: str = "always"     # always | electric | inlet


# Order = ask order (EV run pre-visit pack, 2026-10-31). Short asks get answers;
# a 4-question dealer opener got nothing (2026-11-03).
ITEMS: tuple[Item, ...] = (
    Item("registration_doc", "Registration document (front page)", ("registration_doc",),
         "Could you send a photo of the registration document (front page)?",
         "first-registration date, VIN, import, keeper count; seller = registered owner?"),
    Item("vin", "VIN", ("vin",),
         "Could you send the VIN (photo of the windscreen plate or the papers)?",
         "recalls, plant/market, history checks"),
    Item("vin_check", "Own free VIN checks", ("vin_check",), None,
         "decode + auction archive (with control) + country register before asking more"),
    Item("service_history", "Brand service record", ("service_history",),
         "Do you have the service record (stamped booklet or a dealer printout)?",
         "km trail, recalls done"),
    Item("battery_health", "Battery health evidence", HEALTH_FACTS,
         "Is there a battery health report (dealer certificate, Aviloo) or a screenshot of the car app?",
         "battery is ~40% of the car's value", when="electric"),
    Item("recall_status", "Recall / campaign status", ("recall_status", "recall"),
         "Have all recalls and service campaigns been done? A dealer printout is enough.",
         "open battery recall = waiting + charge limits"),
    Item("odometer_photo", "Odometer photo, car on", ("odometer_photo",),
         "Could you send a photo of the dashboard with the car switched on (odometer visible)?",
         "km matches ad and service record; warning lights"),
    Item("charging_inlet", "Charging inlet photo", ("charging_inlet",),
         "Could you send a photo of the charging port with the flap open?",
         "CCS2 vs GB/T / CCS1: China- or US-market car", when="inlet"),
    Item("warranty", "Warranty end date + type", ("warranty",),
         "Until when is the warranty valid, and is it the factory warranty or an extension?",
         "claim must fit first-registration date"),
    Item("accidents", "Accident / paint history", ("accidents",),
         "Has the car had any accident, paint or bodywork repair (incl. hail/PDR)?",
         "'accident-free' only means nothing reportable; dealers disclose when asked plainly"),
    Item("tyres", "Tyres: tread + DOT", ("tyres",),
         "Could you send a photo of the tyre tread and the DOT code on the sidewall?",
         "€600-1,200 if worn", required=False),
    Item("video_walkaround", "Live video walk-around", ("video_walkaround",),
         "Could we do a short video call to see the car (cold start, dashboard, charging)?",
         "owner joins the call", required=False),
    Item("history_report", "Paid history report (finalists only)", ("history_report",), None,
         "buy only for finalists, in bulk", required=False),
)


class Client(Protocol):
    def car(self, ref: str) -> dict: ...
    def event(self, ref: str, *, type: str, summary: str, data: dict | None = None,
              key: str | None = None) -> Any: ...


@dataclass
class ItemState:
    key: str
    label: str
    state: str          # have | missing | asked | refused | n/a
    required: bool
    value: str | None = None
    source: str | None = None


@dataclass
class EvidenceState:
    car: str
    fuel: str | None
    visit_ready: bool
    items: list[ItemState]
    missing: list[str]
    todo_self: list[str]
    red_flags: list[str]
    asks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def fuel_of(car: dict) -> str | None:
    """Upper-case fuel from cardb's nested powertrain (flat keys from older rows); None = unknown."""
    pt = car.get("powertrain") or {}
    fuel = str(pt.get("fuel") or car.get("fuel") or "").strip().upper()
    if fuel and fuel != "UNKNOWN":
        return fuel
    if any(d.get(k) for d in (pt, car) for k in ("battery_net_kwh", "battery_gross_kwh")):
        return "BEV"
    return None


def _facts(car: dict) -> dict[str, dict]:
    facts = car.get("facts") or []
    if isinstance(facts, dict):
        return {k: (v if isinstance(v, dict) else {"value": v}) for k, v in facts.items()}
    return {f["key"]: f for f in facts if f.get("key")}


def _open_asks(car: dict) -> tuple[dict[str, int], dict[str, int]]:
    """(open topics, all topics) -> number of asks written per topic."""
    asked: dict[str, int] = {}
    answered: dict[str, int] = {}
    for e in car.get("events") or []:
        topic = (e.get("data") or {}).get("topic")
        if not topic:
            continue
        if e.get("type") == "ask":
            asked[topic] = asked.get(topic, 0) + 1
        elif e.get("type") == "ask_answered":
            answered[topic] = answered.get(topic, 0) + 1
    return {t: n for t, n in asked.items() if n > answered.get(t, 0)}, asked


def _needs_inlet(car: dict, facts: dict, flags: list[vinmod.Flag]) -> bool:
    if any(f.code in ("china_market", "china_built", "north_america") for f in flags):
        return True
    imp = str((facts.get("import") or {}).get("value") or "").lower()
    return imp.startswith(("yes", "import"))


def assess(car: dict, ref: str | None = None) -> EvidenceState:
    ref = ref or str(car.get("id"))
    facts = _facts(car)
    fuel = fuel_of(car)
    electric = fuel is None or fuel in ELECTRIC  # unknown powertrain: stay conservative
    open_asks, _ = _open_asks(car)

    red: list[str] = []
    vin = car.get("vin") or (facts.get("vin") or {}).get("value")
    flags: list[vinmod.Flag] = []
    if vin:
        info = vinmod.decode(vin, first_reg=car.get("reg_date"))
        flags = info.flags
        red += [f"VIN: {f.text}" for f in flags if f.severity == "red"]
    red += [f"conflict: {k}" for k in facts if k.endswith("_conflict")]

    items: list[ItemState] = []
    for it in ITEMS:
        required = it.required
        if it.when == "electric" and not electric:
            items.append(ItemState(it.key, it.label, "n/a", False))
            continue
        if it.when == "inlet" and not (electric and _needs_inlet(car, facts, flags)):
            items.append(ItemState(it.key, it.label, "n/a", False))
            continue
        val, src = None, None
        if it.key == "vin" and vin:
            val, src = vin, "car"
        elif it.key == "vin_check" and any(e.get("type") == "vin_check" for e in car.get("events") or []):
            val, src = "vin_check event", "event"
        for k in it.facts:
            f = facts.get(k)
            if f and str(f.get("value") or "").strip():
                val, src = str(f["value"]).strip(), f.get("source")
                break
        low = (val or "").lower()
        if val and low.startswith("refused"):
            state = "refused"
            if required:
                red.append(f"seller refused: {it.label}")
        elif val and not low.startswith(NOT_IN):
            state = "have"
        elif it.key in open_asks:
            state = "asked"
        else:
            state = "missing"
        items.append(ItemState(it.key, it.label, state, required, val, src))

    missing = [s.key for s in items if s.required and s.state != "have"]
    todo_self = [s.key for s, it in zip(items, ITEMS) if it.ask is None and s.required and s.state == "missing"]
    return EvidenceState(car=ref, fuel=fuel, visit_ready=not missing and not red, items=items,
                         missing=missing, todo_self=todo_self, red_flags=red)


def plan_asks(car: dict, state: EvidenceState, max_asks: int = 1) -> list[dict]:
    """Next asks in fixed order: skip have/asked/refused/n-a; at most `max_asks` open at once."""
    open_asks, asked = _open_asks(car)
    budget = max(0, max_asks - len(open_asks))
    by_key = {it.key: it for it in ITEMS}
    out = []
    for s in state.items:
        if budget <= 0:
            break
        it = by_key[s.key]
        if it.ask is None or s.state != "missing" or not s.required:
            continue
        n = asked.get(it.key, 0)
        out.append({"type": "ask", "summary": it.ask,
                    "data": {"topic": it.key, "fact": it.facts[0], "why": it.why, "item": it.label},
                    "key": f"ask:{state.car}:{it.key}:{n + 1}"})
        budget -= 1
    return out


def run(client: Client, ref: str, *, write_asks: bool = False, max_asks: int = 1) -> EvidenceState:
    car = client.car(ref)
    state = assess(car, ref)
    asks = plan_asks(car, state, max_asks)
    if write_asks:
        for a in asks:
            client.event(ref, type=a["type"], summary=a["summary"], data=a["data"], key=a["key"])
    state.asks = asks
    return state


def render(state: EvidenceState) -> str:
    mark = {"have": "✅", "missing": "❌", "asked": "⏳", "refused": "⛔", "n/a": "·"}
    lines = [f"car {state.car}  fuel={state.fuel or '?'}  visit-ready: "
             + ("YES" if state.visit_ready else "no")]
    for s in state.items:
        req = "" if s.required else " (optional)"
        val = f" — {s.value[:70]}" if s.value and s.state != "missing" else ""
        lines.append(f"  {mark.get(s.state, '?')} {s.label}{req}{val}")
    if state.todo_self:
        lines.append("vet to do (own checks): " + ", ".join(state.todo_self))
    lines += [f"  ! {r}" for r in state.red_flags]
    for a in state.asks:
        lines.append(f"ask → {a['data']['topic']}: {a['summary']}")
    return "\n".join(lines)
