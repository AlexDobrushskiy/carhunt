"""`carhunt liveness`: is each live cardb listing's ad still online? Read-only on the sites (one GET per ad).

Writes only through cardb: `PATCH /listings/{id}` (status) + an `ad_check` event with the evidence; a live check
on a live listing is a sighting (upsert by URL bumps last_seen). Never touches car status, never deletes.

Rules (why):
- removed at once on 404/410 or the site's own gone marker; a redirect to a list page is a *soft* signal → removed
  only on the 2nd soft signal ≥1 h after the first (milanuncios redirects live ads now and then, 11-04).
- never on a block/timeout/unknown: a block says nothing about the ad (an ad-hoc check once removed 2 live cars).
- a live page also yields the current asking price (same page, no extra load): a change is written as a minimal
  upsert {url, price} → cardb's price history + price_change event. Newest-first sweeps never revisit known ads,
  so price drops are caught here (EV run: weekly price re-check of liked cars). Net prices are skipped (cardb = gross).
- the first block stops that site for the run (more loads only deepen the ban).
- relists only what this tool removed: removals by agents/owner are deliberate and left alone.
- a site out of pace budget stops for this run; with `--proxy-priority`, priority listings go through the site's
  `liveness.proxy_country` exit instead (coches.net: ≤2 home-IP loads/h, 11-04).
State (last check, soft counts, what we removed): $CARHUNT_HOME/sites/liveness.db. Logs: $CARHUNT_HOME/sites/liveness/.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from carhunt.access import _core
from carhunt.access.errors import AccessError, Blocked, PaceExceeded
from carhunt.sites import base
from carhunt.sites.model import Liveness

WHO = "liveness"
SOFT_GAP_S = 3600
DUE_S = {"priority": 20 * 3600, "normal": 36 * 3600, "removed": 72 * 3600, "soft": 3600}


class DB(Protocol):
    """The cardb calls liveness needs (carhunt.core.db.Client satisfies it via `CardbAdapter`)."""
    def listings(self, status: str) -> list[dict]: ...
    def cars(self) -> dict[int, dict]: ...
    def patch_status(self, listing_id: int, status: str) -> None: ...
    def event(self, car_id: int, listing_id: int, summary: str, key: str, data: dict) -> None: ...
    def sighting(self, url: str, price: int | None = None) -> None: ...


class CardbAdapter:
    def __init__(self, client: Any):
        self.c = client

    @staticmethod
    def _items(res: Any, key: str) -> list[dict]:
        if isinstance(res, dict):
            return res.get("items") or res.get(key) or []
        return res or []

    def listings(self, status: str) -> list[dict]:
        return self._items(self.c.request("GET", "/listings", params={"status": status}), "listings")

    def cars(self) -> dict[int, dict]:
        out, off = {}, 0
        while True:
            res = self.c.cars(limit=1000, offset=off)
            items = self._items(res, "cars")
            for car in items:
                out[car["id"]] = car
            off += len(items)
            total = res.get("total") if isinstance(res, dict) else None
            if not items or total is None or off >= total:
                return out

    def patch_status(self, listing_id: int, status: str) -> None:
        self.c.listing_patch(listing_id, {"status": status, "author": WHO})

    def event(self, car_id: int, listing_id: int, summary: str, key: str, data: dict) -> None:
        self.c.event(car_id, "ad_check", summary, data=data, key=key, listing=listing_id)

    def sighting(self, url: str, price: int | None = None) -> None:
        """Minimal upsert: bumps last_seen; with a price, cardb appends price history + a price_change event."""
        body: dict[str, Any] = {"url": url, "author": WHO}
        if price is not None:
            body["price"] = price
        self.c.upsert_listing(body)


def connect_db() -> DB:
    from carhunt.core import db  # core module: cardb REST client
    return CardbAdapter(db.Client.from_config(author=WHO))


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def priority(car: dict | None) -> int:
    """0 = check first: owner liked/maybe → open chats → good deal → tier 1/2 unrated → rest → disliked → closed."""
    if not car:
        return 9
    v = car.get("verdict")
    v = v.get("value") if isinstance(v, dict) else v
    if car.get("status") in ("dropped", "closed", "bought"):
        return 8
    if v in ("up", "maybe"):
        return 0
    if car.get("status") in ("contacted", "talking", "ready_to_visit"):
        return 1
    if car.get("good_deal") or car.get("deal_rank"):
        return 2
    if v in (None, "none") and str(car.get("tier")) in ("1", "2"):
        return 3
    return 7 if v == "down" else 4


class State:
    """sqlite: per listing last check, soft-signal count, removed_by_us. dry=True works on an in-memory copy."""

    def __init__(self, path: Path, dry: bool = False):
        path.parent.mkdir(parents=True, exist_ok=True)
        disk = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
        disk.execute("""CREATE TABLE IF NOT EXISTS checks (listing_id INTEGER PRIMARY KEY, last_at REAL, verdict TEXT,
            signal TEXT, soft_n INTEGER DEFAULT 0, soft_first REAL, removed_by_us INTEGER DEFAULT 0)""")
        if dry:
            mem = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            disk.backup(mem)
            disk.close()
            self.c = mem
        else:
            disk.execute("PRAGMA journal_mode=WAL")
            self.c = disk
        self.lock = threading.Lock()

    def get(self, lid: int) -> dict:
        with self.lock:
            r = self.c.execute("SELECT last_at, verdict, signal, soft_n, soft_first, removed_by_us FROM checks "
                               "WHERE listing_id=?", (lid,)).fetchone()
        keys = ["last_at", "verdict", "signal", "soft_n", "soft_first", "removed_by_us"]
        return dict(zip(keys, r, strict=True)) if r else {}

    def put(self, lid: int, **kw: Any) -> None:
        with self.lock:
            self.c.execute("INSERT OR IGNORE INTO checks (listing_id) VALUES (?)", (lid,))
            for k, v in kw.items():
                self.c.execute(f"UPDATE checks SET {k}=? WHERE listing_id=?", (v, lid))

    def ours(self) -> set[int]:
        with self.lock:
            return {r[0] for r in self.c.execute("SELECT listing_id FROM checks WHERE removed_by_us=1")}


def verdict_of(lv: Liveness) -> str:
    if lv.state == "removed":
        return "gone_soft" if lv.soft else "gone"
    return lv.state   # live | unknown


def new_price(lst: dict, price: int | None, is_net: bool | None) -> int | None:
    """The page's price when it differs from cardb's. Net (ex-VAT) prices are skipped: cardb stores gross."""
    if price is None or is_net or not lst.get("price"):
        return None
    return price if int(price) != int(lst["price"]) else None


def apply(db: DB, st: State, lst: dict, verdict: str, signal: str, *, dry: bool, now: float | None = None,
          price: int | None = None) -> str | None:
    """Apply one verdict. Returns the action: removed | relisted | soft | seen | price | None.
    `price` = a changed asking price seen on the live page (written with the sighting)."""
    lid, car = lst["id"], lst["car_id"]
    s = st.get(lid)
    now = now if now is not None else time.time()
    day = now_iso()[:10]
    data = {"verdict": verdict, "signal": signal, "url": lst["url"], "checked_at": now_iso()}
    if verdict == "live":
        st.put(lid, soft_n=0, soft_first=None)
        if lst["status"] == "live":
            if not dry:
                db.sighting(lst["url"], price)
            return "price" if price is not None else "seen"
        if lst["status"] == "removed" and s.get("removed_by_us"):
            if not dry:
                db.patch_status(lid, "live")
                if price is not None:
                    db.sighting(lst["url"], price)
                db.event(car, lid, f"{lst['site']} ad is back online", f"liveness:{lid}:back:{day}", data)
                st.put(lid, removed_by_us=0)
            return "relisted"
        return None
    if verdict in ("gone", "gone_soft") and lst["status"] == "live":
        if verdict == "gone_soft":
            n = (s.get("soft_n") or 0) + 1
            first = s.get("soft_first") or now
            st.put(lid, soft_n=n, soft_first=first)
            if n < 2 or now - first < SOFT_GAP_S:
                return "soft"
        if not dry:
            db.patch_status(lid, "removed")
            db.event(car, lid, f"{lst['site']} ad gone ({signal[:60]})", f"liveness:{lid}:gone:{day}", data)
            st.put(lid, removed_by_us=1, soft_n=0, soft_first=None)
        return "removed"
    return None


@dataclass
class Run:
    db: DB
    st: State
    dry: bool = False
    until: float | None = None
    out: Any = None
    proxy_priority: bool = False
    plugin: Callable[[str], base.BaseSite] = base.get
    stats: dict[str, dict] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.lock = threading.Lock()

    def over(self) -> bool:
        return bool(self.until and time.time() >= self.until)

    def note(self, site: str, lst: dict, verdict: str, signal: str, act: str | None, prio: int,
             price: int | None = None) -> None:
        rec = {"at": now_iso(), "listing": lst["id"], "car": lst["car_id"], "site": site, "verdict": verdict,
               "signal": signal, "action": act, "prio": prio, "url": lst["url"], "price": price}
        with self.lock:
            s = self.stats.setdefault(site, {"checked": 0})
            s["checked"] += 1
            s[verdict] = s.get(verdict, 0) + 1
            if act and act != "seen":
                s[act] = s.get(act, 0) + 1
            self.results.append(rec)
            if self.out:
                self.out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                self.out.flush()
        print(f"[{time.strftime('%H:%M:%S')}] {site:16} #{lst['car_id']}/{lst['id']} {verdict:9} {signal[:70]}"
              f"{' → ' + act if act and act != 'seen' else ''}", file=sys.stderr, flush=True)

    def stop(self, site: str, why: str) -> None:
        with self.lock:
            self.stats.setdefault(site, {"checked": 0})["stopped"] = why[:160]
        print(f"[{time.strftime('%H:%M:%S')}] {site}: stopped ({why[:120]})", file=sys.stderr, flush=True)

    def one(self, site: str, lst: dict, verdict: str, signal: str, prio: int, lv: Liveness | None = None) -> None:
        if verdict in ("blocked", "unknown"):
            self.st.put(lst["id"], verdict=verdict, signal=signal)   # last_at untouched: retried next run
            self.note(site, lst, verdict, signal, None, prio)
            return
        price = new_price(lst, lv.price, lv.price_is_net) if lv else None
        try:
            act = apply(self.db, self.st, lst, verdict, signal, dry=self.dry, price=price)
        except Exception as e:   # cardb refused (price sanity 422, conflict): log it, keep checking
            act = f"write failed: {e}"[:80]
        self.st.put(lst["id"], last_at=time.time(), verdict=verdict, signal=signal)
        if price is not None:
            signal = f"{signal}; price {lst.get('price')} → {price}"
        self.note(site, lst, verdict, signal, act, prio, price=lv.price if lv else None)

    def site(self, site_id: str, items: list[tuple[int, dict]]) -> None:
        try:
            p = self.plugin(site_id)
        except (KeyError, ImportError) as e:
            self.stop(site_id, f"no plugin: {e}")
            return
        cap = (p.meta.get("pace") or {}).get("max_loads_per_run")
        proxy_cc = (p.meta.get("liveness") or {}).get("proxy_country")
        try:
            for i, (prio, lst) in enumerate(items[:cap] if cap else items):
                if self.over():
                    self.stop(site_id, "time box reached")
                    return
                try:
                    v, sig, lv = self._check(p, lst["url"])
                except PaceExceeded as e:
                    rest = [x for x in items[i:] if x[0] <= 2]
                    if self.proxy_priority and proxy_cc and rest:
                        self.stop(site_id, f"home pace budget used ({e.reason}); {len(rest)} priority via {proxy_cc}")
                        self._via_proxy(p, site_id, rest, proxy_cc)
                    else:
                        self.stop(site_id, f"pace budget used ({e.reason}); {len(items) - i} left for later")
                    return
                self.one(site_id, lst, v, sig, prio, lv)
                if v == "blocked":
                    self.stop(site_id, f"blocked: {sig}")
                    return
        finally:
            p.close()

    def _via_proxy(self, p: base.BaseSite, site_id: str, items: list[tuple[int, dict]], cc: str) -> None:
        for prio, lst in items:
            if self.over():
                return
            try:
                v, sig, lv = self._check(p, lst["url"], country=cc)
            except (PaceExceeded, AccessError) as e:
                self.stop(site_id, f"{cc} route: {e}")
                return
            self.one(site_id, lst, v, f"{cc} {sig}", prio, lv)
            if v == "blocked":
                return

    @staticmethod
    def _check(p: base.BaseSite, url: str, country: str | None = None) -> tuple[str, str, Liveness | None]:
        try:
            lv = p.is_live(url, country=country) if country else p.is_live(url)
        except Blocked as e:
            return "blocked", e.signature, None
        except base.Unsupported as e:
            return "unknown", f"unsupported: {e}"[:80], None
        except PaceExceeded:
            raise
        except Exception as e:   # network error, parse error: unknown, never gone
            return "unknown", f"error {e!r}"[:80], None
        return verdict_of(lv), lv.evidence, lv

    def go(self, by_site: dict[str, list[tuple[int, dict]]]) -> None:
        # one thread per site: different hosts, each paced on its own ledger
        ts = [threading.Thread(target=self.site, args=(s, it), name=s) for s, it in by_site.items() if it]
        for t in ts:
            t.start()
        for t in ts:
            t.join()


def plan(db: DB, st: State, *, sites: list[str] | None = None, cars: list[int] | None = None, daily: bool = False,
         sample: int | None = None, limit: int | None = None, max_prio: int | None = None,
         now: float | None = None) -> tuple[dict[str, list[tuple[int, dict]]], int]:
    """Pick listings per site in priority order. Returns ({site: [(prio, listing)]}, unsupported count)."""
    now = now if now is not None else time.time()
    listings = db.listings("live")
    ours = st.ours()
    if ours:   # removed by this tool: re-check so a relisted ad goes back to live
        listings += [x for x in db.listings("removed") if x["id"] in ours]
    carmap = db.cars()
    if cars:
        listings = [x for x in listings if x["car_id"] in set(cars)]
    by: dict[str, list[tuple[int, dict, float]]] = {}
    unsupported = 0
    known = set(base.ids())
    for x in listings:
        site = x.get("site")
        if site not in known:
            p = base.for_url(x["url"])
            site = p.id if p else None
        if not site:
            unsupported += 1
            continue
        if sites and site not in sites:
            continue
        prio = priority(carmap.get(x["car_id"]))
        if max_prio is not None and prio > max_prio:
            continue
        s = st.get(x["id"])
        if daily:
            due = DUE_S["priority"] if prio <= 2 else DUE_S["normal"]
            if x["status"] == "removed":
                due = DUE_S["removed"]
            if s.get("soft_n"):
                due = DUE_S["soft"]   # 2nd look at a soft "gone"
            if now - (s.get("last_at") or 0) < due:
                continue
        by.setdefault(site, []).append((prio, x, s.get("last_at") or 0))
    out: dict[str, list[tuple[int, dict]]] = {}
    for site, it in by.items():
        if sample:
            random.seed(f"{site}-{time.strftime('%F')}")
            it = random.sample(it, min(sample, len(it)))
        else:
            it.sort(key=lambda t: (t[0], t[2]))
        out[site] = [(p, x) for p, x, _ in (it[:limit] if limit else it)]
    return out, unsupported


def run(*, sites: list[str] | None = None, cars: list[int] | None = None, daily: bool = False,
        sample: int | None = None, limit: int | None = None, max_prio: int | None = None, until: str | None = None,
        dry: bool = False, proxy_priority: bool = False, db: DB | None = None,
        plugin: Callable[[str], base.BaseSite] = base.get) -> dict:
    db = db or connect_db()
    with _core.flock("sites-liveness"):   # one run at a time: two runs would double the site loads
        return _run(db, sites=sites, cars=cars, daily=daily, sample=sample, limit=limit, max_prio=max_prio,
                    until=until, dry=dry, proxy_priority=proxy_priority, plugin=plugin)


def _run(db: DB, *, sites, cars, daily, sample, limit, max_prio, until, dry, proxy_priority, plugin) -> dict:
    st = State(_core.path("sites", "liveness.db"), dry=dry)
    by_site, unsupported = plan(db, st, sites=sites, cars=cars, daily=daily, sample=sample, limit=limit,
                                max_prio=max_prio)
    until_ts = None
    if until:
        h, m = map(int, until.split(":"))
        t = _core.now().replace(hour=h, minute=m, second=0, microsecond=0)
        until_ts = t.timestamp() if t.timestamp() > time.time() else None
    out_path = _core.path("sites", "liveness", f"checks-{time.strftime('%F')}.jsonl")
    with open(out_path, "a") as out:
        r = Run(db, st, dry=dry, until=until_ts, out=out, proxy_priority=proxy_priority, plugin=plugin)
        t0 = time.time()
        r.go(by_site)
    summary = {"at": now_iso(), "dry": dry, "secs": round(time.time() - t0), "sites": r.stats,
               "queued": sum(len(v) for v in by_site.values()), "unsupported": unsupported,
               "mode": "car" if cars else "daily" if daily else "sample" if sample else "manual"}
    with open(_core.path("sites", "liveness", "runs.jsonl"), "a") as f:
        f.write(json.dumps(summary) + "\n")
    summary["results"] = r.results
    return summary


def car_exit(results: list[dict]) -> int:
    """--car exit: 0 = an ad is live · 4 = every checked ad gone · 5 = could not tell (blocked/unknown)."""
    vs = {x["verdict"] for x in results}
    return 0 if "live" in vs else 4 if vs and vs <= {"gone", "gone_soft"} else 5
