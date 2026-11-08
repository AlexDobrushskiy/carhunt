"""Doctor checks for sites: site.yaml schema, enabled ids, transport deps, stale measurements."""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

from carhunt.sites import base

STALE_DAYS = 45   # walls change: re-measure a site's pace/route after this


def _check(name: str, status: str, detail: str = "", fix: str = ""):
    try:
        from carhunt.core.doctor import Check
    except ImportError:   # core not installed yet: same shape
        from dataclasses import dataclass

        @dataclass
        class Check:  # type: ignore[no-redef]
            name: str
            status: str
            detail: str = ""
            fix: str = ""
            module: str = ""
    return Check(name, status, detail, fix, module="sites")


def _enabled() -> list[str]:
    try:
        from carhunt.access import _core
        return list((_core.section("sites") or {}).get("enabled") or [])
    except Exception:
        return []


def checks() -> list:
    out = []
    import jsonschema
    schema = json.loads((base.ROOT / "site.schema.json").read_text())
    bad, stale = [], []
    for p in sorted(Path(base.ROOT).glob("*/site.yaml")):
        meta = base.load_meta(p.parent.name)
        try:
            jsonschema.validate(meta, schema)
        except jsonschema.ValidationError as e:
            bad.append(f"{p.parent.name}: {e.message}")
        try:
            if (date.today() - date.fromisoformat(str(meta.get("measured")))).days > STALE_DAYS:
                stale.append(meta["site"])
        except ValueError:
            stale.append(meta.get("site", p.parent.name))
    out.append(_check("sites: site.yaml schema", "fail" if bad else "ok", "; ".join(bad) or f"{len(base.ids())} sites",
                      "fix the listed site.yaml keys (carhunt/sites/site.schema.json)" if bad else ""))
    out.append(_check("sites: measurements fresh", "warn" if stale else "ok",
                      f"older than {STALE_DAYS} days: {', '.join(stale)}" if stale else "",
                      "re-measure wall/pace with a few read-only loads, update site.yaml `measured`" if stale else ""))
    unknown = [s for s in _enabled() if s not in base.ids()]
    out.append(_check("sites: enabled ids known", "fail" if unknown else "ok",
                      f"unknown: {', '.join(unknown)}" if unknown else ", ".join(_enabled()) or "none enabled",
                      f"use ids from `carhunt site list` in config sites.enabled" if unknown else ""))
    missing = [m for m in ("cryptography",) if importlib.util.find_spec(m) is None]
    out.append(_check("sites: python deps", "warn" if missing else "ok", ", ".join(missing),
                      "pip install -e '.[sites]' (standvirtual phone/VIN decode needs cryptography)" if missing else ""))
    for mod, what in (("pace", "shared pace ledger (in-process gaps only without it)"),
                      ("session", "browser routes (plain-chrome/lane sites can't read without it)"),
                      ("proxy", "country routes (country_ip sites, liveness --proxy-priority)")):
        ok = importlib.util.find_spec(f"carhunt.access.{mod}") is not None
        out.append(_check(f"sites: access.{mod}", "ok" if ok else "warn", "" if ok else f"missing: {what}",
                          "" if ok else "install the browsers module (scripts/bootstrap)"))
    return out
