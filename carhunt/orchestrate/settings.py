"""Orchestrate's config view: the owner's config (core) with this module's defaults filled in.

Config stays a plain dict here because briefs are rendered from it (`launch.flatten`).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from carhunt.core import config as core_config

DEFAULTS: dict[str, Any] = {
    "owner": {"name": "owner", "tz": "UTC", "languages": ["en"]},
    "contact": {"quiet_hours": "01:30-08:10", "opener_window": "09:30-21:30"},
    "notify": {"quiet_hours": "21:30-09:30", "digests": ["09:30", "20:00"]},
    "orchestrate": {
        "session_backend": "agterm",
        "agent_cli": "claude",
        "agent_args": {"claude": [], "codex": []},
        "handover_ctx_pct": 50,
        "cycle_minutes": 20,
        "mailbox": "carhunt",          # carhunt | external | off
        "workspace": "",               # agterm workspace name for agent sessions ("" = current)
        "digest_strong_cars": 8,
        "schedule": {
            "sweep": "07:00",
            "unpause": "08:10",
            "digest": ["09:30", "20:00"],
            "pause": "23:00",
            "learning": "23:15",
        },
        "hooks": {"secret_globs": ["{home}/secrets/**", "**/.env", "**/*.secret"]},
    },
}


def _deep_merge(base: dict, over: Mapping) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    """Config as a plain dict (secret refs stay `secret:NAME` strings); no config file = defaults."""
    cfg = core_config.load_or_none()
    return _deep_merge(DEFAULTS, cfg.as_dict() if cfg else {})


def get(config: Mapping, dotted: str, default: Any = None) -> Any:
    cur: Any = config
    for part in dotted.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return default
        cur = cur[part]
    return cur


def self_session_id() -> str | None:
    return os.environ.get("CARHUNT_SESSION_ID") or os.environ.get("AGTERM_SESSION_ID") or None


def self_role() -> str | None:
    return os.environ.get("CARHUNT_AGENT") or None
