"""CLI groups `site` and `liveness`. Output: JSON lines on stdout, progress on stderr.

Exit codes (site): 0 ok · 2 blocked / pace exceeded (stop this site) · 3 ad gone · 4 unsupported here.
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from string import Template

from carhunt.access.errors import AccessError, Blocked, PaceExceeded
from carhunt.sites import base
from carhunt.sites.model import SearchQuery

EXIT_BLOCKED, EXIT_GONE, EXIT_UNSUPPORTED = 2, 3, 4


def _out(d: dict) -> None:
    print(json.dumps(d, ensure_ascii=False), flush=True)


def register(sub) -> None:
    _site(sub)
    _liveness(sub)


# --- site -----------------------------------------------------------------------

def _site(sub) -> None:
    p = sub.add_parser("site", help="read one marketplace: search / ad / phone / live (JSON lines)",
                       description="Read one marketplace through its plugin. Reads only; never logs in or sends.")
    p.set_defaults(_parser=p)
    p.add_argument("site_id", nargs="?", help="site id (`carhunt site list`)")
    p.add_argument("action", nargs="?", choices=["search", "ad", "phone", "live", "info"])
    p.add_argument("urls", nargs="*", help="ad URLs (ad/phone/live)")
    q = p.add_argument_group("search")
    q.add_argument("--make")
    q.add_argument("--model")
    q.add_argument("--country", help="ISO-2: domain/market on multi-country sites")
    q.add_argument("--lang", help="language mirror (marktplaats BE: fr = 2ememain)")
    q.add_argument("--price-min", type=int)
    q.add_argument("--price-max", type=int)
    q.add_argument("--year-min", type=int)
    q.add_argument("--year-max", type=int)
    q.add_argument("--km-max", type=int)
    q.add_argument("--fuel", help="bev | phev | hev | petrol | diesel")
    q.add_argument("--seller", choices=["private", "dealer", "any"], default="any")
    q.add_argument("--sort", choices=["newest", "price", "relevance"], default="newest")
    q.add_argument("--pages", type=int, default=1)
    q.add_argument("--max", type=int, help="stop after N cards")
    q.add_argument("--extra", action="append", default=[], metavar="K=V", help="raw site query param")
    p.add_argument("--reveal", action="store_true", help="phone: allow the site's phone endpoint (pace kind phone)")
    p.add_argument("--raw", action="store_true", help="ad: include the site's raw JSON")
    p.add_argument("--dry-run", action="store_true", help="reads only: refuses --reveal")
    p.set_defaults(func=cmd_site)


def cmd_site(a) -> int:
    if a.site_id in (None, "list") or a.action is None:
        for sid, m in sorted(base.metas().items()):
            _out({"site": sid, "name": m.get("name"), "countries": m.get("countries"), "wall": m.get("wall"),
                  "route": m.get("route"), "country_ip": m.get("country_ip"), "phone": m.get("phone"),
                  "measured": m.get("measured")})
        return 0
    try:
        s = base.get(a.site_id)
    except KeyError as e:
        print(f"carhunt: {e.args[0]}", file=sys.stderr)
        return 1
    if a.reveal and a.dry_run:
        print("carhunt: --dry-run reads only: no phone reveal", file=sys.stderr)
        return 1
    try:
        if a.action == "info":
            _out(s.meta)
        elif a.action == "search":
            if a.urls:
                print("carhunt: search takes filters, not URLs", file=sys.stderr)
                return 1
            q = SearchQuery(make=a.make, model=a.model, country=a.country, lang=a.lang, price_min=a.price_min,
                            price_max=a.price_max, year_min=a.year_min, year_max=a.year_max, km_max=a.km_max,
                            fuel=a.fuel, seller=a.seller, sort=a.sort, max_pages=a.pages,
                            extra=dict(kv.split("=", 1) for kv in a.extra))
            for i, c in enumerate(s.search(q)):
                if a.max and i >= a.max:
                    break
                _out(c.to_dict())
        else:
            if not a.urls:
                print(f"carhunt: {a.action} needs ad URLs", file=sys.stderr)
                return 1
            gone = 0
            for u in a.urls:
                try:
                    if a.action == "ad":
                        _out(s.ad(u).to_dict(raw=a.raw))
                    elif a.action == "phone":
                        ad = s.ad(u)
                        _out({"url": u, "phones": s.phone(ad, reveal=a.reveal)})
                    else:
                        _out({"url": u, **s.is_live(u).to_dict()})
                except base.Gone as e:
                    gone += 1
                    _out({"url": u, "gone": e.evidence})
            if gone == len(a.urls):
                return EXIT_GONE
    except Blocked as e:
        _out({"site": s.id, "blocked": e.signature, "url": e.url})
        return EXIT_BLOCKED
    except PaceExceeded as e:
        _out({"site": s.id, "pace": e.reason, "retry_at": e.retry_at.isoformat() if e.retry_at else None})
        return EXIT_BLOCKED
    except AccessError as e:
        _out({"site": s.id, "access": str(e)})
        return EXIT_BLOCKED
    except base.Unsupported as e:
        print(f"carhunt: {e}", file=sys.stderr)
        return EXIT_UNSUPPORTED
    finally:
        s.close()
    return 0


# --- liveness -------------------------------------------------------------------

def _liveness(sub) -> None:
    p = sub.add_parser("liveness", help="mark cardb listings whose ads are gone (read-only on sites)",
                       description="Check live cardb listings; gone ads → listing removed + ad_check event.")
    p.set_defaults(_parser=p, func=cmd_liveness)
    p.add_argument("--site", action="append", help="site id (repeatable)")
    p.add_argument("--car", action="append", type=int, help="car id (repeatable): check its listings now")
    p.add_argument("--daily", action="store_true", help="due listings only (≥36 h; priority cars ≥20 h)")
    p.add_argument("--sample", type=int, help="N random listings per site (with --dry-run: ground truth)")
    p.add_argument("--limit", type=int, help="max listings per site")
    p.add_argument("--max-prio", type=int, help="0 liked/maybe · 1 chats · 2 good deal · 3 tier 1/2 · 4 rest")
    p.add_argument("--until", help="HH:MM local: start no new checks after this")
    p.add_argument("--proxy-priority", action="store_true",
                   help="sites out of home pace budget: priority listings via site.yaml liveness.proxy_country")
    p.add_argument("--dry-run", action="store_true", help="check and log; write nothing to cardb or state")
    p.add_argument("--json", action="store_true", help="print every result")
    p.add_argument("--plist", action="store_true", help="print the launchd plist template rendered for this setup")
    p.add_argument("--at", default="04:30", help="--plist: daily start time (before the morning sweep)")


def cmd_liveness(a) -> int:
    if a.plist:
        print(render_plist(a.at, until=a.until or "06:50"))
        return 0
    from carhunt.sites import liveness
    s = liveness.run(sites=a.site, cars=a.car, daily=a.daily, sample=a.sample, limit=a.limit, max_prio=a.max_prio,
                     until=a.until or ("06:50" if a.daily else None), dry=a.dry_run, proxy_priority=a.proxy_priority)
    results = s.pop("results")
    if a.json:
        for r in results:
            _out(r)
    _out(s)
    return liveness.car_exit(results) if a.car else 0


def render_plist(at: str, *, until: str) -> str:
    import shutil

    from carhunt.access import _core
    h, m = (int(x) for x in at.split(":"))
    tmpl = Template(resources.files("carhunt.sites").joinpath("liveness.plist.tmpl").read_text(encoding="utf-8"))
    return tmpl.substitute(carhunt=shutil.which("carhunt") or "carhunt", home=str(_core.home()), hour=h, minute=m,
                           until=until, logs=str(_core.path("sites", "liveness", "launchd.log")))


if __name__ == "__main__":   # `python -m carhunt.sites.cli …` before core's dispatcher exists
    ap = argparse.ArgumentParser(prog="carhunt")
    register(ap.add_subparsers(dest="group"))
    args = ap.parse_args()
    sys.exit(int(args.func(args) or 0) if hasattr(args, "func") else 2)
