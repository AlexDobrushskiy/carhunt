"""Thin bridge to carhunt.core (config, secrets, clock, lock).

Uses carhunt.core when it is installed; until core lands on main it falls back to the
documented contract (env CARHUNT_HOME / CARHUNT_CONFIG / CARHUNT_SECRET_<NAME> /
CARHUNT_FAKE_NOW). Remove the fallbacks once core is merged.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Iterator, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _core(name: str):
    try:
        return __import__(f"carhunt.core.{name}", fromlist=[name])
    except ImportError:
        return None


def home() -> Path:
    cfg = _core("config")
    if cfg is not None and hasattr(cfg, "home"):
        return Path(cfg.home())
    return Path(os.environ.get("CARHUNT_HOME") or "~/.carhunt").expanduser()


def path(*parts: str) -> Path:
    """Path under $CARHUNT_HOME; parent directories are created."""
    p = home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _raw_config() -> Any:
    cfg = _core("config")
    if cfg is not None and hasattr(cfg, "load"):
        return cfg.load()
    f = Path(os.environ.get("CARHUNT_CONFIG") or home() / "config.yaml").expanduser()
    if not f.exists():
        return {}
    import yaml
    return yaml.safe_load(f.read_text()) or {}


def section(name: str) -> dict:
    """One top-level config section as a plain dict ({} when absent)."""
    cfg = _raw_config()
    val = cfg.get(name) if isinstance(cfg, Mapping) else getattr(cfg, name, None)
    if val is None:
        return {}
    if isinstance(val, Mapping):
        return dict(val)
    return dict(vars(val))


def secret(name: str) -> str | None:
    """Secret value or None. Never print the result."""
    s = _core("secrets")
    if s is not None and hasattr(s, "get"):
        try:
            return s.get(name)
        except Exception:  # missing secret → None, same as env lookup
            return None
    return os.environ.get(f"CARHUNT_SECRET_{name.upper()}")


def secret_exists(name: str) -> bool:
    s = _core("secrets")
    if s is not None and hasattr(s, "exists"):
        return bool(s.exists(name))
    return f"CARHUNT_SECRET_{name.upper()}" in os.environ


def tz() -> ZoneInfo:
    return ZoneInfo(section("owner").get("tz") or "UTC")


def now() -> datetime:
    """Timezone-aware now in owner.tz; CARHUNT_FAKE_NOW (ISO) overrides for tests."""
    c = _core("clock")
    if c is not None and hasattr(c, "now"):
        return c.now()
    fake = os.environ.get("CARHUNT_FAKE_NOW")
    if fake:
        dt = datetime.fromisoformat(fake)
        return dt if dt.tzinfo else dt.replace(tzinfo=tz())
    return datetime.now(tz())


@contextlib.contextmanager
def flock(name: str) -> Iterator[None]:
    """Exclusive cross-process file lock under $CARHUNT_HOME/locks/."""
    lk = _core("lock")
    if lk is not None and hasattr(lk, "flock"):
        with lk.flock(name):
            yield
        return
    p = path("locks", f"{name}.lock")
    with open(p, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
