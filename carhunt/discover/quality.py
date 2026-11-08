"""The thin-ad rule + the ask list, one rule for every site and agent.

Why one rule: each country agent had its own cut-off and almost every dealer ad came out "thin" (2026-11-03).
Thin = fewer than `min_photos` photos, or fewer than `min_info` of {owners, accident-free, service history, battery
SoH, a wanted option stated}. Discover cannot look at photos, so interior / odometer-photo coverage is never claimed:
it is always in the ask list until a photo review (vet) clears it.
"""
from __future__ import annotations

from carhunt.discover.normalize import Listing

DEFAULTS = {"min_photos": 8, "min_info": 3}
INFO = (("owners", "number of owners"), ("accident_free", "accident history"),
        ("service_history", "service history"), ("soh", "battery SoH report"))


def assess(lst: Listing, cfg: dict) -> None:
    """Sets lst.thin / lst.asks and the ad_quality, ask, ad_photo_count facts."""
    rule = {**DEFAULTS, **((cfg.get("discover") or {}).get("thin") or {})}
    wanted = list(((cfg.get("search") or {}).get("options_wanted") or {}).keys())
    info = sum(1 for k, _ in INFO if k in lst.facts)
    info += int(any(lst.options.get(k, ("",))[0] == "yes" for k in wanted))
    n = len(lst.photos)
    lst.thin = (not lst.detail) or n < rule["min_photos"] or info < rule["min_info"]
    asks = []
    if n < rule["min_photos"]:
        asks.append(f"more photos (ad has {n}; all sides)")
    asks += ["interior photos", "odometer photo showing km"]
    asks += [label for k, label in INFO if k not in lst.facts and (k != "soh" or lst.fuel in (None, "bev", "phev"))]
    asks += [f"{k}?" for k in wanted if k not in lst.options]
    lst.asks = asks + [a for a in lst.asks if a not in asks]
    lst.fact("ad_quality", "card-only" if not lst.detail else "thin" if lst.thin else "full", "agent_inference")
    lst.fact("ad_photo_count", n, "ad_spec")
    lst.fact("ask", "; ".join(lst.asks), "agent_inference")
