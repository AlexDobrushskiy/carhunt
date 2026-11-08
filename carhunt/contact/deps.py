"""contact's view of carhunt.core: config as a plain dict, owner-tz clock, lock, paths, secrets,
and the cardb client with the few helpers contact needs."""
from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from carhunt.core import clock, config, lock, paths, secrets
from carhunt.core import db as _db

CardbError = _db.ApiError
CardbNotFound = _db.NotFound


def home() -> Path:
    return paths.home()


def path(*parts: str) -> Path:
    """$CARHUNT_HOME/<parts>, parent dirs created."""
    p = paths.home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def pause_file() -> Path:
    return paths.pause_file()


def load_config() -> dict[str, Any]:
    cfg = config.load_or_none()
    return cfg.as_dict() if cfg else {}


def owner_tz(cfg: dict[str, Any]) -> Any:
    name = (cfg.get("owner") or {}).get("tz")
    return ZoneInfo(name) if name else clock.tz()


def now(cfg: dict[str, Any] | None = None) -> datetime:
    """core clock (CARHUNT_FAKE_NOW aware), in the owner tz of `cfg` when given."""
    return clock.now().astimezone(owner_tz(cfg or {}))


@contextlib.contextmanager
def flock(name: str) -> Iterator[None]:
    with lock.flock(name):
        yield


def secret(name: str) -> str | None:
    """Value or None. Never printed."""
    try:
        return secrets.get(name)
    except Exception:  # SecretNotFound or a backend error: treat as missing
        return None


def resolve(value: Any) -> Any:
    """'secret:NAME' -> secret value; anything else unchanged."""
    if isinstance(value, str) and value.startswith("secret:"):
        return secret(value[len("secret:"):])
    return value


def _items(res: Any, key: str) -> list[dict]:
    if isinstance(res, dict):
        return res.get("items") or res.get(key) or []
    return res or []


class Cardb(_db.Client):
    """core's cardb client + list-normalising helpers used by contact."""

    @classmethod
    def from_config(cls, cfg: Any = None, **kw: Any) -> "Cardb":
        import os

        c = (cfg or {}).get("cardb") or {} if isinstance(cfg, dict) else {}
        url = os.environ.get("CARDB_URL") or c.get("url") or "http://127.0.0.1:8484"
        token = resolve(c["token"]) if c.get("token") else secret("cardb_token")
        return cls(url, token, author=kw.pop("author", None) or os.environ.get("CARDB_AUTHOR"), **kw)

    def find_listing(self, url: str | None = None, **kw: Any) -> dict | None:  # type: ignore[override]
        try:
            return super().find_listing(url, **kw)
        except _db.NotFound:
            return None

    def msgs(self, car: int | str) -> list[dict]:  # type: ignore[override]
        return _items(super().msgs(car), "messages")

    def events(self, car: int | str) -> list[dict]:  # type: ignore[override]
        return _items(super().events(car), "events")

    def cars(self, **filters: Any) -> list[dict]:  # type: ignore[override]
        return _items(super().cars(**filters), "cars")
