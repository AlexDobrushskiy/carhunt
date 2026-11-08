"""Bridge to carhunt.core (config, clock, lock, paths, secrets, cardb client).

Uses carhunt.core when it is importable; otherwise a minimal local fallback with the same
behaviour as design.md, so contact runs and tests before core lands. Drop the fallbacks once
core is merged (tracked in docs/contact.md, "Gaps").
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

try:  # pragma: no cover - exercised once core is merged
    from carhunt.core import clock as _core_clock  # type: ignore
    from carhunt.core import config as _core_config  # type: ignore
    from carhunt.core import db as _core_db  # type: ignore
    from carhunt.core import lock as _core_lock  # type: ignore
    from carhunt.core import paths as _core_paths  # type: ignore
    from carhunt.core import secrets as _core_secrets  # type: ignore
    HAVE_CORE = True
except ImportError:
    HAVE_CORE = False


# ---- paths / config ---------------------------------------------------------------------------

def home() -> Path:
    if HAVE_CORE:
        return Path(_core_config.home())
    return Path(os.environ.get("CARHUNT_HOME") or Path.home() / ".carhunt").expanduser()


def path(*parts: str) -> Path:
    """$CARHUNT_HOME/<parts>, parent dirs created."""
    p = home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def pause_file() -> Path:
    if HAVE_CORE:
        return Path(_core_paths.pause_file())
    return home() / "PAUSE"


def load_config() -> dict[str, Any]:
    """Whole config as a plain dict (core's Config is converted when it has to_dict/as_dict)."""
    if HAVE_CORE:
        cfg = _core_config.load()
        for attr in ("to_dict", "as_dict", "dict"):
            if hasattr(cfg, attr):
                return getattr(cfg, attr)()
        return dict(cfg)
    import yaml

    p = Path(os.environ.get("CARHUNT_CONFIG") or home() / "config.yaml")
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


# ---- clock -----------------------------------------------------------------------------------

def owner_tz(cfg: dict[str, Any]) -> ZoneInfo:
    return ZoneInfo((cfg.get("owner") or {}).get("tz") or "UTC")


def now(cfg: dict[str, Any] | None = None) -> datetime:
    """Aware 'now' in the owner's tz. CARHUNT_FAKE_NOW (ISO) freezes it for tests."""
    tz = owner_tz(cfg or {})
    fake = os.environ.get("CARHUNT_FAKE_NOW")
    if fake:
        dt = datetime.fromisoformat(fake.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz)
    if HAVE_CORE:
        return _core_clock.now().astimezone(tz)
    return datetime.now(timezone.utc).astimezone(tz)


# ---- lock ------------------------------------------------------------------------------------

@contextlib.contextmanager
def flock(name: str) -> Iterator[None]:
    """Exclusive cross-process lock (blocks until free)."""
    if HAVE_CORE:
        with _core_lock.flock(name):
            yield
        return
    p = path("locks", f"{name}.lock")
    with open(p, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---- secrets (never printed) -----------------------------------------------------------------

def secret(name: str) -> str | None:
    if HAVE_CORE:
        try:
            return _core_secrets.get(name)
        except Exception:
            return None
    v = os.environ.get(f"CARHUNT_SECRET_{name.upper()}")
    if v:
        return v
    f = home() / "secrets" / name
    if f.exists():
        return f.read_text().strip()
    r = subprocess.run(["security", "find-generic-password", "-s", "carhunt", "-a", name, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def resolve(value: Any) -> Any:
    """'secret:NAME' -> secret value; anything else unchanged."""
    if isinstance(value, str) and value.startswith("secret:"):
        return secret(value[len("secret:"):])
    return value


# ---- cardb -----------------------------------------------------------------------------------

class CardbError(Exception):
    pass


class CardbNotFound(CardbError):
    pass


class Cardb:
    """The few cardb calls contact needs. Wraps core's db.Client when present, else plain REST."""

    def __init__(self, url: str, token: str | None, author: str | None = None):
        self.url, self.token, self.author = url.rstrip("/"), token, author

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Cardb":
        c = cfg.get("cardb") or {}
        url = os.environ.get("CARDB_URL") or c.get("url") or "http://127.0.0.1:8484"
        token = os.environ.get("CARHUNT_SECRET_CARDB_TOKEN") or resolve(c.get("token", "secret:cardb_token"))
        return cls(url, token, os.environ.get("CARDB_AUTHOR"))

    def _req(self, method: str, p: str, body: dict | None = None, query: dict | None = None) -> Any:
        u = self.url + p + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(u, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise CardbNotFound(p) from e
            raise CardbError(f"{method} {p}: HTTP {e.code} {e.read()[:200]!r}") from e
        except (urllib.error.URLError, OSError) as e:
            raise CardbError(f"{method} {p}: {e}") from e
        return json.loads(raw) if raw else None

    def car(self, car: str) -> dict:
        return self._req("GET", f"/cars/{urllib.parse.quote(str(car))}")

    def find_listing(self, url: str) -> dict | None:
        r = self._req("GET", "/listings", query={"url": url}) or []
        return r[0] if r else None

    def msgs(self, car: str) -> list[dict]:
        r = self._req("GET", f"/cars/{urllib.parse.quote(str(car))}/messages")
        return r.get("messages", r) if isinstance(r, dict) else (r or [])

    def msg(self, **fields: Any) -> dict:
        body = {k: v for k, v in fields.items() if v is not None}
        if self.author and "author" not in body:
            body["author"] = self.author
        return self._req("POST", "/messages", body)

    def events(self, car: str) -> list[dict]:
        r = self._req("GET", f"/cars/{urllib.parse.quote(str(car))}/events")
        return r.get("events", r) if isinstance(r, dict) else (r or [])

    def event(self, car: str, **fields: Any) -> dict:
        body = {k: v for k, v in fields.items() if v is not None}
        if self.author and "author" not in body:
            body["author"] = self.author
        return self._req("POST", f"/cars/{urllib.parse.quote(str(car))}/events", body)

    def cars(self, **filters: Any) -> list[dict]:
        r = self._req("GET", "/cars", query={k: v for k, v in filters.items() if v is not None})
        return r.get("cars", r) if isinstance(r, dict) else (r or [])

    def activity(self, since: str, limit: int = 500) -> list[dict]:
        r = self._req("GET", "/activity", query={"since": since, "limit": limit})
        return r.get("items", r) if isinstance(r, dict) else (r or [])
