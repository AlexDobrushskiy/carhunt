"""Config, paths, clock and the cardb client for discover.

Uses carhunt.core when installed; until core lands on main it falls back to the documented contract (env CARHUNT_HOME,
CARHUNT_CONFIG, CARHUNT_FAKE_NOW, CARHUNT_SECRET_CARDB_TOKEN, CARDB_URL) via carhunt.access._core and `_cardb`.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from carhunt.access import _core

DATA = Path(__file__).resolve().parent / "data"


def _plain(node: Any) -> Any:
    """Config node → plain dict/list (SecretRef objects stay as their `secret:NAME` string)."""
    if isinstance(node, Mapping):
        return {k: _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    if node.__class__.__name__ == "SecretRef":
        return str(node)
    return node


def config() -> dict:
    """The whole config as a plain dict ({} when there is none)."""
    try:
        from carhunt.core import config as core_config
    except ImportError:
        core_config = None
    if core_config is not None and hasattr(core_config, "load"):
        cfg = core_config.load()
        for attr in ("data", "raw"):
            val = getattr(cfg, attr, None)
            if isinstance(val, Mapping):
                return _plain(val)
        if isinstance(cfg, Mapping):
            return _plain(cfg)
        return {k: _plain(cfg.get(k)) for k in ("owner", "search", "sites", "discover", "cardb")
                if cfg.get(k) is not None}
    return _plain(_core._raw_config()) or {}


def home() -> Path:
    return _core.home()


def path(*parts: str) -> Path:
    return _core.path(*parts)


def now() -> datetime:
    return _core.now()


def flock(name: str):
    return _core.flock(name)


def pause_file() -> Path:
    try:
        from carhunt.core import paths
        return Path(paths.pause_file())
    except (ImportError, AttributeError):
        return home() / "PAUSE"


def db_client() -> Any:
    """cardb REST client (core's when installed)."""
    try:
        from carhunt.core import db as core_db
    except ImportError:
        core_db = None
    if core_db is not None and hasattr(core_db, "Client"):
        return core_db.Client.from_config(author=_author())
    from carhunt.discover import _cardb
    return _cardb.Client.from_env(config(), author=_author())


def _author() -> str:
    import os
    return os.environ.get("CARDB_AUTHOR") or "discover"


@cache
def data(name: str) -> Any:
    return yaml.safe_load((DATA / f"{name}.yaml").read_text(encoding="utf-8"))
