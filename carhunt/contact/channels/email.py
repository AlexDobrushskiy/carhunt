"""Email channel over the Gmail API.

Addressing (`to`):
- `addr`        → reply into the latest thread with that address, or a new thread if none.
- `addr#THREAD` → reply into that Gmail thread, to addr.
- `#THREAD`     → reply into that thread; recipient = the last inbound Reply-To/From (our own last
                  message → its To).
Per-send options (channel opts): `subject` (needed for a new thread), `new_thread=True` (don't
reuse the latest thread, e.g. a second car at the same dealer), `cc=[...]`, `attach=[paths]`.

Outgoing mail sets Reply-To to the plus-address (`local+<plus_tag>@domain`) so seller replies
match a Gmail filter and skip the inbox; the sent message gets `sent_label` so later replies in the
thread follow it (mailroute).
Searches never use `in:inbox`: car mail is moved out of it.
"""
from __future__ import annotations

import mimetypes
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, getaddresses, make_msgid, parseaddr
from pathlib import Path
from typing import Any, ClassVar

from .. import deps
from ..gmail import Gmail, GmailError, GmailHTTPError, GmailNetworkError, body_text, headers_of
from .base import DELIVERED, FAILED, UNKNOWN, Channel, ChannelError, Msg, SendResult

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
REPLY_PREFIX = ("re:", "aw:", "r:", "rif:", "sv:", "vs:", "res:", "antw:", "odp:")
THREAD_HEADERS = ("From", "To", "Cc", "Reply-To", "Subject", "Message-ID", "References", "Delivered-To")


def addrs_in(value: str) -> list[str]:
    return [a.lower() for a in EMAIL_RE.findall(value or "")]


def plus_address(addr: str, tag: str) -> str:
    if not tag or "@" not in addr:
        return ""
    local, dom = addr.split("@", 1)
    return f"{local.split('+')[0]}+{tag}@{dom}".lower()


def split_to(to: str) -> tuple[str, str]:
    """'addr#thread' → (addr, thread); either part may be empty."""
    to = to.strip().removeprefix("mailto:")
    addr, _, tid = to.partition("#")
    return parseaddr(addr)[1].lower() if addr else "", tid.strip()


class Email(Channel):
    name: ClassVar[str] = "email"
    kind: ClassVar[str] = "email"
    max_len: ClassVar[int] = 4000

    def __init__(self, cfg: dict[str, Any] | None = None, *, gmail: Gmail | None = None,
                 sleep: Callable[[float], None] = time.sleep, **opts: Any):
        super().__init__(cfg, **opts)
        self.ecfg: dict[str, Any] = ((self.cfg.get("contact") or {}).get("email") or {})
        self._gmail = gmail
        self._sleep = sleep
        self._label_ids: dict[str, str] = {}

    # -- config ---------------------------------------------------------------------------------
    @property
    def gmail(self) -> Gmail:
        if self._gmail is None:
            self._gmail = Gmail.from_config(self.cfg)
        return self._gmail

    @property
    def me(self) -> str:
        a = deps.resolve(self.ecfg.get("from_address") or "")
        if not a:
            raise ChannelError("contact.email.from_address is not set")
        return a.lower()

    @property
    def plus(self) -> str:
        return plus_address(self.me, self.ecfg.get("plus_tag", ""))

    @property
    def label(self) -> str:
        return self.ecfg.get("label") or "cars"

    @property
    def sent_label(self) -> str:
        return self.ecfg.get("sent_label") or self.label

    def is_me(self, addr: str) -> bool:
        a = addr.lower()
        if "@" not in a:
            return False
        local, dom = a.split("@", 1)
        me_local, me_dom = self.me.split("@", 1)
        return dom == me_dom and local.split("+")[0] == me_local.split("+")[0]

    def normalize_to(self, to: str) -> str:
        addr, tid = split_to(to)
        return addr + (f"#{tid}" if tid else "")

    # -- thread lookup (read-only) --------------------------------------------------------------
    def latest_thread(self, addr: str) -> str | None:
        r = self.gmail.list_messages(f"{{from:{addr} to:{addr} cc:{addr}}}", limit=1)
        return r[0]["threadId"] if r else None

    def _thread_msgs(self, tid: str, fmt: str = "metadata") -> list[dict]:
        t = self.gmail.get_thread(tid, fmt=fmt, headers=THREAD_HEADERS if fmt == "metadata" else ())
        return sorted(t.get("messages", []), key=lambda m: int(m.get("internalDate", 0)))

    def _reply_context(self, to: str) -> dict[str, Any]:
        """Thread id, threading headers, subject and recipient for `to` (read-only calls only)."""
        addr, tid = split_to(to)
        if not tid and addr and not self.opts.get("new_thread"):
            tid = self.latest_thread(addr) or ""
        ctx: dict[str, Any] = {"to": [addr] if addr else [], "thread": tid or None}
        if not tid:
            return ctx
        msgs = self._thread_msgs(tid)
        if not msgs:
            raise ChannelError(f"thread {tid} not found")
        first, last = headers_of(msgs[0]), headers_of(msgs[-1])
        ctx["subject"] = first.get("subject", "")
        if last.get("message-id"):
            ctx["in_reply_to"] = last["message-id"]
            ctx["references"] = (last.get("references", "") + " " + last["message-id"]).strip()
        if not addr:
            if "SENT" in msgs[-1].get("labelIds", []):
                cand = [a for _, a in getaddresses([last.get("to", "")]) if a]
            else:
                cand = [a for _, a in getaddresses([last.get("reply-to") or last.get("from", "")]) if a]
            ctx["to"] = [a.lower() for a in cand if not self.is_me(a)] or [a.lower() for a in cand]
        return ctx

    # -- compose --------------------------------------------------------------------------------
    def compose(self, to: str, text: str, ctx: dict[str, Any]) -> EmailMessage:
        if not ctx["to"]:
            raise ChannelError(f"no recipient for {to!r}")
        subject = self.opts.get("subject")
        if ctx.get("thread"):
            s = ctx.get("subject") or subject or ""
            subject = s if s.lower().startswith(REPLY_PREFIX) else "Re: " + s
        elif not subject:
            raise ChannelError(f"new email thread to {ctx['to'][0]} needs a subject (--subject)")
        m = EmailMessage()
        m["From"] = formataddr((self.ecfg.get("from_name") or "", self.me))
        if self.plus:
            m["Reply-To"] = self.plus
        m["To"] = ", ".join(ctx["to"])
        if self.opts.get("cc"):
            m["Cc"] = ", ".join(self.opts["cc"])
        m["Subject"] = subject
        m["Message-ID"] = make_msgid(domain=self.me.split("@", 1)[1])
        if ctx.get("in_reply_to"):
            m["In-Reply-To"] = ctx["in_reply_to"]
            m["References"] = ctx["references"]
        m.set_content(text)
        for f in self.opts.get("attach") or []:
            p = Path(f)
            if not p.is_file():
                raise ChannelError(f"attachment not found: {f}")
            maj, sub = (mimetypes.guess_type(p.name)[0] or "application/octet-stream").split("/", 1)
            m.add_attachment(p.read_bytes(), maintype=maj, subtype=sub, filename=p.name)
        return m

    def dry_run(self, to: str, text: str) -> dict[str, Any]:
        """Headers that would go out. Read-only Gmail lookups (thread + its last Message-ID) unless
        opts offline=True; never a write. Lookup failure → offline payload with the error."""
        out = super().dry_run(to, text)
        try:
            ctx = {"to": [split_to(to)[0]] if split_to(to)[0] else [], "thread": split_to(to)[1] or None}
            if not self.opts.get("offline"):
                ctx = self._reply_context(to)
        except (GmailError, ChannelError) as e:
            out["lookup_error"] = str(e)
        try:
            m = self.compose(to, text, ctx)
        except ChannelError as e:
            return {**out, "error": str(e)}
        keep = ("From", "Reply-To", "To", "Cc", "Subject", "In-Reply-To", "References")
        return {**out, "thread": ctx.get("thread"), "headers": {k: m[k] for k in keep if m[k]},
                "attachments": [Path(f).name for f in self.opts.get("attach") or []]}

    # -- send / verify --------------------------------------------------------------------------
    def _label_id(self, name: str) -> str:
        if name not in self._label_ids:
            self._label_ids[name] = self.gmail.label_id(name, create=True) or ""
        return self._label_ids[name]

    def _find_sent(self, message_id: str) -> dict | None:
        """Our message in Sent by its Message-ID header, or None."""
        for r in self.gmail.list_messages(f"rfc822msgid:{message_id.strip('<>')}", limit=5):
            m = self.gmail.get_message(r["id"], fmt="minimal")
            if "SENT" in m.get("labelIds", []):
                return m
        return None

    def _tag_sent(self, mid: str, raw: dict[str, Any]) -> None:
        try:
            self.gmail.modify(mid, add=[self._label_id(self.sent_label)])
        except GmailError as e:  # the mail went out; a missing label is mailroute's job
            raw["label_error"] = str(e)

    def send(self, to: str, text: str) -> SendResult:
        try:
            ctx = self._reply_context(to)
            m = self.compose(to, text, ctx)
        except (GmailError, ChannelError) as e:
            return SendResult(False, error=f"not sent: {e}", raw={"maybe_sent": False})
        raw: dict[str, Any] = {"message_id": m["Message-ID"], "thread": ctx.get("thread"), "to": ctx["to"]}
        try:
            sent = self.gmail.send_raw(m.as_bytes(), ctx.get("thread"))
        except (GmailNetworkError, GmailHTTPError) as e:
            maybe = e.maybe_sent if isinstance(e, GmailNetworkError) else e.status >= 500
            raw["maybe_sent"] = maybe
            if not maybe:  # never left the machine (after retries) or a clean 4xx refusal
                return SendResult(False, error=str(e), raw=raw)
            # Check Sent before any re-send: a network error may still have sent it.
            found = self._find_sent(m["Message-ID"])
            if not found:
                return SendResult(False, error=f"outcome unknown: {e}", raw=raw)
            sent = found
            raw["recovered_from"] = str(e)
        raw["thread"] = sent.get("threadId")
        self._tag_sent(sent["id"], raw)
        return SendResult(True, external_id=sent["id"], raw=raw)

    def verify(self, to: str, text: str, result: SendResult) -> str:
        """delivered = the message is in Sent; failed = provably never sent; else unknown."""
        if not result.ok and not result.raw.get("maybe_sent"):
            return FAILED
        tries = int(self.ecfg.get("verify_tries", 3))
        for k in range(tries):
            try:
                if result.external_id:
                    m = self.gmail.get_message(result.external_id, fmt="minimal")
                    if "SENT" in m.get("labelIds", []):
                        return DELIVERED
                elif result.raw.get("message_id") and self._find_sent(result.raw["message_id"]):
                    return DELIVERED
            except GmailError:
                pass
            if k < tries - 1:
                self._sleep(float(self.ecfg.get("verify_wait_s", 5)))
        return UNKNOWN

    # -- read -----------------------------------------------------------------------------------
    def to_msg(self, m: dict) -> Msg:
        h = headers_of(m)
        frm = parseaddr(h.get("from", ""))[1].lower()
        mine = self.is_me(frm) or "SENT" in m.get("labelIds", [])
        text, files = body_text(m)
        sender = "" if mine else (parseaddr(h.get("reply-to", ""))[1] or frm).lower()
        return Msg(at=datetime.fromtimestamp(int(m.get("internalDate", 0)) / 1000, UTC), from_me=mine,
                   text=text, id=m["id"], media=", ".join(files), sender=sender,
                   raw={"thread": m.get("threadId"), "subject": h.get("subject", ""),
                        "message_id": h.get("message-id", ""), "labels": m.get("labelIds", [])})

    def read_thread(self, to: str, limit: int = 50) -> list[Msg]:
        """`addr#THREAD`/`#THREAD` → that thread; `addr` → every message with addr across threads
        (the newest `limit`). Oldest first."""
        addr, tid = split_to(to)
        try:
            if tid:
                full = self._thread_msgs(tid, fmt="full")[-limit:]
            elif addr:
                ids = self.gmail.list_messages(f"{{from:{addr} to:{addr} cc:{addr}}}", limit=limit)
                full = [self.gmail.get_message(r["id"], fmt="full") for r in ids]
            else:
                raise ChannelError(f"bad email address {to!r}")
        except GmailError as e:
            raise ChannelError(f"gmail: {e}") from e
        return sorted((self.to_msg(m) for m in full), key=lambda x: x.at)

    def poll(self, since: datetime) -> list[tuple[str, Msg]]:
        """Inbound car mail (label or plus-address) after `since` minus `poll_overlap_s`.

        Overlap (default 900 s): mail without the plus-address gets the label only on the next
        mailroute pass (≤3 min), so a strict watermark would skip it. Callers dedupe by Msg.id.
        Uses `after:<epoch>` (Gmail is UTC; `newer_than:` has no minutes unit), never `in:inbox`.
        """
        if since.tzinfo is None:
            since = since.replace(tzinfo=deps.owner_tz(self.cfg))
        start = since - timedelta(seconds=float(self.ecfg.get("poll_overlap_s", 900)))
        start_ms = int(start.timestamp() * 1000)
        label_q = re.sub(r"[\s/]+", "-", self.label)
        q = f"{{label:{label_q}{' to:' + self.plus if self.plus else ''}}} after:{int(start.timestamp())}"
        ignore = [s.lower() for s in self.ecfg.get("poll_ignore") or []]
        label_id = None
        out: list[tuple[str, Msg]] = []
        try:
            for r in self.gmail.list_messages(q, limit=int(self.ecfg.get("poll_limit", 200))):
                m = self.gmail.get_message(r["id"], fmt="full")
                if int(m.get("internalDate", 0)) <= start_ms:
                    continue
                h = headers_of(m)
                if label_id is None:
                    label_id = self.gmail.label_id(self.label) or ""
                # Gmail's to: ignores +tags, so a to:<plus> hit must be re-checked on the headers.
                if label_id not in m.get("labelIds", []) and not (
                        self.plus and self.plus in addrs_in(h.get("to", "") + h.get("cc", "") + h.get("delivered-to", ""))):
                    continue
                msg = self.to_msg(m)
                if msg.from_me or any(s in h.get("from", "").lower() for s in ignore):
                    continue
                out.append((msg.sender, msg))
        except GmailError as e:
            raise ChannelError(f"gmail poll: {e}") from e
        return sorted(out, key=lambda x: x[1].at)
