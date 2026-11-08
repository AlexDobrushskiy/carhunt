"""Shared pace ledger: per-site rate budget + per-local-day caps, across every agent on this machine.

    from carhunt.access import pace
    t = pace.acquire("coches.net", "load")            # raises PaceExceeded(retry_at=…) when over budget
    pace.acquire("leboncoin.fr", "phone", who="sweep")  # day cap: take the slot BEFORE the action
    pace.check("mobile.de", "load")                     # Status, records nothing

Why shared: one IP ⇒ one budget. Another agent's two liveness checks silently ate a sender's coches.net slot (11-02);
coches allows ≤2 loads per rolling hour for everyone on the IP.
Why take before the action: an attempt hits the site whether it succeeds or not (leboncoin reveals, 11-05).
Day = owner's local calendar day (`owner.tz`), not a hardcoded zone.

Ledger: SQLite `$CARHUNT_HOME/access/pace.sqlite` (WAL; every decision under `BEGIN IMMEDIATE`, so concurrent
processes never both get the last slot). A broken ledger refuses (fail closed), it never silently allows.

Limits: `carhunt/sites/<site>/site.yaml` (`pace{min_gap_s, max_loads_per_run, per_hour}`,
`caps{phone_per_day, send_per_day, login_per_day, <kind>_min_gap_s}`), then config `sites.overrides.<site>`, else DEFAULTS.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from carhunt.access import _core
from carhunt.access.errors import PaceExceeded

KINDS = ("load", "phone", "send", "login")

# Conservative defaults for a site nobody has measured yet:
# - 12 s between loads: ≥10–12 s survived where 6 s got 403s (custojusto after ~50 ads at 6 s, 11-03; leboncoin, mobile.de).
# - 30 loads/rolling hour: under the lowest burst ceilings seen (mobile.de ~25 fast loads/profile, home-IP 403 after ~41, 11-06).
# - 60 loads per run: mobile.de's measured per-run ceiling (≤60/run).
# - phone 5/day, send 10/day: per-account actions; unmeasured sites get a fraction of the measured ones
#   (milanuncios ≤9 reveals/day, leboncoin ≤40/day).
# - login 3/day: repeated logins trip new-device checks and SMS challenges, which can lock an account (11-02).
DEFAULTS: dict[str, Any] = {
    "pace": {"min_gap_s": 12, "per_hour": 30, "max_loads_per_run": 60},
    "caps": {"phone_per_day": 5, "send_per_day": 10, "login_per_day": 3},
}
RUN_WINDOW_S = 3600  # max_loads_per_run counts one `who`'s loads in this window
REPO_SITES = Path(__file__).resolve().parents[1] / "sites"


# ---------- site.yaml lookup ----------

def _plain(x: Any) -> Any:
    if isinstance(x, Mapping):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    return x


def _norm(name: str) -> str:
    return name.lower().replace(".", "_").replace("-", "_")


def sites_dirs() -> list[Path]:
    """Where site.yaml files are searched: $CARHUNT_SITES_DIR (os.pathsep list) first, then carhunt/sites/."""
    env = os.environ.get("CARHUNT_SITES_DIR")
    dirs = [Path(p).expanduser() for p in env.split(os.pathsep) if p] if env else []
    return dirs + [REPO_SITES]


def site_yaml(site: str) -> dict:
    """The site's site.yaml as a dict ({} when no plugin describes it).

    Matches the folder name, or its `name` / `domain` / `domains` keys, ignoring case, dots and dashes.
    """
    import yaml
    want = _norm(site)
    for d in sites_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*/site.yaml")):
            try:
                data = yaml.safe_load(f.read_text()) or {}
            except (OSError, yaml.YAMLError):
                continue
            names = {f.parent.name, str(data.get("name") or ""), str(data.get("domain") or "")}
            names |= {str(x) for x in (data.get("domains") or [])}
            if want in {_norm(n) for n in names if n}:
                return _plain(data)
    return {}


def site_config(site: str) -> dict:
    """site.yaml merged with config `sites.overrides.<site>` (override wins, one level deep per section)."""
    data = site_yaml(site)
    over = _plain((_core.section("sites").get("overrides") or {}).get(site) or {})
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(data.get(k), dict):
            data[k] = {**data[k], **v}
        else:
            data[k] = v
    return data


@dataclass(frozen=True)
class Limits:
    per_day: int | None       # local-day cap (None = no day cap)
    per_hour: int | None      # rolling-hour budget
    per_run: int | None       # per `who` within RUN_WINDOW_S
    min_gap_s: float          # between any two hits by anyone


def limits(site: str, kind: str) -> Limits:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    cfg = site_config(site)
    p = {**DEFAULTS["pace"], **(cfg.get("pace") or {})}
    c = {**DEFAULTS["caps"], **(cfg.get("caps") or {})}

    def num(v):
        return None if v is None else float(v)

    def cnt(v):
        return None if v is None else int(v)

    if kind == "load":
        return Limits(cnt(c.get("load_per_day")), cnt(p.get("per_hour")), cnt(p.get("max_loads_per_run")),
                      num(p.get("min_gap_s")) or 0.0)
    return Limits(cnt(c.get(f"{kind}_per_day")), cnt(c.get(f"{kind}_per_hour")), None,
                  num(c.get(f"{kind}_min_gap_s")) or 0.0)


# ---------- ledger ----------

@dataclass(frozen=True)
class Ticket:
    id: int
    site: str
    kind: str
    at: float
    who: str


@dataclass
class Status:
    site: str
    kind: str
    allowed: bool
    reason: str
    retry_at: datetime | None
    used_today: int
    per_day: int | None
    used_hour: int
    per_hour: int | None
    used_run: int
    per_run: int | None
    min_gap_s: float
    last_at: datetime | None

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("retry_at", "last_at"):
            d[k] = d[k].isoformat(timespec="seconds") if d[k] else None
        return d


def _now() -> datetime:
    # always in owner.tz: an offset-aware CARHUNT_FAKE_NOW would otherwise keep its own offset
    return _core.now().astimezone(_core.tz())


def db_path() -> Path:
    return _core.path("access", "pace.sqlite")


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(db_path(), timeout=30, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("""CREATE TABLE IF NOT EXISTS hits (
        id INTEGER PRIMARY KEY, site TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL,
        at REAL NOT NULL, day TEXT NOT NULL, who TEXT NOT NULL, refunded INTEGER NOT NULL DEFAULT 0)""")
    c.execute("CREATE INDEX IF NOT EXISTS hits_scope ON hits(scope, kind, at)")
    c.execute("CREATE INDEX IF NOT EXISTS hits_day ON hits(site, kind, day)")
    return c


def _who(who: str | None) -> str:
    return who or os.environ.get("CARHUNT_RUN_ID") or os.environ.get("AGTERM_SESSION_ID") or f"pid{os.getpid()}"


def _scope(site: str, via: str | None) -> str:
    # Rate budgets belong to the exit IP: a proxied run (via="fr") has its own. Day caps belong to the account: site only.
    return f"{site}@{via.lower()}" if via else site


def _evaluate(c: sqlite3.Connection, site: str, kind: str, who: str, via: str | None) -> Status:
    lim = limits(site, kind)
    now = _now()
    ts, day, tz = now.timestamp(), now.date().isoformat(), now.tzinfo
    scope = _scope(site, via)
    q = "SELECT COUNT(*), MIN(at) FROM hits WHERE scope=? AND kind=? AND at>? AND refunded=0"
    used_day = c.execute("SELECT COUNT(*) FROM hits WHERE site=? AND kind=? AND day=? AND refunded=0",
                         (site, kind, day)).fetchone()[0]
    used_hour, first_hour = c.execute(q, (scope, kind, ts - 3600)).fetchone()
    used_run = c.execute(q + " AND who=?", (scope, kind, ts - RUN_WINDOW_S, who)).fetchone()[0]
    last = c.execute("SELECT MAX(at) FROM hits WHERE scope=? AND kind=? AND refunded=0", (scope, kind)).fetchone()[0]

    def at(x: float) -> datetime:
        return datetime.fromtimestamp(x, tz)

    allowed, reason, retry = True, "ok", None
    if lim.per_day is not None and used_day >= lim.per_day:
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        allowed, reason, retry = False, f"day cap {lim.per_day} reached ({used_day} on {day})", midnight
    elif lim.per_run is not None and used_run >= lim.per_run:
        allowed, reason = False, f"run cap {lim.per_run} reached for {who} (new run after a break)"
        retry = at(ts + RUN_WINDOW_S)
    elif lim.per_hour is not None and used_hour >= lim.per_hour:
        allowed, reason, retry = False, f"{lim.per_hour}/rolling hour used", at(first_hour + 3600)
    elif last is not None and ts - last < lim.min_gap_s:
        allowed, reason, retry = False, f"min gap {lim.min_gap_s:g}s", at(last + lim.min_gap_s)
    return Status(site, kind, allowed, reason, retry, used_day, lim.per_day, used_hour, lim.per_hour,
                  used_run, lim.per_run, lim.min_gap_s, at(last) if last else None)


def _take_once(site: str, kind: str, who: str, via: str | None) -> tuple[Ticket | None, Status]:
    c = _connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        try:
            st = _evaluate(c, site, kind, who, via)
            ticket = None
            if st.allowed:
                now = _now()
                cur = c.execute("INSERT INTO hits(site, scope, kind, at, day, who) VALUES (?,?,?,?,?,?)",
                                (site, _scope(site, via), kind, now.timestamp(), now.date().isoformat(), who))
                ticket = Ticket(cur.lastrowid, site, kind, now.timestamp(), who)
            c.execute("COMMIT")
            return ticket, st
        except BaseException:
            c.execute("ROLLBACK")
            raise
    finally:
        c.close()


def acquire(site: str, kind: str, *, who: str | None = None, wait: bool = False, via: str | None = None,
            max_wait_s: float = 900, sleep=time.sleep) -> Ticket:
    """Record one `kind` hit on `site` if the budget allows, else raise PaceExceeded(retry_at=…).

    wait=True sleeps until a gap/hourly refusal clears (at most `max_wait_s` in total); day and run caps never wait.
    `via` = exit country when the hit goes through a proxy (separate rate budget, same day caps).
    """
    who = _who(who)
    deadline = time.monotonic() + max_wait_s
    while True:
        try:
            ticket, st = _take_once(site, kind, who, via)
        except sqlite3.Error as e:  # fail closed: no ledger, no hit
            raise PaceExceeded(site, kind, reason=f"pace ledger error: {e}") from e
        if ticket:
            return ticket
        waitable = st.retry_at is not None and not st.reason.startswith(("day cap", "run cap"))
        delay = (st.retry_at - _now()).total_seconds() if st.retry_at else 0
        if not (wait and waitable) or time.monotonic() + delay > deadline:
            raise PaceExceeded(site, kind, retry_at=st.retry_at, reason=st.reason)
        sleep(max(delay, 0.05))


def check(site: str, kind: str, *, who: str | None = None, via: str | None = None) -> Status:
    """What acquire() would decide now; records nothing."""
    c = _connect()
    try:
        return _evaluate(c, site, kind, _who(who), via)
    finally:
        c.close()


def refund(ticket: Ticket) -> None:
    """Give a slot back. Only when the action never reached the site (e.g. the browser failed to launch);
    a request that was sent counts even if it failed."""
    c = _connect()
    try:
        c.execute("UPDATE hits SET refunded=1 WHERE id=?", (ticket.id,))
    finally:
        c.close()


release = refund


def reset_day(site: str, kind: str | None = None) -> int:
    """Owner override: void today's hits for site (and kind). Returns how many."""
    day = _now().date().isoformat()
    c = _connect()
    try:
        q, a = "UPDATE hits SET refunded=1 WHERE site=? AND day=? AND refunded=0", [site, day]
        if kind:
            q, a = q + " AND kind=?", a + [kind]
        return c.execute(q, a).rowcount
    finally:
        c.close()


def status(site: str | None = None) -> list[Status]:
    """Status per (site, kind) seen in the ledger today/this hour, or every kind for one site."""
    if site:
        return [check(site, k) for k in KINDS]
    c = _connect()
    try:
        since = _now().timestamp() - max(3600, RUN_WINDOW_S)
        day = _now().date().isoformat()
        rows = c.execute("SELECT DISTINCT site, kind FROM hits WHERE (at>? OR day=?) AND refunded=0 ORDER BY 1, 2",
                         (since, day)).fetchall()
    finally:
        c.close()
    return [check(s, k) for s, k in rows]


# ---------- CLI: carhunt pace status|take|reset-day ----------

def _cmd_status(a) -> int:
    for st in status(a.site):
        print(json.dumps(st.as_dict(), ensure_ascii=False))
    return 0


def _cmd_take(a) -> int:
    try:
        t = acquire(a.site, a.kind, who=a.who, wait=a.wait, via=a.via)
    except PaceExceeded as e:
        print(json.dumps({"ok": False, "reason": e.reason,
                          "retry_at": e.retry_at.isoformat(timespec="seconds") if e.retry_at else None}))
        return 3
    print(json.dumps({"ok": True, "id": t.id, "site": t.site, "kind": t.kind, "who": t.who}))
    return 0


def _cmd_reset(a) -> int:
    print(json.dumps({"site": a.site, "kind": a.kind, "voided": reset_day(a.site, a.kind)}))
    return 0


def register_cli(sub) -> None:
    p = sub.add_parser("pace", help="shared per-site pace ledger and day caps")
    p.set_defaults(_parser=p)
    s = p.add_subparsers(dest="pace_cmd", metavar="<cmd>")
    x = s.add_parser("status", help="budget per site/kind (JSON lines)")
    x.add_argument("site", nargs="?")
    x.set_defaults(func=_cmd_status)
    x = s.add_parser("take", help="take one slot (exit 0 ok, 3 refused)")
    x.add_argument("site")
    x.add_argument("kind", choices=KINDS)
    x.add_argument("--who")
    x.add_argument("--via", help="exit country when going through a proxy")
    x.add_argument("--wait", action="store_true", help="sleep through a gap/hourly refusal")
    x.set_defaults(func=_cmd_take)
    x = s.add_parser("reset-day", help="void today's slots for a site (owner override)")
    x.add_argument("site")
    x.add_argument("kind", nargs="?", choices=KINDS)
    x.set_defaults(func=_cmd_reset)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pace")
    register_cli(ap.add_subparsers(dest="group"))
    a = ap.parse_args(["pace", *(argv or [])])
    return int(a.func(a)) if hasattr(a, "func") else 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
