"""`carhunt say`: the only way a message leaves. One flock around guard → send → verify → ledger,
then cardb (never blocks the send). EV bug this fixes: two openers went out 4 s apart because
the old guard read the log, sent, then appended without a lock (2026-11-04).
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import deps, guard
from .channels import get as get_channel
from .channels.base import DELIVERED, FAILED, Channel, ChannelError, Msg
from .ledger import FAILED as L_FAILED
from .ledger import SENT, UNKNOWN, Entry, Ledger, log_to_db
from .settings import channel_enabled, contact_settings

EXIT_SENT, EXIT_REFUSED, EXIT_FAILED, EXIT_UNKNOWN = 0, 10, 11, 12
LOCK = "contact-send"


@dataclass
class Outcome:
    code: int
    decision: guard.Decision
    payload: dict[str, Any] | None = None
    entry: Entry | None = None
    db: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"exit": self.code, "ok": self.decision.ok, "rule": self.decision.rule, "reason": self.decision.reason,
                "payload": self.payload, "ledger_id": self.entry.id if self.entry else None,
                "status": self.entry.status if self.entry else None, "cardb": self.db}


def caller_problem(s: dict[str, Any]) -> str | None:
    """A launched agent (role set) must still be its role's active agent: background chains from a
    session that was handed over get refused (EV: chains kept sending after a handover, 2026-11-06)."""
    role = os.environ.get("CARHUNT_AGENT") or os.environ.get("CARDB_AUTHOR")
    if not s["require_active_agent"] or not role:
        return None
    me = os.environ.get("AGTERM_SESSION_ID", "")
    p = deps.home() / "agents" / role / "state.json"
    try:
        active = json.loads(p.read_text()).get("active_agent")
    except (OSError, json.JSONDecodeError):
        return f"caller role {role}: no readable {p.name} for that role"
    if not me or active != me:
        return f"caller {me or '?'} is not the active {role} agent"
    return None


def overrides(now: datetime) -> dict[str, int]:
    """One-day cap overrides set by the owner: contact/cap_override.json {"date", "limits": {name: max}}."""
    p = deps.home() / "contact" / "cap_override.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: int(v) for k, v in (d.get("limits") or {}).items()} if d.get("date") == str(now.date()) else {}


def resolve_car(db: deps.Cardb | None, car: str | None) -> dict[str, Any] | None:
    if not car or db is None:
        return None
    if car.startswith(("http://", "https://")):
        li = db.find_listing(car)
        if not li:
            raise deps.CardbNotFound(f"no listing for {car}")
        car = str(li.get("car_id") or li.get("car"))
    return db.car(car)


def default_to(ch: Channel, car: dict[str, Any] | None, car_arg: str | None) -> str | None:
    if ch.kind == "site":
        if car_arg and car_arg.startswith("http"):
            return car_arg
        for li in (car or {}).get("listings") or []:
            if li.get("site") == ch.name and li.get("status", "live") == "live":
                return li.get("url")
        return None
    kinds = ("whatsapp", "phone") if ch.kind == "chat" else ("email",)
    for k in kinds:
        for c in ((car or {}).get("seller") or {}).get("contacts") or []:
            if c.get("kind") == k and not c.get("shared"):
                return str(c.get("value"))
    return None


def thread_from_cardb(db: deps.Cardb | None, car: dict[str, Any] | None, channel: str, to: str,
                      kind: str) -> list[Msg] | None:
    if db is None or not car:
        return None
    try:
        rows = db.msgs(str(car.get("id")))
    except deps.CardbError:
        return None
    want = guard.norm_target(to, kind)
    out = []
    for r in rows:
        if r.get("channel") != channel or r.get("deleted_at"):
            continue
        cp = r.get("counterpart")
        if cp and guard.norm_target(cp, kind) != want:
            continue
        out.append(Msg(at=datetime.fromisoformat(str(r["at"]).replace("Z", "+00:00")),
                       from_me=r.get("direction") == "out", text=r.get("text") or "", id=str(r.get("id") or "")))
    return sorted(out, key=lambda m: m.at)


def run(*, channel: str, text: str, car: str | None = None, to: str | None = None, mode: str = guard.REPLY,
        dry_run: bool = False, cfg: dict[str, Any] | None = None, db: deps.Cardb | None = None,
        ch: Channel | None = None, ledger: Ledger | None = None, use_db: bool = True,
        channel_opts: dict[str, Any] | None = None) -> Outcome:
    cfg = cfg if cfg is not None else deps.load_config()
    s = contact_settings(cfg)
    ch = ch or get_channel(channel, cfg, **(channel_opts or {}))
    if db is None and use_db:
        db = deps.Cardb.from_config(cfg)
    ledger = ledger or Ledger()
    text = text.strip()
    if not channel_enabled(s, ch.name, ch.kind):
        return Outcome(EXIT_REFUSED, guard.Decision(False, "channel", f"{ch.name} is not in contact.channels"))

    try:
        car_d = resolve_car(db, car)
    except deps.CardbNotFound:
        return Outcome(EXIT_REFUSED, guard.Decision(False, "target", f"car {car} not found in cardb"))
    except deps.CardbError as e:
        return Outcome(EXIT_REFUSED, guard.Decision(False, "target", f"cardb unreachable, can't check target: {e}"))
    to = to or default_to(ch, car_d, car)
    if not to:
        return Outcome(EXIT_REFUSED, guard.Decision(False, "target", f"no {ch.name} contact on the car: pass --to"))
    to = ch.normalize_to(to)
    role = os.environ.get("CARHUNT_AGENT") or os.environ.get("CARDB_AUTHOR") or "owner"

    def decide() -> guard.Decision:
        now = deps.now(cfg)
        thread: list[Msg] | None
        # dry run reads only local sources (wacli's local DB, cardb); sites/email would hit the network
        if ch.can_read and (not dry_run or ch.kind == "chat"):
            try:
                thread = ch.read_thread(to, limit=200 if mode == guard.NUDGE else 50)
            except ChannelError as e:
                if "group chat" in str(e):
                    return guard.Decision(False, "target", str(e))
                thread = thread_from_cardb(db, car_d, ch.name, to, ch.kind)
        else:
            thread = thread_from_cardb(db, car_d, ch.name, to, ch.kind)
        req = guard.Request(channel=ch.name, channel_kind=ch.kind, to=to, text=text, mode=mode, role=role,
                            max_len=int((s["channels"].get(ch.name) or {}).get("max_len") or ch.max_len),
                            channel_refusal=ch.check_text(text))
        ctx = guard.Context(settings=s, now=now, ledger=ledger.entries(), thread=thread, car=car_d,
                            paused=deps.pause_file().exists(), caller_problem=caller_problem(s),
                            overrides=overrides(now))
        return guard.evaluate(req, ctx)

    if dry_run:
        d = decide()
        return Outcome(EXIT_SENT if d.ok else EXIT_REFUSED, d, ch.dry_run(to, text) if d.ok else None)

    with deps.flock(LOCK):
        d = decide()  # re-checked inside the lock, right before the send (rules change mid-chain)
        if not d.ok:
            return Outcome(EXIT_REFUSED, d)
        try:
            res = ch.send(to, text)
        except ChannelError as e:
            from .channels.base import SendResult
            res = SendResult(False, error=str(e))
        try:
            v = ch.verify(to, text, res)
        except Exception:  # verification trouble ≠ failed send
            v = "unknown"
        flags = [k for k in ("blocked", "login", "gone", "no_form", "already_contacted", "refused") if res.raw.get(k)]
        if flags:  # site signals: blocked → stop this site; gone/no_form → other channel
            res.error = (res.error + f" [{','.join(flags)}]").strip()
        status = SENT if v == DELIVERED else L_FAILED if v == FAILED else UNKNOWN
        e = ledger.append(Entry(channel=ch.name, to=to, text=text, status=status, t=deps.now(cfg).timestamp(),
                                car=str(car_d["id"]) if car_d else None, kind=mode, by=role,
                                err=res.error[-300:], external_id=res.external_id))
    dbmsg = ""
    if db is not None and e.car:
        try:  # cardb failure never blocks or retries the send; `carhunt ledger reconcile` backfills
            log_to_db(db, e)
            dbmsg = "logged"
        except Exception as ex:
            dbmsg = f"skipped ({ex.__class__.__name__}): run `carhunt ledger reconcile`"
    code = {SENT: EXIT_SENT, L_FAILED: EXIT_FAILED, UNKNOWN: EXIT_UNKNOWN}[status]
    return Outcome(code, d, None, e, dbmsg)


def print_outcome(o: Outcome, as_json: bool, dry_run: bool) -> None:
    if as_json:
        print(json.dumps(o.as_dict(), ensure_ascii=False))
        if not o.decision.ok:
            print(f"REFUSED [{o.decision.rule}]: {o.decision.reason}", file=sys.stderr)
        return
    if not o.decision.ok:
        print(f"REFUSED [{o.decision.rule}]: {o.decision.reason}", file=sys.stderr)
        return
    if dry_run:
        print("DRY-RUN OK: guard passes (nothing sent)")
        print("would send: " + json.dumps(o.payload, ensure_ascii=False))
        return
    st = o.entry.status if o.entry else "?"
    print({"sent": "SENT", "failed": "FAILED", "unknown": "UNKNOWN delivery: check the channel before any re-send"}
          .get(st, st) + (f" ({o.entry.err})" if o.entry and o.entry.err else ""))
    print(f"ledger: {o.entry.id if o.entry else '-'}  cardb: {o.db or '-'}")
