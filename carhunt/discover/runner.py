"""The sweep: enabled sites, one at a time → search → cursor → scope → detail read → normalize → cardb.

Rules:
- Serial: one site at a time, one sweep per machine (lock `sweep`) — parallel workers on one IP get sites banned.
- Sends before reads: a site with `pace.read_after` (sellers are messaged there) is read only after that local time,
  so discovery reads don't get the messaging IP blocked.
- Per-site load budget = min(site.yaml `pace.max_loads_per_run`, `discover.max_loads_per_site`, default 60).
- Stop a site at its first block (`Blocked`), record the signature, go on with the next site; an ad that is gone
  (`Gone`, 404/410) is skipped, never a block.
- Focus families (tiers in `discover.detail_tiers`) get a detail read + full gallery; the rest are card-only:
  market picture without spending the load budget.
- Scope prefilter on the search card before any detail load; every drop is logged with its reason.
- Cardb lookups go by URL (cardb derives its own ad id from the URL); in-run dedupe and the price memory go by the
  card's `site_ref` (the site's data id), which on standvirtual / olx.pt differs from the URL token.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from carhunt.access.errors import Blocked, PaceExceeded, ProxyUnavailable
from carhunt.discover import _env, heuristics, normalize, quality, scope
from carhunt.discover.cursor import Cursor, Store, strategy_for
from carhunt.discover.distance import Geo, place_of
from carhunt.discover.ingest import Ingest
from carhunt.sites import base as sites
from carhunt.sites.base import Gone, Unsupported
from carhunt.sites.model import Card, SearchQuery

DEFAULT_LOADS = 60
DEFAULT_PAGES = 5


class BudgetSpent(Exception):
    pass


class RunCapReached(Exception):
    pass


@dataclass
class SiteResult:
    site: str
    state: str = "pending"          # ok | blocked | pace | budget | deferred | unsupported | max | error
    detail: str = ""
    loads: int = 0
    cards: int = 0
    new: int = 0
    linked: int = 0
    updated: int = 0
    unchanged: int = 0
    gone: int = 0
    rejected: int = 0
    price_held: int = 0             # stored without price: cardb refused the ask (x100 / range / net) → check the ad
    dropped: Counter = field(default_factory=Counter)
    queries_done: int = 0
    queries: int = 0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["dropped"] = dict(self.dropped)
        return d


@dataclass
class Plan:
    site: str
    meta: dict
    run: bool
    why: str = ""


def _hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def _before(now: datetime, hhmm: str) -> bool:
    return (now.hour, now.minute) < _hhmm(hhmm)


def window_now(cfg: dict, now: datetime) -> str | None:
    for name, span in ((cfg.get("discover") or {}).get("windows") or {}).items():
        a, b = span.split("-")
        if _hhmm(a) <= (now.hour, now.minute) < _hhmm(b):
            return name
    return None


def plan(cfg: dict, *, only: list[str] | None = None, window: str | None = None,
         now: datetime | None = None) -> list[Plan]:
    """Which sites run now and why the others don't."""
    now = now or _env.now()
    metas = sites.metas()
    enabled = (cfg.get("sites") or {}).get("enabled") or list(metas)
    wanted = only or enabled
    out = []
    for sid in wanted:
        meta = metas.get(sid)
        if meta is None:
            out.append(Plan(sid, {}, False, "no plugin registered"))
            continue
        read_after = (meta.get("pace") or {}).get("read_after")
        if window == "morning" and read_after:
            out.append(Plan(sid, meta, False, f"messaging site: afternoon window only (reads after {read_after})"))
        elif read_after and _before(now, read_after):
            out.append(Plan(sid, meta, False, f"sends first: reads after {read_after} local"))
        else:
            out.append(Plan(sid, meta, True))
    return out


def queries(meta: dict, cfg: dict, strategy: str) -> list[tuple[SearchQuery, scope.Model]]:
    search = cfg.get("search") or {}
    disc = cfg.get("discover") or {}
    home = ((cfg.get("owner") or {}).get("home") or {}).get("country")
    wanted = [c.upper() for c in search.get("countries") or []]
    site_countries = meta.get("countries") or [None]
    countries = [c for c in site_countries if not wanted or c is None or c in wanted]
    fuels = [f.lower() for f in search.get("powertrain") or []]
    price = search.get("price") or {}
    out = []
    for m in scope.models(search):
        for c in countries:
            seller = "dealer" if (search.get("private_sellers_abroad") is False and c and home and c != home) else "any"
            q = SearchQuery(make=m.make, model=m.model, country=c, price_max=price.get("max_eur"),
                            price_min=price.get("min_eur"), year_min=search.get("year_min"), km_max=search.get("km_max"),
                            fuel=fuels[0] if len(fuels) == 1 else None, seller=seller,
                            sort="relevance" if strategy == "full" else "newest",
                            max_pages=int(disc.get("max_pages") or DEFAULT_PAGES))
            out.append((q, m))
    return out


def query_key(q: SearchQuery) -> str:
    return f"{q.country or '*'}|{q.make}|{q.model}|{q.seller}"


def _ref(card: Card) -> str:
    """Dedupe / price-memory key: the site's data id, else the URL."""
    return f"{card.site}:{card.site_ref}" if card.site_ref else card.url


class Sweep:
    def __init__(self, cfg: dict, db: Any, *, dry_run: bool = False, max_new: int | None = None,
                 geo: Geo | None = None, site_factory: Callable[[str], Any] | None = None,
                 log: Callable[[str], None] | None = None, now: Callable[[], datetime] | None = None):
        self.cfg, self.dry_run, self.max_new = cfg, dry_run, max_new
        self.disc = cfg.get("discover") or {}
        self.ingest = Ingest(db, dry_run=dry_run, max_photos=int(self.disc.get("max_photos") or 40))
        self.geo = geo or Geo(cfg)
        self.site_factory = site_factory or sites.get
        self.log = log or (lambda s: None)
        self.now = now or _env.now
        self.store = Store(_env.path("discover", "cursors.json"))
        self.seen_path = _env.path("discover", "seen.json")     # site:site_ref → the site's own ask at the last sweep
        self.seen: dict[str, int | None] = json.loads(self.seen_path.read_text()) if self.seen_path.exists() else {}
        self.created = 0
        self.writes: list[dict] = []        # dry-run payloads / write results, for the report
        self.detail_tiers = self.disc.get("detail_tiers")   # None = every tier gets detail reads

    # --- bookkeeping ------------------------------------------------------------
    def _disposition(self, res: SiteResult, url: str, reason: str, *, count: bool = True) -> None:
        if count:
            res.dropped[reason.split(":")[0]] += 1
        rec = {"at": self.now().isoformat(timespec="seconds"), "site": res.site, "url": url, "reason": reason}
        if not self.dry_run:
            with open(_env.path("discover", "dispositions.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _budget(self, meta: dict) -> int:
        site_cap = (meta.get("pace") or {}).get("max_loads_per_run")
        mine = int(self.disc.get("max_loads_per_site") or DEFAULT_LOADS)
        return min(mine, int(site_cap)) if site_cap else mine

    @staticmethod
    def _loads(site: Any) -> int:
        return int(getattr(getattr(site, "net", None), "loads", 0) or 0)

    # --- one site ---------------------------------------------------------------
    def run_site(self, sid: str, meta: dict) -> SiteResult:
        res = SiteResult(sid)
        try:
            site = self.site_factory(sid)
        except Exception as e:  # noqa: BLE001 - one broken plugin must not stop the sweep
            res.state, res.detail = "error", f"plugin: {type(e).__name__}: {e}"
            return res
        budget = self._budget(meta)
        strategy = strategy_for(meta, self.disc)
        qs = queries(meta, self.cfg, strategy)
        res.queries = len(qs)
        try:
            for q, model in qs:
                self._run_query(site, res, q, model, strategy, budget)
                res.queries_done += 1
            res.state = "ok"
        except Blocked as e:
            res.state, res.detail = "blocked", f"{e.signature}" + (f" at {e.url}" if e.url else "")
        except PaceExceeded as e:
            res.state, res.detail = "pace", str(e)
        except ProxyUnavailable as e:
            res.state, res.detail = "blocked", f"proxy: {e}"
        except BudgetSpent:
            res.state, res.detail = "budget", f"{budget} loads"
        except RunCapReached:
            res.state, res.detail = "max", f"--max {self.max_new} new listings reached"
        except Unsupported as e:
            res.state, res.detail = "unsupported", str(e)
        finally:
            res.loads = self._loads(site)
            if not self.dry_run:
                self.seen_path.write_text(json.dumps(self.seen, indent=0, sort_keys=True))
            try:
                site.close()
            except Exception:  # noqa: BLE001
                pass
        return res

    def _run_query(self, site: Any, res: SiteResult, q: SearchQuery, model: scope.Model, strategy: str,
                   budget: int) -> None:
        key = query_key(q)
        cur = Cursor(strategy, self.store.get(res.site, key), eligible=lambda c: self._in_filter(c, q))
        seen: set[str] = set()
        for card in site.search(q):
            if self._loads(site) > budget:
                raise BudgetSpent()
            res.cards += 1
            if cur.stop(card):
                break
            cur.observe(card)
            if _ref(card) in seen:
                continue
            seen.add(_ref(card))
            self._card(site, res, card, model, budget)
        if not self.dry_run:
            self.store.put(res.site, key, cur.committed(self.now().isoformat(timespec="seconds")))

    @staticmethod
    def _in_filter(card: Card, q: SearchQuery) -> bool:
        """Organic rows inside the query's own filter may set a cursor; promoted rows can violate filters."""
        if q.price_max and card.price and not card.price_is_net and card.price > q.price_max:
            return False
        if q.km_max and card.km and card.km > q.km_max:
            return False
        return not (q.year_min and card.year and card.year < q.year_min)

    def _card(self, site: Any, res: SiteResult, card: Card, model: scope.Model, budget: int) -> None:
        lst = normalize.from_card(card)
        why = scope.check(lst, self.cfg, partial=True)
        if why:
            self._disposition(res, card.url, why)
            return
        existing = self.ingest.known(card.url)
        if existing:
            last = self.seen.get(_ref(card))
            changed = last is not None and card.price is not None and card.price != last
            if changed and (self.detail_tiers is None or (lst.tier or model.tier) in self.detail_tiers):
                try:
                    lst = normalize.from_ad(site.ad(card.url))      # derive the stored price the same way
                except Gone as e:
                    res.gone += 1
                    self._disposition(res, card.url, f"gone: {e.evidence}")
                    return
            r = self.ingest.sighting(lst, existing, price_changed=changed)
            self._count(res, r)
            if r.action == "rejected":
                self._disposition(res, card.url, f"cardb_rejected: {r.reason}", count=False)
            self.seen[_ref(card)] = card.price
            return
        if self.max_new is not None and self.created >= self.max_new:
            raise RunCapReached()
        detail = self.detail_tiers is None or (lst.tier or model.tier) in self.detail_tiers
        if detail:
            if self._loads(site) >= budget:
                raise BudgetSpent()
            try:
                ad = site.ad(card.url)
            except Gone as e:
                res.gone += 1
                self._disposition(res, card.url, f"gone: {e.evidence}")
                return
            lst = normalize.from_ad(ad)
            if not lst.country:
                lst.country = (card.country or "").upper() or None
        heuristics.apply(lst, self.cfg)
        self._locate(lst)
        why = scope.check(lst, self.cfg)
        if why:
            self._disposition(res, card.url, why)
            return
        quality.assess(lst, self.cfg)
        r = self.ingest.write(lst)
        self._count(res, r)
        if r.action == "rejected" or (r.reason and "price held" in r.reason):
            self._disposition(res, card.url, f"cardb_rejected: {r.reason}", count=False)
        if r.reason and "price held" in r.reason:
            res.price_held += 1
        if r.action in ("created", "linked", "updated"):
            self.seen[_ref(card)] = card.price
        if r.action in ("created", "linked", "would_create"):
            self.created += 1
        self.writes.append({**r.to_dict(), "summary": lst.summary()} if not self.dry_run
                           else {"action": r.action, "url": r.url, "summary": lst.summary(), "upsert": r.payload})

    def _locate(self, lst: normalize.Listing) -> None:
        if lst.lat is not None or not lst.city:
            return
        ll = self.geo.geocode(place_of(lst.city, lst.country), offline=self.dry_run)
        if not ll:
            return
        lst.lat, lst.lon = ll
        km, how = self.geo.km(*ll)
        if how == "road":
            lst.distance_km = km            # real road km → stored; else cardb estimates from lat/lon
        lst.distance_est_km = km

    @staticmethod
    def _count(res: SiteResult, r: Any) -> None:
        a = r.action
        if a in ("created", "would_create"):
            res.new += 1
        elif a == "linked":
            res.linked += 1
        elif a in ("updated", "would_update"):
            res.updated += 1
        elif a == "unchanged":
            res.unchanged += 1
        elif a == "rejected":
            res.rejected += 1
            res.dropped[f"cardb_rejected {r.reason or ''}".strip()] += 1

    # --- whole run ---------------------------------------------------------------
    def run(self, plans: list[Plan]) -> dict:
        started = self.now()
        results: list[SiteResult] = []
        for p in plans:
            if not p.run:
                results.append(SiteResult(p.site, state="deferred", detail=p.why))
                self.log(f"{p.site}: deferred ({p.why})")
                continue
            if self.max_new is not None and self.created >= self.max_new:
                results.append(SiteResult(p.site, state="max", detail="run cap reached before this site"))
                continue
            self.log(f"{p.site}: sweeping")
            r = self.run_site(p.site, p.meta)
            self.log(f"{p.site}: {r.state} new={r.new} updated={r.updated} unchanged={r.unchanged} "
                     f"dropped={sum(r.dropped.values())} loads={r.loads} {r.detail}".rstrip())
            results.append(r)
        report = {"started": started.isoformat(timespec="seconds"), "finished": self.now().isoformat(timespec="seconds"),
                  "dry_run": self.dry_run, "sites": [r.to_dict() for r in results], "writes": self.writes}
        if not self.dry_run:
            stamp = started.strftime("%Y%m%dT%H%M%S")
            _env.path("discover", "runs", f"{stamp}.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
        return report
