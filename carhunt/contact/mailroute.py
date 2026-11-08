"""Keep car mail out of the owner's inbox: car threads get the car label and leave the inbox.

A thread is car mail when a message in it
- already has the car label, or is in a thread we sent from carhunt (ledger `addr#THREAD`), or
- is to the plus-address (Reply-To of our mail, site forms), or
- is from (inbound: From/Reply-To) or to (our sent mail: To/Cc) a known car address or domain.
Known addresses: cardb seller contacts, the ledger's email rows, `contact.mailroute.addresses`.
Known domains: `contact.mailroute.domains` (marketplaces, dealers) + domains of known addresses.
Freemail hosts match by exact address only (one gmail seller must not pull in all gmail).

Matching is by address and thread only, never by words (phrase filters hit non-car mail).
Never marks read, never deletes, touches nothing unmatched.
`contact.mailroute.never_touch` (addresses or domains, e.g. family, work) vetoes a whole thread.
Every move is logged to $CARHUNT_HOME/contact/mailroute.log with its reason.

Run it every 3 min (`launchd_plist`) plus a daily 60-day deep pass.
"""
from __future__ import annotations

import fcntl
import json
import re
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from . import deps
from .channels.email import EMAIL_RE, addrs_in, plus_address, split_to
from .gmail import Gmail, headers_of

WINDOW = "3d"
DEEP_WINDOW = "60d"
THREAD_HEADERS = ("From", "To", "Cc", "Reply-To", "Delivered-To", "Subject")
FREEMAIL = re.compile(r"""^(gmail|googlemail|hotmail|outlook|live|msn|windowslive|yahoo|ymail|rocketmail|icloud|me|mac|
    aol|gmx|web|t-online|freenet|online|arcor|posteo|mail|email|e-mail|orange|wanadoo|free|sfr|neuf|laposte|bbox|club-internet|
    libero|virgilio|tiscali|alice|tin|fastwebnet|inwind|iol|telefonica|movistar|terra|ya|yandex|ukr|rambler|proton|protonmail|
    pm|tutanota|zoho|skynet|telenet|ziggo|kpnmail|hetnet|planet|home|chello|quicknet|xs4all|upcmail|sapo|clix|netcabo|bluewin|
    hispeed|seznam|wp|o2|interia|onet|abv|kabelmail|vodafone|1und1|aon|a1)\.""", re.X)
# Big platforms whose addresses turn up in car records (links, receipts): never derive a domain rule
# from them; only an explicit `domains` entry can route them.
PLATFORM_DOMAINS = {"google.com", "whatsapp.net", "apple.com", "microsoft.com", "facebook.com", "amazon.com",
                    "amazon.de", "amazon.es", "amazon.fr", "amazon.it", "booking.com", "paypal.com"}
NO_DOMAIN_LOCALS = ("noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster")


# -- address helpers ----------------------------------------------------------------------------

def base_domain(host: str) -> str:
    parts = host.lower().strip(".").split(".")
    two_level = len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2
    return ".".join(parts[-3:] if two_level else parts[-2:])


def is_freemail(host: str) -> bool:
    return bool(FREEMAIL.match(base_domain(host)))


def _on_domain(host: str, domains: Iterable[str]) -> str | None:
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


class Rules:
    """Known car addresses/domains + the never-touch veto, for one config."""

    def __init__(self, cfg: dict[str, Any], addrs: Iterable[str] = (), domains: Iterable[str] = ()):
        mr = (cfg.get("contact") or {}).get("mailroute") or {}
        em = (cfg.get("contact") or {}).get("email") or {}
        me = (deps.resolve(em.get("from_address") or "") or "").lower()
        self.me_local, _, self.me_dom = me.partition("@")
        self.plus = plus_address(me, em.get("plus_tag", ""))
        self.label = em.get("label") or "cars"
        self.freemail = {d.lower().lstrip("@.") for d in mr.get("freemail") or []}  # extra freemail/ISP hosts
        never = [str(x).lower().strip() for x in mr.get("never_touch") or []]
        self.never_addrs = {x for x in never if "@" in x}
        self.never_domains = {x.lstrip("@") for x in never if "@" not in x}
        self.addrs = {a for a in (x.lower().strip(".") for x in [*addrs, *(mr.get("addresses") or [])])
                      if "@" in a and not self.is_me(a) and not self.never(a)}
        explicit = {d.lower().lstrip("@.") for d in mr.get("domains") or []}
        derived = {base_domain(a.split("@")[1]) for a in self.addrs
                   if not a.split("@")[0].startswith(NO_DOMAIN_LOCALS)}
        derived = {d for d in derived if not self.free(d) and d not in PLATFORM_DOMAINS}
        self.domains = {d for d in explicit | derived | {x.lower() for x in domains}
                        if d and not self.free(d) and not self.never("x@" + d)}

    def free(self, host: str) -> bool:
        return is_freemail(host) or bool(_on_domain(host.lower(), self.freemail))

    def is_me(self, a: str) -> bool:
        local, _, dom = a.partition("@")
        return bool(self.me_dom) and dom == self.me_dom and local.split("+")[0] == self.me_local.split("+")[0]

    def never(self, a: str) -> bool:
        host = a.split("@")[-1]
        return a in self.never_addrs or bool(_on_domain(host, self.never_domains))

    def hit(self, a: str) -> str | None:
        if a in self.addrs:
            return a
        host = a.split("@")[-1]
        if self.free(host):  # freemail: exact address only
            return None
        return _on_domain(host, self.domains)


# -- known-address sources ----------------------------------------------------------------------

def db_addresses(db: Any) -> set[str]:
    """Email addresses in cardb records of cars we've talked to (seller contacts, notes)."""
    cars = [c for c in db.cars() if c.get("message_count") or c.get("status") not in (None, "new", "to_contact")]
    with ThreadPoolExecutor(6) as ex:
        texts = list(ex.map(lambda c: json.dumps(db.car(c["id"]), ensure_ascii=False), cars))
    return {a.lower().strip(".") for t in texts for a in EMAIL_RE.findall(t)}


def ledger_known(ledger: Any) -> tuple[set[str], set[str]]:
    """(addresses, thread ids) from the ledger's email rows that went out (or may have)."""
    addrs, threads = set(), set()
    for e in ledger.iter() if ledger is not None else ():
        if e.channel != "email" or not e.counts:
            continue
        a, tid = split_to(e.to)
        if a:
            addrs.add(a)
        if tid:
            threads.add(tid)
    return addrs, threads


def known(cfg: dict[str, Any], *, db: Any, ledger: Any,
          db_source: Callable[[Any], Iterable[str]] = db_addresses) -> dict[str, Any]:
    """{'addrs', 'threads', 'db_error'}. On a cardb error the last good set is reused."""
    cache = deps.path("contact", "mailroute-known.json")
    addrs, threads = ledger_known(ledger)
    err = None
    try:
        from_db = set(db_source(db)) if db is not None else set()
        cache.write_text(json.dumps(sorted(from_db)))
    except Exception as e:  # noqa: BLE001 - cardb down must not stop routing known threads
        err = str(e)[:200]
        from_db = set(json.loads(cache.read_text())) if cache.exists() else set()
    return {"addrs": addrs | from_db, "threads": threads, "db_error": err}


# -- routing ------------------------------------------------------------------------------------

def _days(window: str | int) -> str:
    w = f"{window}d" if isinstance(window, int) else str(window).strip()
    if not re.fullmatch(r"\d+[dmy]", w):  # Gmail newer_than: has d/m/y only, no hours or minutes
        raise ValueError(f"window {window!r}: use Nd, Nm or Ny")
    return w


def why_car(msgs: list[dict], rules: Rules, label_id: str | None, threads: set[str]) -> str | None:
    """Reason this thread is car mail, or None. Address/thread evidence only."""
    for m in msgs:
        if m.get("threadId") in threads:
            return "known thread"
        if label_id and label_id in m.get("labelIds", []):
            return "thread already labelled"
        h = headers_of(m)
        if rules.plus and rules.plus in addrs_in(" ".join(h.get(k, "") for k in ("to", "cc", "delivered-to"))):
            return "to plus-address"
        sent = "SENT" in m.get("labelIds", [])
        fields = ("to", "cc") if sent else ("from", "reply-to")
        for a in addrs_in(" ".join(h.get(k, "") for k in fields)):
            hit = rules.hit(a)
            if hit:
                return ("sent to " if sent else "from ") + hit
    return None


def vetoed(msgs: list[dict], rules: Rules) -> str | None:
    for m in msgs:
        h = headers_of(m)
        for a in addrs_in(" ".join(h.get(k, "") for k in ("from", "to", "cc", "reply-to"))):
            if rules.never(a):
                return a
    return None


def _lock() -> Any:
    fh = open(deps.path("locks", "mailroute.lock"), "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def run_once(cfg: dict[str, Any], *, gmail: Gmail, db: Any = None, ledger: Any = None, window: str | int = WINDOW,
             dry_run: bool = False, known_set: dict[str, Any] | None = None) -> dict[str, Any]:
    """One pass over inbox threads newer than `window`. Deep pass: window=DEEP_WINDOW.

    Returns {window, threads_checked, threads_moved, moved, tagged_sent, vetoed, addresses, domains,
    dry_run, db_error, moves: [{thread, why, ids, from, subject}]} or {skipped: reason}."""
    w = _days(window)
    lock = _lock()
    if lock is None:
        return {"skipped": "another mailroute pass is running"}
    try:
        k = known_set or known(cfg, db=db, ledger=ledger)
        rules = Rules(cfg, k["addrs"])
        label_id = gmail.label_id(rules.label, create=not dry_run)
        # in:inbox is right here: the router acts on the inbox. Agent searches never use it.
        tids = [t["id"] for t in gmail.list_threads(f"in:inbox newer_than:{w}")]
        with ThreadPoolExecutor(6) as ex:
            threads = dict(zip(tids, ex.map(
                lambda t: gmail.get_thread(t, fmt="metadata", headers=THREAD_HEADERS).get("messages", []), tids)))
        move: list[str] = []
        tag: list[str] = []
        moves: list[dict[str, Any]] = []
        n_veto = 0
        for tid, msgs in threads.items():
            why = why_car(msgs, rules, label_id, k.get("threads") or set())
            if not why:
                continue
            if vetoed(msgs, rules):
                n_veto += 1
                continue
            ids = [m["id"] for m in msgs if "INBOX" in m.get("labelIds", [])]
            tag += [m["id"] for m in msgs if "SENT" in m.get("labelIds", []) and label_id not in m.get("labelIds", [])]
            if ids:
                h = headers_of(msgs[-1])
                move += ids
                moves.append({"thread": tid, "why": why, "ids": ids, "from": h.get("from", "")[:80],
                              "subject": h.get("subject", "")[:100]})
        if not dry_run and label_id:
            # Only ever remove INBOX: never UNREAD (stays unread for the owner), never TRASH.
            if move:
                gmail.batch_modify(move, add=[label_id], remove=["INBOX"])
            if tag:
                gmail.batch_modify(tag, add=[label_id])
            if moves:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                with open(deps.path("contact", "mailroute.log"), "a", encoding="utf-8") as f:
                    for mv in moves:
                        f.write(f"{stamp} | {mv['thread']} | {len(mv['ids'])} msg | {mv['from']} | "
                                f"{mv['subject']} | {mv['why']}\n")
        return {"window": w, "threads_checked": len(threads), "threads_moved": len(moves), "moved": len(move),
                "tagged_sent": len(tag), "vetoed": n_veto, "addresses": len(rules.addrs),
                "domains": len(rules.domains), "dry_run": dry_run, "db_error": k.get("db_error"), "moves": moves}
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


# -- Gmail filters (UI import) --------------------------------------------------------------------

def filters_xml(cfg: dict[str, Any], known_addresses: Iterable[str] = (), *, max_chars: int = 1000) -> str:
    """Gmail filter XML: to:<plus-address> and from:(domains, freemail addresses) → label + skip inbox.

    Import in Gmail: Settings → Filters and Blocked Addresses → Import filters, leave "apply to
    existing" unticked (mailroute already swept). Not via the API: creating filters needs the
    `gmail.settings.basic` scope, which the send/modify token doesn't have (re-auth required).
    Filters act at delivery, so car mail never shows in the inbox; mailroute catches the rest."""
    rules = Rules(cfg, known_addresses)
    terms = sorted(rules.domains) + sorted(a for a in rules.addrs if not _on_domain(a.split("@")[1], rules.domains))
    groups: list[list[str]] = [[]]
    for t in terms:
        if groups[-1] and len(" OR ".join(groups[-1] + [t])) > max_chars:
            groups.append([])
        groups[-1].append(t)

    def entry(props: list[tuple[str, str]]) -> str:
        body = "".join(f"<apps:property name={quoteattr(k)} value={quoteattr(v)}/>" for k, v in props)
        return (f"<entry><category term='filter'></category><title>Mail Filter</title><content></content>"
                f"{body}</entry>")

    action = [("label", rules.label), ("shouldArchive", "true")]
    entries = [entry([("to", rules.plus)] + action)] if rules.plus else []
    entries += [entry([("hasTheWord", "from:(" + " OR ".join(g) + ")")] + action) for g in groups if g]
    return ("<?xml version='1.0' encoding='UTF-8'?><feed xmlns='http://www.w3.org/2005/Atom' "
            "xmlns:apps='http://schemas.google.com/apps/2006'><title>Mail Filters</title>"
            + "\n".join(entries) + "</feed>\n")


# -- launchd --------------------------------------------------------------------------------------

TEMPLATE = Path(__file__).parent / "templates" / "launchd-mailroute.plist"


def launchd_plist(cfg: dict[str, Any], interval_s: int = 180, *, deep: bool = False,
                  carhunt_bin: str | None = None) -> str:
    """launchd job running `carhunt mailroute` every `interval_s` (label com.carhunt.mailroute), or
    with deep=True the daily 60-day pass at `contact.mailroute.deep_at` (default 04:10)."""
    mr = (cfg.get("contact") or {}).get("mailroute") or {}
    exe = carhunt_bin or shutil.which("carhunt") or str(Path(sys.executable).with_name("carhunt"))
    args = [exe, "mailroute", *(["--deep"] if deep else []), "--quiet"]
    if deep:
        hh, mm = (int(x) for x in str(mr.get("deep_at", "04:10")).split(":"))
        schedule = (f"<key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hh}</integer>"
                    f"<key>Minute</key><integer>{mm}</integer></dict>")
    else:
        schedule = f"<key>StartInterval</key><integer>{int(interval_s)}</integer><key>RunAtLoad</key><true/>"
    label = "com.carhunt.mailroute" + ("-deep" if deep else "")
    logs = deps.path("logs", "x").parent
    return TEMPLATE.read_text().format(
        label=escape(label),
        program_args="\n".join(f"    <string>{escape(a)}</string>" for a in args),
        carhunt_home=escape(str(deps.home())),
        path=escape(f"{Path(exe).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"),
        schedule="  " + schedule,
        stdout=escape(str(logs / f"{label.split('.')[-1]}.out")),
        stderr=escape(str(logs / f"{label.split('.')[-1]}.err")),
    )
