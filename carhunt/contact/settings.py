"""Contact config: defaults (the EV run's proven values) deep-merged with config.yaml `contact:`.

Every number here is a rule from the EV run; the why lives next to it and in docs/contact.md.
"""
from __future__ import annotations

import copy
from typing import Any

DEFAULTS: dict[str, Any] = {
    "variant": "home",  # home (private sellers, home market) | abroad (dealers abroad)
    # No sends at all (owner tz). Why: nobody answers at night; night sends look like a bot.
    "quiet_hours": "01:30-08:10",
    # First messages only in this window, seller-local time (tz by phone prefix / car country).
    "opener_window": "09:30-21:30",
    # Seller-local business hours for nudges and for channels with `seller_hours: true`.
    "seller_hours": {
        "dealer": {"mon-fri": "08:30-19:00", "sat": "08:30-13:00", "sun": "10:00-19:00"},
        "private": {"mon-sun": "10:00-20:00"},
    },
    # Rate limits over the shared ledger (all agents). `channels`: names, "sites" (= every site
    # channel) or "*". `kind`: opener|nudge|any. `per_channel`: count each channel separately.
    "limits": [
        # WhatsApp bans spam-shaped bursts from new contacts on the owner's main number.
        {"name": "chat-spacing", "channels": ["whatsapp", "sites"], "min_gap_s": 180},
        {"name": "chat-hourly", "channels": ["whatsapp", "sites"], "per": "hour", "max": 12},
        # One shared opener budget (EV: 6 → 8 → 10 → 20/day over 4 days; abroad sends used to bypass it).
        {"name": "openers-daily", "channels": "*", "kind": "opener", "per": "day", "max": 20,
         "reserve": {"role": "outreach-home", "slots": 4, "until": "15:00"}},
        {"name": "opener-spacing", "channels": "*", "kind": "opener", "min_gap_s": 600},
        {"name": "email-spacing", "channels": ["email"], "min_gap_s": 300},
        {"name": "site-spacing", "channels": ["sites"], "per_channel": True, "min_gap_s": 600},
        # Short follow-ups to silent threads: 4/10 answered same day (EV 2026-11-03), but cap them.
        {"name": "followups-daily", "channels": "*", "kind": "nudge", "per": "day", "max": 15},
    ],
    "reply": {
        "min_seller_age_s": 180,  # seller's message ≥3 min old before we answer (instant replies read as a bot)
        "owner_backoff_min": 15,  # owner typed in the chat himself → it's his chat
    },
    "opener": {
        "max_chars": 280,  # 5–10-question openers got 4/18 replies vs ~13/13 for short ones (EV 11-01..04)
        "max_questions": 2,  # one question per message, two at most
        # specs in an opener made sellers wary; the ad already says it
        "spec_pattern": r"\b\d[\d.,]*\s?(km|kwh|kw|hp|cv|ps|ch|€|eur)\b",
    },
    "nudge": {
        "after_h": 48,
        "auto_reply_s": 15,  # a "reply" this soon after ours is an auto-greeting (fastest human: 28 s)
        "statuses": ["new", "to_contact", "contacted", "talking"],
        # Car must match one `qualify` predicate and no `exclude` predicate (cardb car fields).
        "qualify": [{"field": "tier", "eq": 1}, {"field": "verdict.value", "eq": "up"},
                    {"field": "good_deal", "eq": True}],
        "exclude": [],
        "seller_hours": "dealer",
    },
    "duplicate_prefix": 60,  # same first 60 chars already sent to this target → refuse
    "allow_unlisted": False,  # `--to` must be a contact of the car's seller in cardb
    "require_active_agent": True,  # caller's AGTERM_SESSION_ID == its role's state.json active_agent
    "channels": {
        "whatsapp": {"max_len": 500, "seller_hours": False},
        "email": {"seller_hours": True},
        "sites": {"seller_hours": False},
    },
    "persona": {},
    "phone_tz": {
        "351": "Europe/Lisbon", "34": "Europe/Madrid", "33": "Europe/Paris", "49": "Europe/Berlin",
        "39": "Europe/Rome", "32": "Europe/Brussels", "31": "Europe/Amsterdam", "41": "Europe/Zurich",
        "43": "Europe/Vienna", "352": "Europe/Luxembourg", "45": "Europe/Copenhagen", "46": "Europe/Stockholm",
        "47": "Europe/Oslo", "358": "Europe/Helsinki", "48": "Europe/Warsaw", "420": "Europe/Prague",
        "421": "Europe/Bratislava", "36": "Europe/Budapest", "386": "Europe/Ljubljana", "385": "Europe/Zagreb",
        "44": "Europe/London", "353": "Europe/Dublin", "30": "Europe/Athens", "40": "Europe/Bucharest",
        "359": "Europe/Sofia", "370": "Europe/Vilnius", "371": "Europe/Riga", "372": "Europe/Tallinn",
        "377": "Europe/Monaco", "376": "Europe/Andorra",
    },
    "country_tz": {
        "PT": "Europe/Lisbon", "ES": "Europe/Madrid", "FR": "Europe/Paris", "DE": "Europe/Berlin",
        "IT": "Europe/Rome", "BE": "Europe/Brussels", "NL": "Europe/Amsterdam", "LU": "Europe/Luxembourg",
        "AT": "Europe/Vienna", "CH": "Europe/Zurich", "PL": "Europe/Warsaw", "CZ": "Europe/Prague",
        "DK": "Europe/Copenhagen", "SE": "Europe/Stockholm", "GB": "Europe/London", "IE": "Europe/Dublin",
    },
    "default_phone_cc": "",  # prepended to bare national numbers (e.g. "351" for 9-digit PT numbers)
}


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def contact_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    user = dict((cfg or {}).get("contact") or {})
    if isinstance(user.get("channels"), list):  # `channels: [whatsapp, email, …]` = enabled list, not settings
        user["enabled"] = user.pop("channels")
    return merge(DEFAULTS, user)
