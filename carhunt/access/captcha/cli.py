"""`carhunt captcha …` / `browsers/bin/captcha-solve …`: solve or classify the wall in a browser tab.

  solve  --plain|--lane|--identity[-a…]|--cdp URL  [--url SUBSTR | --target ID] [--dry-run] [opts]
  detect --plain|--lane|…  [--url SUBSTR]          classify the live tab, no action
  detect --html FILE [--frame SRC=FILE …]          classify saved HTML (offline)
  detect --image BG --piece PIECE                  puzzle gap from the widget's own images (offline)
  detect --image SHOT                              name the wall in a screenshot (local VLM)
  bench  --fixtures DIR                            offline accuracy on a labelled set
  stats                                            attempts / outcomes from the log
  slide-js                                         print the MCP-lane slider snippet (browser_run_code_unsafe)

Routes attach to an already-open tab over its debug port (ports from config `browsers.ports`).
DataDome: solve in plain-chrome (`plain-chrome open URL`, then `solve --plain --url …`), never in a lane
(a correct slide there still gets "Access temporarily restricted"). Never open a second browser on a site
whose captcha is showing or was just solved: reuse that tab. Prints one JSON line; exit 0 only for
solved / no-captcha (detect: always 0 unless an error). Never notifies anyone.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from carhunt.access.settings import POOL_LETTERS


def _add_route(p: argparse.ArgumentParser, required: bool) -> None:
    g = p.add_mutually_exclusive_group(required=required)
    g.add_argument("--plain", dest="route", action="store_const", const="plain", help="plain-chrome's browser")
    g.add_argument("--lane", dest="route", action="store_const", const="lanes", help="the lanes MCP Chrome (ch-lane-*)")
    g.add_argument("--identity", dest="route", action="store_const", const="identity", help="identity MCP Chrome (hold the lease)")
    for c in POOL_LETTERS:
        g.add_argument(f"--identity-{c}", dest="route", action="store_const", const=f"identity-{c}", help=argparse.SUPPRESS)
    g.add_argument("--cdp", help="any Chrome debug endpoint, e.g. http://127.0.0.1:PORT")
    p.add_argument("--url", help="substring of the tab's URL (needed when several tabs are open)")
    p.add_argument("--target", help="CDP targetId of the tab")


def _endpoint(a) -> tuple[str, int, str]:
    """(cdp url, port, route kind for solve())."""
    if getattr(a, "cdp", None):
        port = int(a.cdp.rstrip("/").rsplit(":", 1)[1].split("/")[0])
        return a.cdp, port, "cdp"
    from carhunt.access import settings
    s = settings.load()
    if a.route == "plain":
        port, route = s.plain_debug_port, "plain"
    else:
        port, route = s.debug_port(a.route), ("lane" if a.route == "lanes" else a.route)
    return f"http://127.0.0.1:{port}", port, route


def _page_for(browser, target: str | None, url_part: str | None):
    pages = [pg for c in browser.contexts for pg in c.pages]
    if url_part and not target:
        hits = [pg for pg in pages if url_part in pg.url]
        if len(hits) == 1:
            return hits[0]
        raise SystemExit(f"captcha: {len(hits)} tabs match --url {url_part!r}" +
                         (": " + ", ".join(pg.url[:80] for pg in hits) if hits else
                          " (open it first, e.g. `plain-chrome open URL`; don't open a second browser on that site)"))
    if not target:
        if len(pages) == 1:
            return pages[0]
        raise SystemExit(f"captcha: {len(pages)} tabs open; pass --url SUBSTR or --target ID")
    for pg in pages:
        s = pg.context.new_cdp_session(pg)
        try:
            if s.send("Target.getTargetInfo")["targetInfo"]["targetId"] == target:
                return pg
        finally:
            s.detach()
    raise SystemExit(f"captcha: tab {target} not found")


def _info_dict(info) -> dict:
    if info is None:
        return {"captcha": None}
    return {"kind": info.kind, "vendor": info.vendor, "solvable": info.solvable, "frame_url": (info.url or "")[:200],
            "detail": {k: v for k, v in info.detail.items()}}


def _live(a, fn):
    from playwright.sync_api import sync_playwright
    cdp, port, route = _endpoint(a)
    with sync_playwright() as p:
        try:
            b = p.chromium.connect_over_cdp(cdp)
        except Exception as e:
            raise SystemExit(f"captcha: nothing listening at {cdp} ({type(e).__name__}); is that browser running?")
        # never b.close(): that would close a browser we only attached to
        return fn(_page_for(b, a.target, a.url), port, route)


def cmd_solve(a) -> int:
    from .core import OK, solve

    def run(page, port, route):
        res = solve(page, route=route, input=a.input, port=port, max_attempts=a.max_attempts,
                    use_vlm=not a.no_vlm, force=a.force, dry_run=a.dry_run)
        out = res.to_dict()
        out["url"] = page.url
        print(json.dumps(out, default=str))
        return 0 if res.status in OK or (a.dry_run and res.status == "dry-run") else 1
    return _live(a, run)


def cmd_detect(a) -> int:
    if a.html:
        from .detect import classify
        from .static import StaticPage
        frames = {}
        for spec in a.frame or []:
            src, _, f = spec.rpartition("=")
            frames[src] = Path(f).read_text()
        page = StaticPage(Path(a.html).read_text(), a.url or "https://example.invalid/", frames, a.status)
        print(json.dumps(_info_dict(classify(page.static_snapshot())), default=str))
        return 0
    if a.image:
        import cv2
        img = cv2.imread(a.image, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise SystemExit(f"captcha: cannot read image {a.image}")
        if a.piece:
            from . import vision
            piece = cv2.imread(a.piece, cv2.IMREAD_UNCHANGED)
            if piece is None or piece.ndim < 3 or piece.shape[2] < 4:
                raise SystemExit("captcha: --piece must be an RGBA image (transparent around the piece)")
            g, px, py = vision.gap_from_images(img, piece)
            print(json.dumps({"kind": "puzzle-gap", "gap_x": g.x, "piece_x": px, "piece_y": py,
                              "travel_px": g.x - px, "margin": round(g.margin, 2)}))
            return 0
        from .config import load
        from .vlm import Ollama
        client = Ollama.from_config(load())
        if not client.available():
            print(json.dumps({"kind": None, "error": f"local VLM {client.model} not available at {client.url}",
                              "fix": f"ollama pull {client.model}"}))
            return 1
        print(json.dumps({"kind": "vlm", **client.classify(img[:, :, :3] if img.ndim == 3 else img)}))
        return 0
    if not (a.route or a.cdp):
        raise SystemExit("captcha detect: pass a route (--plain/--lane/--identity/--cdp), --html or --image")
    from .detect import detect

    def run(page, port, route):
        print(json.dumps(_info_dict(detect(page)), default=str))
        return 0
    return _live(a, run)


def cmd_bench(a) -> int:
    from .bench import run
    r = run(Path(a.fixtures), a.tolerance)
    print(json.dumps(r))
    bad = sum(v["n"] - v["ok"] for v in r.values())
    return 0 if bad == 0 else 1


def cmd_stats(a) -> int:
    from .attempts import AttemptLog
    print(f"{'site':18} {'kind':18} {'input':8} {'method':14} {'outcome':11} {'n':>3} {'avg s':>6}  last (UTC)")
    for r in AttemptLog().stats():
        print(f"{r[0]:18} {r[1]:18} {r[2][:8]:8} {str(r[3])[:14]:14} {r[4]:11} {r[5]:>3} {r[6]:>6}  {r[7]}")
    return 0


def cmd_slide_js(a) -> int:
    print((Path(__file__).parent / "slide.js").read_text())
    return 0


def _build(sub) -> None:
    p = sub.add_parser("solve", help="solve the wall in an open tab")
    _add_route(p, required=True)
    p.add_argument("--dry-run", action="store_true", help="detect + budget/route checks only, no input")
    p.add_argument("--input", choices=["cdp", "macos"], default="cdp",
                   help="pointer path: cdp (default) or macos native events to the Chrome process")
    p.add_argument("--max-attempts", type=int, default=None, help="default browsers.captcha.max_attempts (2)")
    p.add_argument("--no-vlm", action="store_true", help="never call the local vision model")
    p.add_argument("--force", action="store_true", help="ignore the per-site budget and the DataDome route rule")
    p.set_defaults(func=cmd_solve)

    p = sub.add_parser("detect", help="classify a wall (live tab, saved HTML or image)")
    _add_route(p, required=False)
    p.add_argument("--html", help="saved page HTML")
    p.add_argument("--frame", action="append", metavar="SRC=FILE", help="HTML of an iframe in --html (repeatable)")
    p.add_argument("--status", type=int, default=200, help="HTTP status of the saved page")
    p.add_argument("--image", help="puzzle background (with --piece) or a page screenshot")
    p.add_argument("--piece", help="puzzle piece image with alpha, same pixel frame as --image")
    p.set_defaults(func=cmd_detect)

    p = sub.add_parser("bench", help="offline accuracy on a labelled fixtures dir")
    p.add_argument("--fixtures", required=True, help="dir with labels.json (make_fixtures.py writes one)")
    p.add_argument("--tolerance", type=int, default=3, help="puzzle gap tolerance in px")
    p.set_defaults(func=cmd_bench)

    sub.add_parser("stats", help="attempt log summary").set_defaults(func=cmd_stats)
    sub.add_parser("slide-js", help="print the MCP-lane slider snippet").set_defaults(func=cmd_slide_js)


def register(sub) -> None:
    """Add the `captcha` group to carhunt's top-level subparsers. Handlers: args.func(args) -> exit code."""
    p = sub.add_parser("captcha", help="local captcha / bot-wall solver", description=__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    _build(p.add_subparsers(dest="captcha_cmd", required=True))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("--") and argv[0] not in ("-h", "--help"):
        argv = ["solve"] + argv  # `captcha-solve --plain --url X` = solve
    ap = argparse.ArgumentParser(prog="captcha-solve", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    _build(ap.add_subparsers(dest="captcha_cmd", required=True))
    a = ap.parse_args(argv)
    return a.func(a)
