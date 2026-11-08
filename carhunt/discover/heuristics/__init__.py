"""Model heuristics plug-ins: one YAML per model group (`heuristics/<name>.yaml`), `vag_meb.yaml` is the worked example.

A plug-in maps what an ad says to what the car is, for one model group:
- `families`: canonical family name → regex on make/model/variant/title.
- `variants`: battery / power / drive per trim + year (first match per family wins; `match: ''` rules are power
  fallbacks with `power_kw_min|max`). Small packs share trim names across years (2025+ Q4 40 = 63 kWh), so verify kW
  + battery per car, never the trim name alone.
- `drive_rules`: `on: ad_text` rules first, then variant rules; one distinct drive per pass is decisive, more = unknown.
- `option_cues`: `kind: text` cues are applied here (source `ad_text`); `kind: photo` cues are for the photo review
  (vet) and agents — discover never claims photo evidence.
- `pr_codes` + `fallback_ask`: when wanted options stay unknown, ask the seller once for the option-sticker photo.
Config: `discover.heuristics` = plug-in names to load (default: all). Add a model group = add a YAML; no code.
"""
from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from carhunt.discover.normalize import Listing, cue_hit, fold

ROOT = Path(__file__).resolve().parent


@cache
def load(name: str) -> dict:
    return yaml.safe_load((ROOT / f"{name}.yaml").read_text(encoding="utf-8"))


def names() -> list[str]:
    return sorted(p.stem for p in ROOT.glob("*.yaml"))


def plugins(cfg: dict | None = None) -> list[dict]:
    wanted = ((cfg or {}).get("discover") or {}).get("heuristics")
    return [load(n) for n in (wanted if wanted is not None else names())]


def _fams(rule: dict) -> list[str] | None:
    f = rule.get("family") or rule.get("families")
    return None if f is None else ([f] if isinstance(f, str) else list(f))


def _year_ok(rule: dict, year: int | None) -> bool:
    if year is None:
        return not (rule.get("year_from") or rule.get("year_to"))
    return not ((rule.get("year_from") and year < rule["year_from"]) or (rule.get("year_to") and year > rule["year_to"]))


def family_of(lst: Listing, plugin: dict) -> str | None:
    head = fold(f"{lst.make or ''} {lst.model or ''} {lst.variant or ''} {lst.title or ''}")
    for name, f in (plugin.get("families") or {}).items():
        if re.search(f["match"], head) and (not lst.make or fold(f["make"]) in fold(lst.make) or
                                             fold(f["make"])[:2] == fold(lst.make)[:2]):
            return name
    return None


def variant_of(lst: Listing, plugin: dict, family: str) -> dict | None:
    head = fold(f"{lst.model or ''} {lst.variant or ''} {lst.title or ''}")
    fallback = None
    for r in plugin.get("variants") or []:
        if family not in (_fams(r) or [family]):
            continue
        if not r.get("match"):
            p = lst.power_kw
            if fallback is None and p is not None and p >= r.get("power_kw_min", 0) and p <= r.get("power_kw_max", 10**4):
                fallback = r
            continue
        if not _year_ok(r, lst.year):
            continue
        if re.search(r["match"], head) and not (r.get("unless") and re.search(r["unless"], head)):
            if r.get("power_kw") and lst.power_kw and abs(r["power_kw"] - lst.power_kw) > 2:
                continue        # stated power beats the year/trim guess (late-2023 regs can be either side of MY24)
            return r
    return fallback


def drive_of(lst: Listing, plugin: dict, family: str) -> tuple[str | None, str]:
    texts = {"ad_text": fold(f"{lst.title or ''} {lst.description}"),
             "variant": fold(f"{lst.model or ''} {lst.variant or ''} {lst.title or ''}")}
    for on in ("ad_text", "variant"):
        hits: set[str] = set()
        why, stopped = "", False
        for r in plugin.get("drive_rules") or []:
            if r.get("on", "variant") != on or family not in (_fams(r) or [family]):
                continue
            t = texts[on]
            if re.search(r["match"], t) and not (r.get("unless") and re.search(r["unless"], t)):
                if r.get("stop"):
                    stopped = True      # a negated / listed-alternatives drive: this pass is not decisive
                    break
                hits.add(r["drive"])
                why = why or r.get("why", "")
        if stopped:
            continue
        if len(hits) == 1:
            return hits.pop(), f"{on} rule: {why}"
        if hits:
            return None, f"{on} rules disagree ({', '.join(sorted(hits))})"
    return None, ""


def apply(lst: Listing, cfg: dict | None = None) -> str | None:
    """Fill battery / drive / text options from the first plug-in that knows the family. Returns the family."""
    wanted = list((((cfg or {}).get("search") or {}).get("options_wanted") or {}).keys())
    for plugin in plugins(cfg):
        family = family_of(lst, plugin)
        if not family:
            continue
        v = variant_of(lst, plugin, family)
        if v:
            if lst.battery_net_kwh is None and v.get("battery_net_kwh"):
                lst.battery_net_kwh = float(v["battery_net_kwh"])
                lst.fact("battery_basis", f"{plugin['plugin']} variant rule: {v.get('note', '')}".strip(),
                         "agent_inference")
            if v.get("drive") and lst.drive is None:
                lst.drive = v["drive"]
                lst.fact("drive_basis", f"{plugin['plugin']} variant rule", "agent_inference")
        d, why = drive_of(lst, plugin, family)
        if d and lst.drive is None:
            lst.drive = d
            lst.fact("drive_basis", why, "agent_inference")
        elif d and d != lst.drive:
            lst.fact("drive_evidence_conflict", f"ad/site says {lst.drive}; {why} says {d}; verify", "agent_inference")
        text = fold(lst.text())
        for cue in plugin.get("option_cues") or []:
            if cue.get("kind") != "text" or family not in (cue.get("families") or [family]):
                continue
            if _year_ok(cue, lst.year) and cue_hit(cue["match"], text, cue.get("unless")):
                lst.opt(cue["option"], str(cue["implies"]), "ad_text")
        unknown = [k for k in wanted if k not in lst.options and _has_cue(plugin, k)]
        if unknown and plugin.get("fallback_ask"):
            lst.asks.append(f"options unknown ({', '.join(unknown)}): ask once for the option-sticker photo "
                            f"({plugin['plugin']} fallback_ask)")
        return family
    return None


def _has_cue(plugin: dict, key: str) -> bool:
    return any(c.get("option") == key for c in plugin.get("option_cues") or []) or \
        any(p.get("option") == key for p in (plugin.get("pr_codes") or {}).values())


def decode_pr(codes: list[str], plugin_name: str) -> dict[str, dict[str, Any]]:
    """PR codes from an option sticker → {option: {value, code, conf}} (for vet/agents)."""
    table = load(plugin_name).get("pr_codes") or {}
    out: dict[str, dict[str, Any]] = {}
    for c in codes:
        r = table.get(c.strip().upper())
        if r:
            out[r["option"]] = {"value": str(r["implies"]), "code": c.upper(), "conf": r.get("conf")}
    return out
