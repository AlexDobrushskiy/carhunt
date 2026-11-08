"""Attempt log (SQLite, $CARHUNT_HOME/access/captcha.sqlite): success rates + the per-site budget."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from carhunt.access import _core


class AttemptLog:
    def __init__(self, path: Path | None = None):
        if path is None:
            from .config import db_path
            path = db_path()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _con(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.execute("""create table if not exists attempts (
            ts real, site text, url text, kind text, input text, method text, outcome text,
            duration real, attempt int, detail text, screenshot text)""")
        return c

    def record(self, site: str, url: str, kind: str, input: str, method: str, outcome: str,
               duration: float, attempt: int, detail: dict | None = None, screenshot: str | None = None) -> None:
        """attempt=0 marks a detection / wait (not counted by the budget)."""
        with self._con() as c:
            c.execute("insert into attempts values (?,?,?,?,?,?,?,?,?,?,?)",
                      (_core.now().timestamp(), site, url, kind, input, method, outcome, round(duration, 2), attempt,
                       json.dumps(detail or {}, default=str)[:4000], screenshot))

    def recent(self, site: str, seconds: float) -> int:
        """Real solve attempts (attempt > 0) on this site in the last `seconds`."""
        with self._con() as c:
            return c.execute("select count(*) from attempts where site=? and ts>? and attempt>0",
                             (site, _core.now().timestamp() - seconds)).fetchone()[0]

    def budget_left(self, site: str, limit: int, window_h: float) -> int:
        return max(0, limit - self.recent(site, window_h * 3600))

    def stats(self) -> list[tuple]:
        with self._con() as c:
            return c.execute("""select site, kind, input, method, outcome, count(*), round(avg(duration),1),
                                max(datetime(ts,'unixepoch')) from attempts group by 1,2,3,4,5
                                order by 1,2,3,4,5""").fetchall()
