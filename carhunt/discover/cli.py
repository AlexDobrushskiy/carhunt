"""`carhunt sweep [--sites a,b] [--window morning|afternoon] [--dry-run] [--max N] [--json]`.

Exit codes: 0 every planned site finished · 1 error · 3 at least one site blocked / out of budget / capped by pace ·
10 refused (PAUSE file, or another sweep holds the lock).
"""
from __future__ import annotations

import argparse
import fcntl
import json
import sys
from typing import Any

from carhunt.discover import _env


def register(sub: Any) -> None:
    p = sub.add_parser("sweep", help="find new listings on the enabled sites and store them in cardb",
                       description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sites", help="comma list of site ids (default: config sites.enabled)")
    p.add_argument("--window", choices=["morning", "afternoon"],
                   help="morning = sites without pace.read_after only; default: by clock")
    p.add_argument("--dry-run", action="store_true", help="read sites, print what would be upserted, write nothing")
    p.add_argument("--max", type=int, metavar="N", help="stop after N new listings")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.set_defaults(func=run, _parser=p)


def _table(report: dict) -> str:
    rows = [("site", "state", "loads", "new", "linked", "upd", "same", "gone", "dropped", "detail")]
    for s in report["sites"]:
        dropped = ", ".join(f"{k}:{v}" for k, v in sorted(s["dropped"].items())) or "-"
        rows.append((s["site"], s["state"], str(s["loads"]), str(s["new"]), str(s["linked"]), str(s["updated"]),
                     str(s["unchanged"]), str(s["gone"]), dropped, s["detail"] or ""))
    w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]) - 1)]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r[:-1])) + "  " + r[-1] for r in rows)


def run(args: argparse.Namespace) -> int:
    from carhunt.discover import runner

    cfg = _env.config()
    if _env.pause_file().exists() and not args.dry_run:
        print("sweep refused: PAUSE file present (carhunt unpause)", file=sys.stderr)
        return 10
    only = [s.strip() for s in args.sites.split(",")] if args.sites else None
    lock_path = _env.path("locks", "sweep.lock")
    with open(lock_path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("sweep refused: another sweep is running (one sweep per IP)", file=sys.stderr)
            return 10
        now = _env.now()
        window = args.window or runner.window_now(cfg, now)
        plans = runner.plan(cfg, only=only, window=window, now=now)
        db = _env.db_client()
        sweep = runner.Sweep(cfg, db, dry_run=args.dry_run, max_new=args.max,
                             log=lambda m: print(f"sweep: {m}", file=sys.stderr))
        report = sweep.run(plans)
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        print(_table(report))
        if args.dry_run:
            for w in report["writes"]:
                print(json.dumps({"action": w["action"], "upsert": w.get("upsert")}, ensure_ascii=False))
    states = {s["state"] for s in report["sites"]}
    if "error" in states:
        return 1
    return 3 if states & {"blocked", "budget", "pace"} else 0
