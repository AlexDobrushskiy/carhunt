"""Where the last sweep stopped, per site and query. State: `$CARHUNT_HOME/discover/cursors.json`.

Strategies (config `discover.cursor.<site>`, else site.yaml `cursor`, else `first_seen`):
- `newest_id`: numeric ids, newest first. A card is new iff id > the stored max for its id width; paging stops at the
  first organic card at/below it. Widths are tracked separately (mobile.de has two id widths: 14-digit mirrors).
- `first_seen`: newest-first lists with opaque ids (AS24 UUIDs). Per query: the first organic in-filter id of the last
  run + its created timestamp; paging stops on that id or on an organic card created at/before the boundary.
- `full`: relevance-sorted lists (coches.net): no stop point — every page up to the query's page cap, every run.

Rules:
- Sponsored / out-of-filter cards never set or match a cursor — promoted rows violate filters.
- The cursor stop check runs before the "already in cardb" check, so an ingested cursor card still stops paging.
- Commit only after a query finished without a block: a blocked run repeats from the old cursor next time.
- Commit merges per query: a query that saw no eligible card keeps its old cursor.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from carhunt.sites.model import Card

STRATEGIES = ("newest_id", "first_seen", "full")


def strategy_for(site_meta: dict, disc_cfg: dict) -> str:
    """Config `discover.cursor.<site>` (override) > site.yaml `cursor.strategy` > `first_seen`."""
    s = (disc_cfg.get("cursor") or {}).get(site_meta.get("site"))
    s = s or (site_meta.get("cursor") or {}).get("strategy") or "first_seen"
    if s not in STRATEGIES:
        raise ValueError(f"unknown cursor strategy {s!r} (known: {', '.join(STRATEGIES)})")
    return s


def _ts(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def _num(ref: str) -> int | None:
    d = re.sub(r"\D", "", ref or "")
    return int(d) if d else None


class Store:
    """cursors.json: {site: {query_key: {...}}}. Atomic writes; callers hold the sweep lock."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, dict]] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, site: str, key: str) -> dict:
        return dict(self.data.get(site, {}).get(key) or {})

    def put(self, site: str, key: str, value: dict) -> None:
        self.data.setdefault(site, {})[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cursors.")
        with os.fdopen(fd, "w") as fh:
            json.dump(self.data, fh, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


@dataclass
class Cursor:
    """One query's cursor during a run. `stop(card)` → paging should end; `new(card)` → card not seen before."""
    strategy: str
    old: dict
    eligible: Any = None                        # callable(card) → bool: organic + inside the query filter
    head: dict | None = None                    # first eligible card this run (first_seen)
    widths: dict[str, int] = field(default_factory=dict)   # newest_id: width → max id this run

    def _eligible(self, card: Card) -> bool:
        return not card.sponsored and (self.eligible(card) if self.eligible else True)

    def stop(self, card: Card) -> bool:
        if not self._eligible(card):
            return False
        if self.strategy == "first_seen":
            if self.old.get("first_id") and card.site_ref == self.old["first_id"]:
                return True
            boundary, created = _ts(self.old.get("created")), _ts(card.created)
            return bool(boundary and created and created <= boundary)
        if self.strategy == "newest_id":
            n = _num(card.site_ref)
            cut = (self.old.get("max_id_by_width") or {}).get(str(len(str(n)))) if n is not None else None
            return cut is not None and n <= int(cut)
        return False

    def new(self, card: Card) -> bool:
        """Only meaningful for newest_id (others rely on stop + cardb lookups)."""
        if self.strategy != "newest_id":
            return True
        n = _num(card.site_ref)
        cut = (self.old.get("max_id_by_width") or {}).get(str(len(str(n)))) if n is not None else None
        return cut is None or n > int(cut)

    def observe(self, card: Card) -> None:
        if not self._eligible(card):
            return
        if self.strategy == "first_seen" and self.head is None:
            self.head = {"first_id": card.site_ref, "created": card.created}
        elif self.strategy == "newest_id":
            n = _num(card.site_ref)
            if n is not None:
                w = str(len(str(n)))
                self.widths[w] = max(self.widths.get(w, 0), n)

    def committed(self, at: str) -> dict:
        """The value to store after a clean query; merges with the old cursor."""
        out = dict(self.old)
        out["last_run"] = at
        if self.strategy == "first_seen" and self.head:
            out.update(first_id=self.head["first_id"], created=self.head.get("created") or at)
        if self.strategy == "newest_id" and self.widths:
            merged = dict(out.get("max_id_by_width") or {})
            for w, n in self.widths.items():
                merged[w] = max(int(merged.get(w, 0)), n)
            out["max_id_by_width"] = merged
        return out
