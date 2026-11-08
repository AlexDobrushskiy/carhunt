"""CLI groups owned by contact: say, watch, mailroute, ledger, asks.

`register(subparsers)` is auto-discovered by carhunt/cli.py (core). `python -m carhunt.contact`
runs the same groups standalone (used by tests and before core lands).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import guard


def _say(a: argparse.Namespace) -> int:
    from . import say

    if a.nudge and (a.opener or a.approved):
        print("REFUSED [mode]: --nudge can't be combined with --opener/--approved", file=sys.stderr)
        return say.EXIT_REFUSED
    if a.opener and a.approved:
        print("REFUSED [mode]: --opener can't be combined with --approved", file=sys.stderr)
        return say.EXIT_REFUSED
    if a.text_file:
        text = sys.stdin.read() if a.text_file == "-" else open(a.text_file, encoding="utf-8").read()
    else:
        text = a.text or ""
    mode = guard.OPENER if a.opener else guard.NUDGE if a.nudge else guard.APPROVED if a.approved else guard.REPLY
    opts = {k: v for k, v in (("subject", a.subject), ("new_thread", a.new_thread or None),
                              ("attach", a.attach or None)) if v}
    o = say.run(channel=a.channel, text=text, car=a.car, to=a.to, mode=mode, dry_run=a.dry_run,
                use_db=not a.no_db, channel_opts=opts)
    say.print_outcome(o, a.json, a.dry_run)
    return o.code


def _watch(a: argparse.Namespace) -> int:
    from . import watch

    return watch.run(a)


def _mailroute(a: argparse.Namespace) -> int:
    from . import deps, mailroute
    from .gmail import Gmail
    from .ledger import Ledger

    cfg = deps.load_config()
    if a.filters:
        k = mailroute.known(cfg, db=deps.Cardb.from_config(cfg), ledger=Ledger())
        print(mailroute.filters_xml(cfg, sorted(k["addrs"])))
        return 0
    if a.launchd:
        print(mailroute.launchd_plist(cfg, deep=a.deep))
        return 0

    res = mailroute.run_once(cfg, gmail=Gmail.from_config(cfg), db=deps.Cardb.from_config(cfg), ledger=Ledger(),
                             window=a.window, dry_run=a.dry_run)
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _ledger(a: argparse.Namespace) -> int:
    from . import deps
    from .ledger import Ledger, reconcile

    led = Ledger()
    if a.ledger_cmd == "reconcile":
        cfg = deps.load_config()
        print(json.dumps(reconcile(led, deps.Cardb.from_config(cfg), since=a.since)))
        return 0
    rows = led.entries()[-a.limit:]
    for e in rows:
        if a.json:
            print(json.dumps(e.__dict__, ensure_ascii=False))
        else:
            print(f"{e.at:%Y-%m-%d %H:%M:%S}Z {e.status:<7} {e.kind:<8} {e.channel:<14} car={e.car or '-':<6} "
                  f"{e.to[:28]:<28} {e.text[:50]!r}")
    return 0


def _asks(a: argparse.Namespace) -> int:
    from . import asks, deps

    if a.asks_cmd == "close" and not (a.car and (a.ask_id or a.topic)):
        print("asks close needs --car and --ask-id or --topic", file=sys.stderr)
        return 2
    db = deps.Cardb.from_config(deps.load_config())
    if a.asks_cmd == "close":
        try:
            ev = asks.close(db, a.car, ask_id=a.ask_id, topic=a.topic, answer=a.answer, record_fact=not a.no_fact)
        except LookupError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(json.dumps(ev, ensure_ascii=False))
        return 0
    rows = asks.open_asks(db, a.car) if a.car else asks.open_asks_all(db)
    for r in rows:
        print(json.dumps(r, ensure_ascii=False))
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("say", help="guarded send to a seller (exit 0 sent, 10 refused, 11 failed, 12 unknown)")
    p.add_argument("--channel", required=True, help="whatsapp | email | <site>")
    p.add_argument("--car", help="cardb car id/alias or ad URL")
    p.add_argument("--to", help="phone / email / ad URL (default: the car's contact for this channel)")
    t = p.add_mutually_exclusive_group(required=True)
    t.add_argument("--text")
    t.add_argument("--text-file", help="file with the message, '-' = stdin")
    p.add_argument("--opener", action="store_true", help="first message in this thread")
    p.add_argument("--nudge", action="store_true", help="the one follow-up after our unanswered message")
    p.add_argument("--approved", action="store_true", help="owner approved this exact text")
    p.add_argument("--dry-run", action="store_true", help="guard decision + payload; nothing leaves the machine")
    p.add_argument("--subject", help="email: subject for a new thread")
    p.add_argument("--new-thread", action="store_true", help="email: start a new thread")
    p.add_argument("--attach", action="append", help="email: file to attach (repeatable)")
    p.add_argument("--no-db", action="store_true", help="don't use cardb (tests)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_say, _parser=p)

    p = sub.add_parser("watch", help="watch WhatsApp/Gmail/site inboxes; new seller messages → cardb + inbox + stdout")
    p.add_argument("--channels", help="comma list (default contact.watch.channels)")
    p.add_argument("--agent", help="agent inbox to write (default $CARHUNT_AGENT or outreach)")
    p.add_argument("--once", action="store_true", help="one pass, then exit")
    p.add_argument("--until-new", action="store_true", help="block until at least one new message, then exit 0")
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--no-db", action="store_true")
    p.set_defaults(func=_watch, _parser=p)

    p = sub.add_parser("mailroute", help="move car mail out of the inbox (address/domain/thread only)")
    p.add_argument("--window", default="3d", help="search window, e.g. 3d or 60d")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--filters", action="store_true", help="print Gmail filter XML for import")
    p.add_argument("--launchd", action="store_true", help="print a launchd plist (every 3 min)")
    p.add_argument("--deep", action="store_true", help="with --launchd: the daily 60-day pass")
    p.set_defaults(func=_mailroute, _parser=p)

    p = sub.add_parser("ledger", help="show the send ledger / reconcile it into cardb")
    p.add_argument("ledger_cmd", nargs="?", choices=["show", "reconcile"], default="show")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--since", type=float, default=0.0, help="unix time (reconcile)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_ledger, _parser=p)

    p = sub.add_parser("asks", help="open vet asks (cardb ask events) / close one")
    p.add_argument("asks_cmd", nargs="?", choices=["list", "close"], default="list")
    p.add_argument("--car")
    p.add_argument("--ask-id", help="close this ask event")
    p.add_argument("--topic", help="close the oldest open ask of this topic (vet's data.topic)")
    p.add_argument("--answer", default="", help="the seller's answer, short (or 'refused: …'); fills the ask's fact")
    p.add_argument("--no-fact", action="store_true", help="close without writing the ask's fact")
    p.set_defaults(func=_asks, _parser=p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="carhunt")
    sub = ap.add_subparsers(dest="group", required=True)
    register(sub)
    a = ap.parse_args(argv)
    return int(a.func(a) or 0)
