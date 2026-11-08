"""WhatsApp via wacli (unofficial whatsmeow CLI, linked device on the owner's number).

- Reads run with WACLI_READONLY=1; only `send` lifts it, and only inside `carhunt say`.
- Never touch wacli's store/session files directly; only the CLI.
- Ban risk: WhatsApp bans spam-shaped bursts from new contacts → the guard's spacing/caps.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from typing import Any, ClassVar

from .base import DELIVERED, FAILED, UNKNOWN, Channel, ChannelError, Msg, SendResult


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def to_msg(m: dict[str, Any]) -> Msg:
    return Msg(
        at=_ts(m["Timestamp"]),
        from_me=bool(m.get("FromMe")),
        text=m.get("Text") or "",
        id=m.get("ID") or m.get("MsgID") or "",
        reaction=m.get("ReactionEmoji") or "",
        media=m.get("MediaType") or "",
        revoked=bool(m.get("Revoked")),
        sender=m.get("SenderJID") or m.get("Sender") or "",
        raw={k: m.get(k) for k in ("ChatJID",)},
    )


class WhatsApp(Channel):
    name: ClassVar[str] = "whatsapp"
    kind: ClassVar[str] = "chat"
    max_len: ClassVar[int] = 500

    def __init__(self, cfg: dict[str, Any] | None = None, *, wacli: str | None = None, **opts: Any):
        super().__init__(cfg, **opts)
        wcfg = ((cfg or {}).get("contact") or {}).get("whatsapp") or {}
        self.wacli = wacli or os.environ.get("CARHUNT_WACLI") or wcfg.get("wacli") or shutil.which("wacli") or "wacli"
        self.account = wcfg.get("account")
        self.default_cc = str(((cfg or {}).get("contact") or {}).get("default_phone_cc") or "")

    def normalize_to(self, to: str) -> str:
        n = "".join(c for c in to if c.isdigit())
        if self.default_cc and len(n) <= 10 and not n.startswith(self.default_cc):
            n = self.default_cc + n  # bare national number
        return n

    def _run(self, args: list[str], *, write: bool = False, timeout: int = 60) -> subprocess.CompletedProcess:
        env = dict(os.environ, WACLI_READONLY="0" if write else "1")
        base = [self.wacli] + (["--account", self.account] if self.account else [])
        try:
            return subprocess.run(base + args, capture_output=True, text=True, env=env, timeout=timeout)
        except OSError as e:
            raise ChannelError(f"wacli not runnable ({e.__class__.__name__}): brew install openclaw/tap/wacli") from e
        except subprocess.TimeoutExpired as e:
            raise ChannelError(f"wacli timed out: {' '.join(args[:3])}") from e

    def read_thread(self, to: str, limit: int = 50) -> list[Msg]:
        r = self._run(["--json", "messages", "list", "--chat", self.normalize_to(to), "--limit", str(limit)])
        if r.returncode != 0:
            raise ChannelError(f"wacli messages list failed: {r.stderr.strip()[-200:]}")
        try:
            raw = (json.loads(r.stdout).get("data") or {}).get("messages") or []
        except json.JSONDecodeError as e:
            raise ChannelError("wacli returned non-JSON") from e
        if raw and "@g.us" in (raw[-1].get("ChatJID") or ""):
            raise ChannelError("group chat: never message a group")
        return sorted((to_msg(m) for m in raw), key=lambda m: m.at)

    def dry_run(self, to: str, text: str) -> dict[str, Any]:
        return {"channel": self.name, "to": "+" + self.normalize_to(to), "text": text,
                "argv": [os.path.basename(self.wacli), "send", "text", "--to", "+" + self.normalize_to(to), "--message", "…"]}

    def send(self, to: str, text: str) -> SendResult:
        r = self._run(["--json", "send", "text", "--to", "+" + self.normalize_to(to), "--message", text], write=True)
        if r.returncode != 0:
            err = r.stderr.strip()[-300:] or "send failed"
            if "no LID found" in err:  # number not on WhatsApp → use the site message instead
                err += " (number not on WhatsApp: use the site's chat)"
            return SendResult(False, error=err)
        mid = ""
        try:
            d = json.loads(r.stdout or "{}")
            mid = (d.get("data") or {}).get("id") or (d.get("data") or {}).get("ID") or d.get("id") or ""
        except json.JSONDecodeError:
            pass
        return SendResult(True, external_id=str(mid))

    def verify(self, to: str, text: str, result: SendResult) -> str:
        """delivered if wacli returned a message id or our text is in the local chat; else unknown."""
        if not result.ok:
            return FAILED
        if result.external_id:
            return DELIVERED
        try:
            thread = self.read_thread(to, limit=10)
        except ChannelError:
            return UNKNOWN
        head = text.strip()[:60]
        return DELIVERED if any(m.from_me and head in m.text for m in thread) else UNKNOWN

    def poll(self, since: datetime) -> list[tuple[str, Msg]]:
        r = self._run(["--json", "messages", "list", "--from-them", "--after", since.isoformat(timespec="seconds"),
                       "--asc", "--limit", "500"])
        if r.returncode != 0:
            raise ChannelError(f"wacli poll failed: {r.stderr.strip()[-200:]}")
        out = []
        for m in (json.loads(r.stdout or "{}").get("data") or {}).get("messages") or []:
            chat = m.get("ChatJID") or ""
            if "@g.us" in chat or "@newsletter" in chat or "status@" in chat:
                continue
            out.append(("".join(c for c in chat.split("@")[0] if c.isdigit()), to_msg(m)))
        return out
