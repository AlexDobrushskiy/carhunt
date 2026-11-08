"""In-memory Gmail double. Subclasses the real client and replaces only the wire (`_raw`), so the
real retry policy and every client method run against it. Records each API call in `calls`.

Search supports what contact uses: in:inbox|sent, newer_than:Nd, after:EPOCH, from:/to:/cc:,
label:, rfc822msgid:, and {a b} OR-groups. Like Gmail, `to:` ignores +tags.
"""
from __future__ import annotations

import base64
import re
import socket
import threading
import urllib.error
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, make_msgid
from typing import Any

from carhunt.contact.gmail import Gmail

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
SYSTEM = {"INBOX", "SENT", "UNREAD", "TRASH", "SPAM", "DRAFT", "IMPORTANT", "STARRED"}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _payload(part: Any) -> dict:
    p: dict[str, Any] = {"mimeType": part.get_content_type(), "filename": part.get_filename() or "",
                         "headers": [{"name": k, "value": str(v)} for k, v in part.items()], "body": {}}
    if part.is_multipart():
        p["parts"] = [_payload(c) for c in part.iter_parts()]
    else:
        p["body"] = {"data": _b64(part.get_payload(decode=True) or b"")}
    return p


def _norm(a: str) -> str:
    local, at, dom = a.lower().partition("@")
    return local.split("+")[0] + at + dom


class FakeGmail(Gmail):
    def __init__(self, me: str = "owner@example.com", now: datetime = NOW):
        super().__init__(sleep=lambda s: self.sleeps.append(s))
        self.me, self.now = me, now
        self.msgs: dict[str, dict] = {}
        self.label_names: dict[str, str] = {}  # id -> name (user labels)
        self.calls: list[tuple[str, str, dict, Any]] = []
        self.sleeps: list[float] = []
        self._faults: list[dict] = []
        self._n = 0
        self._lock = threading.RLock()

    # -- seeding -----------------------------------------------------------------------------
    def _id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:04d}"

    def add_label(self, name: str) -> str:
        lid = self._id("Label_")
        self.label_names[lid] = name
        return lid

    def add(self, *, frm: str, to: str, subject: str = "Hello", body: str = "hi", labels=("INBOX", "UNREAD"),
            thread: str | None = None, minutes_ago: float = 60, cc: str = "", reply_to: str = "",
            delivered_to: str = "", message_id: str | None = None, references: str = "") -> dict:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = frm, to, subject
        for k, v in (("Cc", cc), ("Reply-To", reply_to), ("Delivered-To", delivered_to), ("References", references)):
            if v:
                m[k] = v
        m["Message-ID"] = message_id or make_msgid(domain="mail.example.com")
        m.set_content(body)
        at = self.now.timestamp() - minutes_ago * 60
        return self._store(m, list(labels), thread, at)

    def _store(self, m: Any, labels: list[str], thread: str | None, at: float) -> dict:
        mid = self._id("m")
        rec = {"id": mid, "threadId": thread or "t" + mid[1:], "labelIds": labels,
               "internalDate": str(int(at * 1000)), "email": m}
        self.msgs[mid] = rec
        return rec

    def fail(self, op: str, kind: str = "before", times: int = 1, status: int = 500) -> None:
        """Inject a fault on calls whose 'METHOD path' starts with `op`.
        before = DNS error, nothing sent · after = handled then timeout · http = HTTPError(status)."""
        self._faults.append({"op": op, "kind": kind, "times": times, "status": status})

    # -- views -------------------------------------------------------------------------------
    def writes(self) -> list[tuple[str, str, dict, Any]]:
        return [c for c in self.calls if c[0] != "GET"]

    def sent(self) -> list[dict]:
        return [m for m in self.msgs.values() if "SENT" in m["labelIds"]]

    def access_token(self) -> str:
        return "fake-token"

    # -- search ------------------------------------------------------------------------------
    def _hdr(self, m: dict, name: str) -> str:
        return str(m["email"].get(name, "") or "")

    def _term(self, m: dict, t: str) -> bool:
        key, _, val = t.partition(":")
        val = val.lower()
        if key == "in":
            return {"inbox": "INBOX", "sent": "SENT"}[val] in m["labelIds"]
        if key == "newer_than":
            return int(m["internalDate"]) > (self.now.timestamp() - int(val[:-1]) * 86400) * 1000
        if key == "after":
            return int(m["internalDate"]) >= int(val) * 1000
        if key == "label":
            names = {self.label_names.get(l, l).lower().replace(" ", "-") for l in m["labelIds"]}
            return val in names
        if key == "rfc822msgid":
            return val in self._hdr(m, "Message-ID").lower()
        if key in ("from", "to", "cc"):
            fields = {"from": ["From"], "to": ["To", "Cc", "Delivered-To"], "cc": ["Cc"]}[key]
            addrs = [_norm(a) for _, a in getaddresses([x for x in map(lambda f: self._hdr(m, f), fields) if x])]
            v = _norm(val) if "@" in val else val
            return any(v == a or ("@" not in v and a.endswith(v)) for a in addrs)
        raise ValueError(f"fake gmail: unsupported search term {t!r}")

    def _match(self, m: dict, q: str) -> bool:
        if "TRASH" in m["labelIds"] or "SPAM" in m["labelIds"]:
            return False
        for tok in re.findall(r"\{[^}]*\}|\S+", q):
            if tok.startswith("{"):
                if not any(self._term(m, t) for t in tok[1:-1].split()):
                    return False
            elif not self._term(m, tok):
                return False
        return True

    # -- wire --------------------------------------------------------------------------------
    def _fault(self, op: str) -> dict | None:
        for f in self._faults:
            if f["times"] > 0 and op.startswith(f["op"]):
                f["times"] -= 1
                return f
        return None

    def _raw(self, method: str, path: str, query: dict[str, Any] | None, body: Any) -> Any:
        with self._lock:
            query = query or {}
            self.calls.append((method, path, dict(query), body))
            f = self._fault(f"{method} {path}")
            if f and f["kind"] == "before":
                raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
            if f and f["kind"] == "http":
                raise urllib.error.HTTPError(path, f["status"], "fault", {}, None)
            out = self._handle(method, path, query, body)
            if f and f["kind"] == "after":
                raise TimeoutError("The read operation timed out")
            return out

    def _open(self, req: Any) -> Any:  # pragma: no cover - the wire is _raw
        raise AssertionError("fake gmail never opens sockets")

    def _view(self, m: dict, fmt: str, headers: list[str] | str | None) -> dict:
        out = {k: m[k] for k in ("id", "threadId", "labelIds", "internalDate")}
        out["labelIds"] = list(m["labelIds"])
        if fmt == "minimal":
            return out
        p = _payload(m["email"])
        if fmt == "metadata":
            want = {h.lower() for h in ([headers] if isinstance(headers, str) else headers or [])}
            hs = [h for h in p["headers"] if not want or h["name"].lower() in want]
            p = {"mimeType": p["mimeType"], "headers": hs}
        out["payload"] = p
        out["snippet"] = ""
        return out

    def _handle(self, method: str, path: str, q: dict[str, Any], body: Any) -> Any:
        newest = sorted(self.msgs.values(), key=lambda m: -int(m["internalDate"]))
        if method == "GET" and path == "messages":
            hits = [m for m in newest if self._match(m, q.get("q", ""))][: int(q.get("maxResults", 100))]
            return {"messages": [{"id": m["id"], "threadId": m["threadId"]} for m in hits]} if hits else {}
        if method == "GET" and path == "threads":
            seen: list[str] = []
            for m in newest:
                if self._match(m, q.get("q", "")) and m["threadId"] not in seen:
                    seen.append(m["threadId"])
            return {"threads": [{"id": t} for t in seen]} if seen else {}
        if method == "GET" and path.startswith("messages/"):
            m = self.msgs.get(path.split("/", 1)[1])
            if not m:
                raise urllib.error.HTTPError(path, 404, "not found", {}, None)
            return self._view(m, q.get("format", "full"), q.get("metadataHeaders"))
        if method == "GET" and path.startswith("threads/"):
            tid = path.split("/", 1)[1]
            ms = sorted((m for m in self.msgs.values() if m["threadId"] == tid), key=lambda m: int(m["internalDate"]))
            if not ms:
                raise urllib.error.HTTPError(path, 404, "not found", {}, None)
            return {"id": tid, "messages": [self._view(m, q.get("format", "full"), q.get("metadataHeaders")) for m in ms]}
        if method == "POST" and path == "messages/send":
            raw = base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4))
            m = message_from_bytes(raw, policy=policy.default)
            rec = self._store(m, ["SENT"], body.get("threadId"), self.now.timestamp())
            return {"id": rec["id"], "threadId": rec["threadId"], "labelIds": ["SENT"]}
        if method == "POST" and path.endswith("/modify"):
            m = self.msgs[path.split("/")[1]]
            self._apply(m, body)
            return {"id": m["id"], "labelIds": m["labelIds"]}
        if method == "POST" and path == "messages/batchModify":
            for i in body["ids"]:
                self._apply(self.msgs[i], body)
            return {}
        if method == "GET" and path == "labels":
            return {"labels": [{"id": s, "name": s, "type": "system"} for s in sorted(SYSTEM)]
                    + [{"id": i, "name": n, "type": "user"} for i, n in self.label_names.items()]}
        if method == "POST" and path == "labels":
            return {"id": self.add_label(body["name"]), "name": body["name"]}
        raise ValueError(f"fake gmail: no route {method} {path}")

    @staticmethod
    def _apply(m: dict, body: dict) -> None:
        m["labelIds"] = [l for l in m["labelIds"] if l not in body.get("removeLabelIds", [])]
        m["labelIds"] += [l for l in body.get("addLabelIds", []) if l not in m["labelIds"]]
