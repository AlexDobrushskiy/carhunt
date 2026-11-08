"""Render the per-site access table (skill reference) from `carhunt/sites/<site>/site.yaml` files.

    carhunt browser site-table [--sites-dir DIR] [--write PATH] [--check PATH]

`--check` exits 1 when PATH differs from a fresh render (CI: the skill table never drifts from site.yaml).
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DEFAULT_SITES_DIR = REPO / "carhunt" / "sites"
COLUMNS = ["site", "wall", "route", "country IP", "pace", "caps",
           "account / verification", "messaging", "measured", "notes"]
NONE = "—"

_PACE = {  # key -> (prefix, suffix)
    "min_gap_s": ("≥", " s gap"),
    "max_loads_per_run": ("≤", "/run"),
    "per_hour": ("≤", "/h"),
}
_CAPS = {
    "phone_per_day": ("phone ≤", "/day"),
    "send_per_day": ("send ≤", "/day"),
    "login_per_day": ("login ≤", "/day"),
    "load_per_day": ("load ≤", "/day"),
}


def sites_dir(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("CARHUNT_SITES_DIR")
    return Path(env).expanduser() if env else DEFAULT_SITES_DIR


def discover(root: Path | str | None = None) -> list[Path]:
    """`<root>/*/site.yaml`, sorted. root: arg, else $CARHUNT_SITES_DIR, else carhunt/sites."""
    return sorted(sites_dir(root).glob("*/site.yaml"))


def load(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if data is None:
        data = {}
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: site.yaml must be a mapping, got {type(data).__name__}")
    data = dict(data)
    # display name: same lookup order as pace.site_yaml (name, domain), else the plugin dir
    data["site"] = data.get("name") or data.get("domain") or data.get("site") or Path(path).parent.name
    return data


def _cell(v) -> str:
    """One markdown table cell: never empty, no pipes or newlines."""
    if v is None or v == "" or v == [] or v == {}:
        return NONE
    if isinstance(v, (dt.date, dt.datetime)):
        s = v.isoformat()[:10]
    elif isinstance(v, bool):
        s = "yes" if v else "no"
    elif isinstance(v, (list, tuple)):
        s = ", ".join(_cell(x) for x in v)
    elif isinstance(v, Mapping):
        s = "; ".join(f"{k}: {_cell(x)}" for k, x in v.items())
    else:
        s = str(v)
    s = "; ".join(" ".join(ln.split()) for ln in s.splitlines() if ln.strip())
    return s.replace("|", "\\|") or NONE


def _keyed(d, known: dict[str, tuple[str, str]]) -> str:
    if not d:
        return NONE
    if not isinstance(d, Mapping):
        return _cell(d)
    parts = []
    for k, v in d.items():
        if v is None:
            continue
        if k in known:
            pre, suf = known[k]
            parts.append(f"{pre}{v}{suf}")
        else:
            parts.append(f"{k} {_cell(v)}")
    return _cell(" · ".join(parts))


def _route(v) -> str:
    if isinstance(v, (list, tuple)):
        return _cell(" → ".join(str(x) for x in v))
    return _cell(v)


def _account(a) -> str:
    if not a:
        return NONE
    if not isinstance(a, Mapping):
        return _cell(a)
    need = a.get("needed_for") or []
    if isinstance(need, str):
        need = [need]
    ver = a.get("verification")
    parts = []
    if need:
        parts.append("for " + ", ".join(str(x) for x in need))
    if ver:
        parts.append(_cell(ver))
    extra = {k: v for k, v in a.items() if k not in ("needed_for", "verification")}
    if extra:
        parts.append(_cell(extra))
    return _cell(" · ".join(parts)) if parts else NONE


def row(site: Mapping) -> list[str]:
    return [
        _cell(site.get("site")),
        _cell(site.get("wall")),
        _route(site.get("route")),
        _cell(site.get("country_ip")),
        _keyed(site.get("pace"), _PACE),
        _keyed(site.get("caps"), _CAPS),
        _account(site.get("account")),
        _cell(site.get("messaging")),
        _cell(site.get("measured")),
        _cell(site.get("notes")),
    ]


def _source_label(paths: list[Path]) -> tuple[str, bool]:
    """(where the rows came from, is it the shipped carhunt/sites dir)."""
    parents = {p.resolve().parent.parent for p in paths}
    if not parents:
        return "`carhunt/sites/*/site.yaml`", True
    shipped = parents == {DEFAULT_SITES_DIR.resolve()}
    if len(parents) == 1:
        d = parents.pop()
        try:
            label = f"`{d.relative_to(REPO)}/*/site.yaml`"
        except ValueError:
            label = "`$CARHUNT_SITES_DIR/*/site.yaml`"
    else:
        label = "explicit site.yaml paths"
    return label, shipped


def render(site_yaml_paths: Iterable[Path | str]) -> str:
    paths = [Path(p) for p in site_yaml_paths]
    sites = sorted((load(p) for p in paths), key=lambda s: str(s["site"]).lower())
    source, shipped = _source_label(paths)
    out = [
        "# Site table (generated)",
        "",
        f"<!-- GENERATED by `carhunt browser site-table` from {source}. Do not edit: edit the site.yaml, then re-run with --write. -->",
        f"Source: {source} ({len(sites)} sites). Re-measure a row older than ~3 months; a new wall or changed result → edit that site's `site.yaml` (date it) and regenerate.",
    ]
    if not shipped:
        out += ["", "> **Placeholder:** rendered from a non-shipped source (test fixtures / override). "
                    "Real rows come from the sites module's `carhunt/sites/<site>/site.yaml`."]
    out += ["", "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    out += ["| " + " | ".join(row(s)) + " |" for s in sites]
    if not sites:
        out.append("| " + " | ".join([NONE] * len(COLUMNS)) + " |")
    out += ["", "Routes: `http` plain HTTP · `lane` Playwright MCP lane · `identity` logged-in pool browser · "
                "`plain-chrome` normal launch, attach after first load · `camoufox` anti-detect Firefox. "
                "`→` = try in this order.", ""]
    return "\n".join(out)


def _cmd(args: argparse.Namespace) -> int:
    paths = discover(args.sites_dir)
    text = render(paths)
    if args.check:
        p = Path(args.check)
        cur = p.read_text(encoding="utf-8") if p.exists() else ""
        if cur != text:
            sys.stderr.writelines(difflib.unified_diff(
                cur.splitlines(True), text.splitlines(True), str(p), "rendered"))
            print(f"{p}: out of date; run `carhunt browser site-table --write {p}`", file=sys.stderr)
            return 1
        return 0
    if args.write:
        p = Path(args.write)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"wrote {p} ({len(paths)} sites)", file=sys.stderr)
        return 0
    sys.stdout.write(text)
    return 0


def _add_args(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--sites-dir", help="dir holding <site>/site.yaml (default $CARHUNT_SITES_DIR, else carhunt/sites)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", metavar="PATH", help="write the table to PATH")
    g.add_argument("--check", metavar="PATH", help="exit 1 if PATH differs from a fresh render")
    ap.set_defaults(func=_cmd)


def register_cli(sub) -> None:
    """Add `site-table` to the `carhunt browser` subparsers."""
    _add_args(sub.add_parser("site-table", help="render the per-site access table from site.yaml files"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="site-table", description=__doc__.splitlines()[0])
    _add_args(ap)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
