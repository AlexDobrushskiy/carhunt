"""Owner notifications: `send(text, agent=, kind=)` and per-agent `inbox(agent)` for the answers.

Telegram replies come back by reply-to message id (or button press) to the agent that sent the ping;
an unthreaded line goes to `notify.default_agent` (default `overseer`).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from carhunt.core import clock, config, lock, paths
from carhunt.core.notify.backends import NoneBackend, NotifyError, StdoutBackend, TelegramBackend
from carhunt.core.notify.inbox import Inbox
from carhunt.core.notify.policy import KINDS, Refused, check, quiet_mode

__all__ = ["send", "deliver", "flush", "poll", "inbox", "Inbox", "Result", "Refused", "NotifyError", "KINDS",
           "TelegramBackend"]


@dataclass
class Result:
    status: str  # sent | held | dropped
    ref: str | None = None
    until: datetime | None = None
    silent: bool = False


def _cfg() -> config.Config | None:
    return config.load_or_none()


def _state(name: str):
    return paths.path("notify", name)


def backend(cfg: config.Config | None = None):
    cfg = cfg if cfg is not None else _cfg()
    kind = os.environ.get("CARHUNT_NOTIFY_BACKEND") or (cfg.get("notify.backend") if cfg else None) or "none"
    if kind == "stdout":
        return StdoutBackend()
    if kind == "none":
        return NoneBackend()
    if kind == "telegram":
        if cfg is None:
            raise NotifyError("notify.backend telegram needs a config")
        api = os.environ.get("CARHUNT_TELEGRAM_API") or cfg.get("notify.telegram.api_base") or "https://api.telegram.org"
        try:
            return TelegramBackend(cfg.secret("notify.telegram.bot_token"), cfg.secret("notify.telegram.chat_id"), api)
        except (config.ConfigError, KeyError) as e:
            raise NotifyError(f"telegram not configured: {e}") from None
    raise NotifyError(f"unknown notify backend {kind!r}")


def _record_sent(ids: list[int], agent: str, kind: str, text: str, buttons: list[str] | None) -> None:
    with lock.flock("notify-sent"), _state("sent.jsonl").open("a") as fh:
        fh.write(json.dumps({"ids": ids, "agent": agent, "kind": kind, "buttons": buttons or [],
                             "text": text[:200], "ts": clock.now().isoformat(timespec="seconds")},
                            ensure_ascii=False) + "\n")


def _lookup_sent(message_id: int) -> dict | None:
    f = _state("sent.jsonl")
    if not f.exists():
        return None
    for line in reversed(f.read_text().splitlines()):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if message_id in rec.get("ids", []):
            return rec
    return None


def _transmit(b, text: str, agent: str, kind: str, buttons: list[str] | None, ask: bool, silent: bool) -> Result:
    if isinstance(b, NoneBackend):
        return Result("dropped")
    ids = b.send(text, silent=silent, buttons=buttons, ask=ask)
    if b.name == "telegram":
        _record_sent(ids, agent, kind, text, buttons)
    return Result("sent", f"{b.name}:{ids[-1]}" if ids else None, silent=silent)


def deliver(text: str, *, agent: str, kind: str, buttons: list[str] | None = None, ask: bool = False,
            cfg: config.Config | None = None) -> Result:
    """Policy check -> quiet hours (hold or silent) -> backend. Raises Refused or NotifyError."""
    paths.safe_name(agent, "agent")
    check(text, kind, buttons)
    ask = ask or (kind == "ask" and not buttons)
    cfg = cfg if cfg is not None else _cfg()
    b = backend(cfg)
    quiet = cfg.get("notify.quiet_hours") if cfg else None
    silent = False
    if quiet and clock.in_window(quiet):
        if quiet_mode(kind, cfg.get("notify.quiet") if cfg else None) == "hold":
            until = clock.window_end(quiet)
            with lock.flock("notify-held"), _state("held.jsonl").open("a") as fh:
                fh.write(json.dumps({"text": text, "agent": agent, "kind": kind, "buttons": buttons, "ask": ask,
                                     "until": until.isoformat()}, ensure_ascii=False) + "\n")
            return Result("held", until=until)
        silent = True
    else:
        flush(cfg)
    return _transmit(b, text, agent, kind, buttons, ask, silent)


def send(text: str, *, agent: str, kind: str, buttons: list[str] | None = None, ask: bool = False) -> str | None:
    """Design API: the message ref (`telegram:<id>`), or None when held / dropped."""
    return deliver(text, agent=agent, kind=kind, buttons=buttons, ask=ask).ref


def flush(cfg: config.Config | None = None) -> int:
    """Send held messages whose quiet window is over. Returns how many went out."""
    f = _state("held.jsonl")
    if not f.exists():
        return 0
    cfg = cfg if cfg is not None else _cfg()
    now = clock.now()
    with lock.flock("notify-held"):
        items = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        due = [i for i in items if datetime.fromisoformat(i["until"]) <= now]
        if not due:
            return 0
        b = backend(cfg)
        left = [i for i in items if i not in due]
        sent = 0
        try:
            for i in due:
                _transmit(b, i["text"], i["agent"], i["kind"], i.get("buttons"), i.get("ask", False), False)
                sent += 1
        finally:
            left += due[sent:]
            f.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in left))
    return sent


def _route(u: dict, b: TelegramBackend, default_agent: str) -> tuple[str, dict] | None:
    uid = u["update_id"]
    if cq := u.get("callback_query"):
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != b.chat_id:
            return None
        rec = _lookup_sent(msg.get("message_id", -1))
        labels = (rec or {}).get("buttons") or []
        data = cq.get("data", "")
        label = labels[int(data)] if data.isdigit() and int(data) < len(labels) else data
        b.answer_callback(cq.get("id", ""), label)
        return ((rec or {}).get("agent") or default_agent,
                {"id": f"tg-{uid}", "source": "telegram", "kind": "button", "text": label,
                 "re": f"telegram:{msg.get('message_id')}", "re_text": (rec or {}).get("text", "")[:80]})
    msg = u.get("message")
    if not msg or str((msg.get("chat") or {}).get("id")) != b.chat_id:
        return None  # only the configured chat may talk to agents
    text = msg.get("text") or msg.get("caption")
    if text is None:
        media = next((k for k in ("voice", "photo", "document", "audio", "video", "sticker") if k in msg), "other")
        text = f"[{media} message: open Telegram to see it]"
    item = {"id": f"tg-{uid}", "source": "telegram", "kind": "text", "text": text}
    agent = default_agent
    if reply := msg.get("reply_to_message"):
        rec = _lookup_sent(reply.get("message_id", -1))
        item["re"] = f"telegram:{reply.get('message_id')}"
        if rec:
            agent = rec["agent"]
            item["re_text"] = rec.get("text", "")[:80]
    return agent, item


def poll(timeout: int = 25, *, wait_lock: float | None = 0, cfg: config.Config | None = None) -> int:
    """One getUpdates round: route each owner line to its agent inbox. Returns items added.

    One poller at a time (flock `notify-poll`; Telegram also refuses parallel getUpdates).
    wait_lock=0 raises lock.LockTimeout at once if another process is polling.
    """
    cfg = cfg if cfg is not None else _cfg()
    b = backend(cfg)
    if not isinstance(b, TelegramBackend):
        return 0
    default_agent = (cfg.get("notify.default_agent") if cfg else None) or "overseer"
    with lock.flock("notify-poll", timeout=wait_lock):
        off_f = _state("offset")
        offset = int(off_f.read_text()) if off_f.exists() and off_f.read_text().strip() else None
        added = 0
        for u in b.updates(offset, timeout):
            routed = _route(u, b, default_agent)
            if routed and Inbox(routed[0]).add(routed[1]):
                added += 1
            off_f.write_text(str(u["update_id"] + 1))
        return added


def inbox(agent: str) -> Inbox:
    return Inbox(agent)
