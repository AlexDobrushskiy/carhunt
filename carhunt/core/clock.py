"""Owner-local time. TZ comes from config `owner.tz` (never hardcoded); CARHUNT_FAKE_NOW pins "now" for tests.

Windows are "HH:MM-HH:MM", start inclusive, end exclusive; start > end crosses midnight ("21:30-09:30").
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

_WINDOW = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)-([01]\d|2[0-3]):([0-5]\d)$")


def tz() -> tzinfo:
    """CARHUNT_TZ > config owner.tz > the system zone."""
    if name := os.environ.get("CARHUNT_TZ"):
        return ZoneInfo(name)
    from carhunt.core import config

    try:
        cfg = config.load_or_none()
    except config.ConfigError:
        cfg = None
    if cfg and (name := cfg.get("owner.tz")):
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def now() -> datetime:
    """Aware datetime in the owner's zone. CARHUNT_FAKE_NOW: ISO 8601; a naive value means owner-local."""
    z = tz()
    if fake := os.environ.get("CARHUNT_FAKE_NOW"):
        t = datetime.fromisoformat(fake)
        return t.replace(tzinfo=z) if t.tzinfo is None else t.astimezone(z)
    return datetime.now(z)


def today() -> date:
    return now().date()


def parse_window(window: str) -> tuple[time, time]:
    m = _WINDOW.match(window.strip())
    if not m:
        raise ValueError(f"bad window {window!r}: want HH:MM-HH:MM")
    a, b = time(int(m[1]), int(m[2])), time(int(m[3]), int(m[4]))
    if a == b:
        raise ValueError(f"empty window {window!r}: start equals end")
    return a, b


def in_window(window: str, at: datetime | None = None) -> bool:
    a, b = parse_window(window)
    t = _local(at).time()
    if a < b:
        return a <= t < b
    return t >= a or t < b


def window_end(window: str, at: datetime | None = None) -> datetime:
    """When the window that contains `at` closes (the next close if `at` is outside)."""
    _, b = parse_window(window)
    t = _local(at)
    end = t.replace(hour=b.hour, minute=b.minute, second=0, microsecond=0)
    return end if end > t else end + timedelta(days=1)


def next_start(window: str, at: datetime | None = None) -> datetime:
    """The next time the window opens (now if `at` is exactly on the start)."""
    a, _ = parse_window(window)
    t = _local(at)
    start = t.replace(hour=a.hour, minute=a.minute, second=0, microsecond=0)
    return start if start >= t else start + timedelta(days=1)


def _local(at: datetime | None) -> datetime:
    if at is None:
        return now()
    return at.replace(tzinfo=tz()) if at.tzinfo is None else at.astimezone(tz())
