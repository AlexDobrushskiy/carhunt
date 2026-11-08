"""`carhunt watch`: one watcher for every inbound channel (WhatsApp, Gmail, site inboxes).

Each new seller message → cardb (verbatim, original language, idempotent on external id) + one
item in the agent's inbox (core notify inbox) + one line on stdout. The stdout line is the agent's wake-up signal:
- refuses to run with stdout on /dev/null (wake-ups would be lost);
- run as a tracked background task, never `&`; re-arm on any non-zero exit.
One cursor store ($CARHUNT_HOME/contact/cursors.json) for all channels, advanced only after the
message is logged (moving it first can skip a reply).
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from carhunt.core import notify

from . import deps
from .channels import get as get_channel
from .channels.base import Channel, ChannelError, Msg

SEEN_KEEP = 2000


def stdout_is_devnull() -> bool:
    try:
        a, b = os.fstat(sys.stdout.fileno()), os.stat(os.devnull)
    except (OSError, ValueError):
        return False
    return stat.S_ISCHR(a.st_mode) and a.st_rdev == b.st_rdev


class Cursors:
    """{channel: {"since": iso, "seen": [ids]}} — atomic writes under a lock."""

    def __init__(self, path: Path | None = None):
        self.path = path or deps.path("contact", "cursors.json")

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, d: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1))
        os.replace(tmp, self.path)


def _key(channel: str, cp: str, m: Msg) -> str:
    if m.id:
        return m.id
    if m.raw.get("at_parsed") is False:  # site showed no time: `at` is the poll time, so key on text only
        return f"{channel}|{cp}|{hashlib.sha1(m.text.encode()).hexdigest()[:16]}"
    return f"{channel}|{cp}|{m.at.isoformat()}|{m.text[:40]}"


def inbox_path(agent: str) -> Path:
    return notify.inbox(agent).file


def pass_once(channels: list[Channel], *, db: deps.Cardb | None, agent: str, cursors: Cursors,
              now: datetime, lookback: timedelta = timedelta(days=2),
              out: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Poll every channel once; log new inbound messages. Returns the new items."""
    new: list[dict[str, Any]] = []
    with deps.flock("contact-cursors"):
        state = cursors.load()
        for ch in channels:
            cur = state.setdefault(ch.name, {})
            since = datetime.fromisoformat(cur["since"]) if cur.get("since") else now - lookback
            seen = set(cur.get("seen") or [])
            try:
                items = ch.poll(since - timedelta(minutes=5))  # overlap: clocks and late syncs
            except ChannelError as e:
                out(json.dumps({"kind": "watch_error", "channel": ch.name, "error": str(e)[:200]}))
                continue
            newest = since
            for cp, m in sorted(items, key=lambda x: x[1].at):
                k = _key(ch.name, cp, m)
                if m.from_me or k in seen or not m.is_content:
                    seen.add(k)
                    continue
                item = {"kind": "seller_msg", "channel": ch.name, "counterpart": cp, "at": m.at.isoformat(),
                        "text": m.text, "media": m.media or None, "external_id": m.id or None, "car": None}
                if db is not None:
                    try:
                        r = db.msg(channel=ch.name, direction="in", counterpart=cp, text=m.text,
                                   at=m.at.isoformat(), sender_kind="seller", delivery="received",
                                   external_id=m.id or None, dedupe_key=None if m.id else f"watch:{k}",
                                   attachments=[{"kind": "image" if m.media == "image" else "other"}] if m.media else None)
                        item["car"] = (r or {}).get("car_id")
                    except deps.CardbError as e:
                        item["cardb_error"] = str(e)[:160]  # unknown counterpart (new number?) still reaches the agent
                notify.inbox(agent).add({"id": f"{ch.name}:{k}", "source": "contact.watch", **item})
                out(json.dumps(item, ensure_ascii=False))
                new.append(item)
                seen.add(k)
                newest = max(newest, m.at)
            cur["since"] = max(newest, since).isoformat()
            cur["seen"] = list(seen)[-SEEN_KEEP:]
            cursors.save(state)
    return new


def run(args: Any) -> int:
    if stdout_is_devnull():
        print("REFUSED: stdout is /dev/null — the watcher's output is the wake-up signal", file=sys.stderr)
        return 2
    cfg = deps.load_config()
    names = args.channels.split(",") if args.channels else _enabled(cfg)
    chans = []
    for n in names:
        try:
            chans.append(get_channel(n, cfg))
        except ChannelError as e:
            print(json.dumps({"kind": "watch_error", "channel": n, "error": str(e)}), flush=True)
    db = None if args.no_db else deps.Cardb.from_config(cfg)
    agent = args.agent or os.environ.get("CARHUNT_AGENT") or "outreach"
    cursors = Cursors()
    out = lambda s: print(s, flush=True)  # noqa: E731
    while True:
        new = pass_once(chans, db=db, agent=agent, cursors=cursors, now=datetime.now(UTC), out=out)
        if args.once or (args.until_new and new):
            return 0
        time.sleep(args.interval)


def _enabled(cfg: dict[str, Any]) -> list[str]:
    """contact.watch.channels, else the contact.channels list (minus `sites`: site inboxes are named one by one),
    else whatsapp + email."""
    c = cfg.get("contact") or {}
    w = (c.get("watch") or {}).get("channels")
    if w:
        return list(w)
    if isinstance(c.get("channels"), list):
        return [x for x in c["channels"] if x != "sites"]
    return ["whatsapp", "email"]
