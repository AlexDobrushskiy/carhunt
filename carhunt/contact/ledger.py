"""One append-only JSONL ledger for every outgoing send, all channels and agents.

Every row is a send attempt (status sent|failed|unknown). Guards read it for spacing, caps and
duplicates; `carhunt ledger reconcile` re-posts rows to cardb (idempotent on the row id).
Why one ledger: the EV run had two (sends.log + prose log.md) and the guards disagreed.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import deps

SENT, FAILED, UNKNOWN = "sent", "failed", "unknown"


@dataclass
class Entry:
    channel: str
    to: str
    text: str
    status: str
    t: float  # unix time of the attempt
    car: str | None = None
    kind: str = "reply"  # opener | reply | nudge | approved | ask
    by: str = ""  # agent role / session
    err: str = ""
    external_id: str = ""
    id: str = field(default_factory=lambda: "")

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"snd:{self.t:.3f}:{uuid.uuid4().hex[:8]}"

    @property
    def counts(self) -> bool:
        """Sent or possibly sent: counts for spacing, caps and duplicates. A failed attempt doesn't
        (EV: a failed send stamped a false 20-min block, 2026-11-03)."""
        return self.status in (SENT, UNKNOWN)

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.t, timezone.utc)


def default_path() -> Path:
    return deps.path("contact", "ledger.jsonl")


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_path()

    def entries(self) -> list[Entry]:
        return list(self.iter())

    def iter(self) -> Iterator[Entry]:
        if not self.path.exists():
            return
        known = set(Entry.__dataclass_fields__)
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a torn line never blocks the guard
                yield Entry(**{k: v for k, v in d.items() if k in known})

    def append(self, e: Entry) -> Entry:
        """Append one row (one write() call + fsync; callers hold the send lock)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(e), ensure_ascii=False) + "\n"
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return e


def reconcile(ledger: Ledger, db: "deps.Cardb", *, since: float = 0.0) -> dict[str, int]:
    """Post every ledger row to cardb (dedupe key = row id, so re-runs write nothing new)."""
    out = {"posted": 0, "skipped": 0, "errors": 0}
    for e in ledger.iter():
        if e.t < since or not e.car:
            out["skipped"] += 1
            continue
        try:
            log_to_db(db, e)
            out["posted"] += 1
        except Exception:
            out["errors"] += 1
    return out


def log_to_db(db: "deps.Cardb", e: Entry) -> dict:
    return db.msg(
        car=e.car,
        counterpart=e.to,
        channel=e.channel,
        direction="out",
        at=e.at.isoformat(timespec="seconds"),
        sender_kind="agent",
        sender=e.by or None,
        text=e.text,
        delivery=e.status,
        error=e.err or None,
        external_id=e.external_id or None,
        dedupe_key=e.id,
    )
