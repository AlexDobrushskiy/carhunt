"""Thin adapter over carhunt.core (paths, config, clock, notify, cardb).

Uses core when it is installed; the fallbacks keep this package testable on its own
and mirror the design.md interface exactly.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def safe_name(name: str, what: str = "name") -> str:
    try:
        from carhunt.core.paths import safe_name as core_safe
        return core_safe(name, what)
    except ImportError:
        if not _NAME.match(name or "") or ".." in name:
            raise ValueError(f"invalid {what}: {name!r} (letters, digits, _ . - only)")
        return name


def home() -> Path:
    try:
        from carhunt.core.paths import home as core_home
        return core_home()
    except ImportError:
        return Path(os.environ.get("CARHUNT_HOME") or "~/.carhunt").expanduser()


def agents_root() -> Path:
    return home() / "agents"


def agent_dir(role: str) -> Path:
    d = agents_root() / safe_name(role, "agent")
    d.mkdir(parents=True, exist_ok=True)
    return d


def pause_file() -> Path:
    try:
        from carhunt.core.paths import pause_file as core_pause
        return core_pause()
    except ImportError:
        return home() / "PAUSE"


def repo_root() -> Path:
    env = os.environ.get("CARHUNT_REPO")
    return Path(env).expanduser() if env else Path(__file__).resolve().parents[2]


def config_file() -> Path:
    env = os.environ.get("CARHUNT_CONFIG")
    return Path(env).expanduser() if env else home() / "config.yaml"


def _deep_merge(base: dict, over: Mapping) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, Mapping) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _as_dict(cfg: Any) -> dict:
    if isinstance(cfg, Mapping):
        return dict(cfg)
    for attr in ("data", "raw", "as_dict", "to_dict"):
        v = getattr(cfg, attr, None)
        v = v() if callable(v) else v
        if isinstance(v, Mapping):
            return dict(v)
    return {}


def load_config() -> dict:
    """Config as a plain dict with orchestrate defaults filled in. Missing file = defaults."""
    raw: dict = {}
    try:
        from carhunt.core import config as core_config
        raw = _as_dict(core_config.load())
    except ImportError:
        f = config_file()
        if f.is_file():
            import yaml
            raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    return _deep_merge(DEFAULTS, raw)


def cfg(config: Mapping, dotted: str, default: Any = None) -> Any:
    cur: Any = config
    for part in dotted.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return default
        cur = cur[part]
    return cur


def now(config: Mapping | None = None) -> datetime:
    try:
        from carhunt.core import clock
        return clock.now()
    except ImportError:
        fake = os.environ.get("CARHUNT_FAKE_NOW")
        tz = ZoneInfo(cfg(config or {}, "owner.tz", "UTC") or "UTC")
        if fake:
            dt = datetime.fromisoformat(fake)
            return dt if dt.tzinfo else dt.replace(tzinfo=tz)
        return datetime.now(tz)


def notify(text: str, *, agent: str, kind: str, buttons: list[str] | None = None) -> Any:
    """core.notify.send; without core, print (the stdout backend)."""
    try:
        from carhunt.core import notify as core_notify
        return core_notify.send(text, agent=agent, kind=kind, buttons=buttons)
    except ImportError:
        print(f"[notify {kind} from {agent}]\n{text}")
        return None


def cardb_queue(limit: int) -> list[dict]:
    """Top of the cardb queue (tier 1 first). Empty when cardb is unreachable."""
    try:
        from carhunt.core import db
        client = db.Client.from_config()
        res = client.queue(tier="1", limit=limit) if _accepts(client.queue, "tier") else client.queue()
    except Exception:  # noqa: BLE001 - the digest still goes out without cars
        return []
    items = res.get("items", []) if isinstance(res, Mapping) else list(res or [])
    return list(items)[:limit]


def _accepts(fn: Any, name: str) -> bool:
    import inspect
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def self_session_id() -> str | None:
    return os.environ.get("CARHUNT_SESSION_ID") or os.environ.get("AGTERM_SESSION_ID") or None


def self_role() -> str | None:
    return os.environ.get("CARHUNT_AGENT") or None
