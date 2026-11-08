"""The few carhunt.core calls the access layer uses, in one place.

No config file yet → empty sections, so the browser tools work before `scripts/bootstrap`.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from carhunt.core import clock, config, lock, paths, secrets


def home() -> Path:
    return paths.home()


def path(*parts: str) -> Path:
    """Path under $CARHUNT_HOME; parent directories are created."""
    return paths.path(*parts)


def section(name: str) -> dict:
    """One top-level config section as a plain dict ({} when absent or no config yet)."""
    cfg = config.load_or_none()
    if cfg is None:
        return {}
    return dict(cfg.as_dict().get(name) or {})  # secret refs stay "secret:NAME" strings


def secret(name: str) -> str | None:
    """Secret value or None. Never print the result."""
    try:
        return secrets.get(name)
    except secrets.SecretNotFound:
        return None


def set_secret(name: str, value: str) -> str:
    """Store in the configured backend; returns the backend name."""
    return secrets.set(name, value)


def secret_exists(name: str) -> bool:
    return bool(secrets.exists(name))


def tz():
    return clock.tz()


def now() -> datetime:
    """Aware now in owner.tz (CARHUNT_FAKE_NOW honoured by core.clock)."""
    return clock.now()


@contextlib.contextmanager
def flock(name: str) -> Iterator[None]:
    with lock.flock(name):
        yield
