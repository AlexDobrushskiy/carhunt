"""Per-agent inbox: $CARHUNT_HOME/agents/<agent>/inbox.jsonl (append-only) + inbox.acked (one id per line).

Writers: the Telegram poller (owner replies), contact's watcher, anything with a line for an agent.
Item: {id, ts, source, kind, text, re?, re_text?, ...}. Ids are unique per inbox; a repeated id is ignored.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from carhunt.core import clock, lock, paths


class Inbox:
    def __init__(self, agent: str):
        self.agent = paths.safe_name(agent, "agent")

    @property
    def dir(self) -> Path:
        return paths.agent_dir(self.agent)

    @property
    def file(self) -> Path:
        return self.dir / "inbox.jsonl"

    @property
    def acked_file(self) -> Path:
        return self.dir / "inbox.acked"

    def _items(self) -> list[dict]:
        if not self.file.exists():
            return []
        out = []
        for line in self.file.read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue  # a torn line from a crash must not hide the rest
        return out

    def _acked(self) -> set:
        return set(self.acked_file.read_text().split()) if self.acked_file.exists() else set()

    def add(self, item: dict[str, Any]) -> bool:
        """Append; False if an item with this id is already there."""
        if not item.get("id"):
            raise ValueError("inbox item needs an id")
        item = {"ts": clock.now().isoformat(timespec="seconds"), **item}
        with lock.flock(f"inbox-{self.agent}"):
            if any(i.get("id") == item["id"] for i in self._items()):
                return False
            with self.file.open("a") as fh:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")
        return True

    def list(self, *, unacked: bool = True) -> list[dict]:
        items, acked = self._items(), self._acked()
        return [i for i in items if not (unacked and i.get("id") in acked)]

    def ack(self, *ids: str) -> list[str]:
        """Mark items handled; returns the ids that were not in the inbox."""
        with lock.flock(f"inbox-{self.agent}"):
            known = {i.get("id") for i in self._items()}
            done = self._acked()
            new = [i for i in ids if i in known and i not in done]
            if new:
                with self.acked_file.open("a") as fh:
                    fh.write("".join(f"{i}\n" for i in new))
        return [i for i in ids if i not in known]

    def wait(self, timeout: float | None = None, *, poll: bool = True, interval: float = 2.0) -> list[dict]:
        """Block until there is an unacked item (returns them) or timeout (returns []).

        poll=True: while waiting, this process drives the Telegram poller when no one else holds it,
        so a waiting agent needs no separate daemon.
        """
        from carhunt.core import notify

        deadline = None if timeout is None else time.monotonic() + timeout
        if poll:
            try:
                poll = isinstance(notify.backend(), notify.TelegramBackend)
            except notify.NotifyError:
                poll = False  # misconfigured telegram: still watch the file (other writers)
        while True:
            if items := self.list():
                return items
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                return []
            step = 25 if left is None else max(1, min(25, int(left)))
            polled = False
            if poll:
                try:
                    notify.poll(timeout=step, wait_lock=0)
                    polled = True
                except lock.LockTimeout:
                    pass
                except notify.NotifyError:
                    pass  # transient network trouble: keep waiting, try again next round
            if not polled:
                time.sleep(min(interval, left) if left is not None else interval)
