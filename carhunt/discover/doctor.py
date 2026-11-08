"""`carhunt doctor` checks for discover: search criteria, enabled sites, cursor state, heuristics data."""
from __future__ import annotations

import json
from typing import Any


def _check(name: str, status: str, detail: str, fix: str = "") -> Any:
    try:
        from carhunt.core.doctor import Check
        return Check(name, status, detail, fix)
    except ImportError:
        return {"name": name, "status": status, "detail": detail, "fix": fix}


def checks() -> list[Any]:
    from carhunt.discover import _env, heuristics
    from carhunt.sites import base

    out = []
    cfg = _env.config()
    models = (cfg.get("search") or {}).get("models") or []
    out.append(_check("discover: search.models", "ok" if models else "fail", f"{len(models)} model(s)",
                      "add makes/models under search.models in config.yaml"))
    enabled = (cfg.get("sites") or {}).get("enabled") or []
    unknown = sorted(set(enabled) - set(base.ids()))
    out.append(_check("discover: sites.enabled", "warn" if unknown or not enabled else "ok",
                      f"unknown: {', '.join(unknown)}" if unknown else f"{len(enabled)} site(s)",
                      "site ids = `site:` in carhunt/sites/*/site.yaml"))
    p = _env.home() / "discover" / "cursors.json"
    try:
        n = len(json.loads(p.read_text())) if p.exists() else 0
        out.append(_check("discover: cursors", "ok", f"{n} site(s) with cursors" if n else "none yet (first sweep)"))
    except ValueError as e:
        out.append(_check("discover: cursors", "fail", f"{p.name} unreadable: {e}",
                          f"move {p} aside; the next sweep re-reads from the newest ads"))
    try:
        names = heuristics.names()
        for n_ in names:
            heuristics.load(n_)
        out.append(_check("discover: heuristics", "ok", ", ".join(names) or "none"))
    except Exception as e:  # noqa: BLE001
        out.append(_check("discover: heuristics", "fail", f"{type(e).__name__}: {e}", "fix the plug-in YAML"))
    geo = ((cfg.get("discover") or {}).get("distance") or {}).get("geocoder", "nominatim")
    out.append(_check("discover: geocoder", "ok", f"{geo} (cached in $CARHUNT_HOME/discover/geocode.json)"))
    return out
