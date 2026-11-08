"""`carhunt digest`: the owner's twice-daily summary — the only scheduled push.

Agents put FYI lines in their digest-input.md instead of pinging.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from carhunt.core import clock, notify, paths

from . import launch, settings, state
from .session import Backend

NONE = "–"


def _money(v: Any) -> str:
    try:
        return f"€{int(float(v)):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "€?"


def car_line(item: Mapping) -> str:
    car = item.get("car") or item
    title = " ".join(str(car.get(k)) for k in ("make", "model", "trim", "year") if car.get(k))
    bits = [f"#{car.get('id', '?')} {title}".strip()]
    if car.get("km") is not None:
        bits.append(f"{car['km']} km")
    bits.append(_money(car.get("price_eur", car.get("price"))))
    gap = item.get("price_gap_pct")
    if gap is not None:
        bits.append(f"{gap:+.0f}% vs fair" if isinstance(gap, (int, float)) else str(gap))
    if item.get("why"):
        bits.append(str(item["why"]))
    return "• " + " · ".join(bits)


def session_line(data: Mapping, backend: Backend | None) -> str:
    sid = data.get("active_agent")
    status = data.get("status", "?")
    bits = [f"• {data.get('role')}: {status}"]
    if backend and sid and status == "running":
        if backend.alive(sid):
            pct = backend.ctx_percent(sid)
            if pct is not None:
                bits.append(f"ctx {pct}%")
        else:
            bits.append("session gone")
    if data.get("summary"):
        bits.append(str(data["summary"]))
    return " · ".join(bits)


def needs_you(states: list[Mapping]) -> tuple[str, list[str]]:
    lines: list[str] = []
    buttons: list[str] = []
    n = 0
    for s in states:
        for item in s.get("pending_owner") or []:
            n += 1
            lines.append(f"{n}. [{s.get('role')}] {item.get('question')}")
            opts = item.get("options") or []
            if opts:
                lines.append("   " + "  ".join(f"{o['key']}) {o['text']}" for o in opts))
                buttons += [f"{n}{o['key']}" for o in opts]
            if item.get("rec"):
                lines.append(f"   → Rec: {item['rec']}")
    return ("\n".join(lines) or NONE), buttons


def collect_fyi(roles: list[str], consume: bool, stamp: str) -> list[str]:
    out: list[str] = []
    for role in roles:
        f = paths.agent_dir(role) / "digest-input.md"
        if not f.is_file():
            continue
        lines = [ln.strip().lstrip("-•* ").strip() for ln in f.read_text().splitlines()]
        out += [f"• [{role}] {ln}" for ln in lines if ln and not ln.startswith("#")]
        if consume:
            sent = f.parent / "digest-sent"
            sent.mkdir(exist_ok=True)
            f.rename(sent / f"{stamp}.md")
    return out


def cardb_queue(limit: int) -> list[dict]:
    """Top of the cardb queue (tier 1 first). Empty when cardb is unreachable: the digest still goes out."""
    from carhunt.core import db
    try:
        res = db.Client.from_config().queue(tier=1, limit=limit)
    except Exception:  # noqa: BLE001
        return []
    items = res.get("items", []) if isinstance(res, Mapping) else list(res or [])
    return list(items)[:limit]


def build(slot: str, *, backend: Backend | None, config: Mapping | None = None,
          queue: Callable[[int], list[dict]] = cardb_queue, consume: bool = False) -> tuple[str, list[str]]:
    config = config if config is not None else settings.load()
    roles = state.roles()
    states = [state.read(r) for r in roles]
    limit = int(settings.get(config, "orchestrate.digest_strong_cars", 8))
    cars = [car_line(i) for i in queue(limit)]
    ask, buttons = needs_you(states)
    advice = [f"• {a}" for s in states if s.get("role") == "learning" for a in (s.get("advice") or [])][:5]
    today = clock.now().date().isoformat()
    fyi = collect_fyi(roles, consume, f"{today}-{slot}")
    tmpl = (launch.templates_dir() / "digest.txt").read_text()
    text = launch.render(tmpl, {
        "slot": slot, "date": today,
        "sessions": "\n".join(session_line(s, backend) for s in states) or NONE,
        "cars": "\n".join(cars) or NONE,
        "needs_you": ask,
        "advice": "\n".join(advice) or NONE,
        "fyi": "\n".join(fyi) or NONE,
    })
    return text, buttons[:8]


def send(slot: str, *, backend: Backend | None, config: Mapping | None = None, dry_run: bool = False,
         queue: Callable[[int], list[dict]] = cardb_queue) -> str:
    text, buttons = build(slot, backend=backend, config=config, queue=queue, consume=not dry_run)
    if not dry_run:
        notify.send(text, agent="overseer", kind="digest", buttons=buttons or None)
    return text
