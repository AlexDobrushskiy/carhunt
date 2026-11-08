"""Thin Gmail REST client (stdlib only): OAuth refresh, safe retries, the calls contact needs.

Secrets (by name, never printed): `gmail_oauth_client` = the OAuth client JSON Google gives you
(`{"installed": {...}}`, `{"web": {...}}` or flat `client_id/client_secret/token_uri`);
`gmail_token` = `{"refresh_token": ...}` JSON (may also carry the client fields) or the bare
refresh token. Get one with `local_consent()` and store it with `carhunt secret set gmail_token`.

Scope: `gmail.modify` covers read, send and labels. Filters need `gmail.settings.basic`, which a
modify token doesn't have, so mailroute writes filter XML for import in the Gmail UI instead.

Retry policy: GETs retry on any network error (idempotent). POSTs retry only on errors raised
before the request left the machine (DNS, connection refused): nothing was sent yet. Any other
POST failure is `GmailNetworkError(maybe_sent=True)` and the caller must check Sent before a
re-send. Why: blind re-sends after network errors sent 4 duplicate emails (2026-11-05).
"""
from __future__ import annotations

import base64
import http.client
import http.server
import json
import secrets as _pysecrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Iterable

from . import deps

API = "https://gmail.googleapis.com/gmail/v1/users/me/"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
DEFAULT_SCOPES = ("https://www.googleapis.com/auth/gmail.modify",)


class GmailError(Exception):
    pass


class GmailAuthError(GmailError):
    pass


class GmailHTTPError(GmailError):
    def __init__(self, status: int, detail: str = ""):
        super().__init__(f"HTTP {status} {detail}".strip())
        self.status = status


class GmailNetworkError(GmailError):
    """`maybe_sent` False = the request never left (safe to retry); True = outcome unknown."""

    def __init__(self, msg: str, *, maybe_sent: bool):
        super().__init__(msg)
        self.maybe_sent = maybe_sent


def _pre_request(reason: Any) -> bool:
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError))


def _client_fields(client: Any) -> dict[str, str]:
    if isinstance(client, str):
        client = json.loads(client) if client.strip().startswith("{") else {}
    client = client or {}
    return client.get("installed") or client.get("web") or client


class Gmail:
    """One mailbox (`users/me`). Inject `urlopen`/`sleep` in tests."""

    def __init__(self, *, client_secret: str = "gmail_oauth_client", token_secret: str = "gmail_token",
                 retries: int = 3, retry_wait_s: float = 20.0, timeout_s: float = 60.0,
                 urlopen: Callable[..., Any] | None = None, sleep: Callable[[float], None] = time.sleep):
        self.client_secret, self.token_secret = client_secret, token_secret
        self.retries, self.retry_wait_s, self.timeout_s = retries, retry_wait_s, timeout_s
        self._urlopen = urlopen or urllib.request.urlopen
        self._sleep = sleep
        self._access: str | None = None
        self._access_exp = 0.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any], **kw: Any) -> "Gmail":
        e = ((cfg.get("contact") or {}).get("email") or {})
        name = lambda v, d: (v or d).removeprefix("secret:")  # noqa: E731
        return cls(client_secret=name(e.get("oauth_client"), "gmail_oauth_client"),
                   token_secret=name(e.get("token"), "gmail_token"), **kw)

    def __repr__(self) -> str:  # never show tokens
        return f"Gmail(client={self.client_secret!r}, token={self.token_secret!r})"

    # -- auth -----------------------------------------------------------------------------------
    def _creds(self) -> dict[str, str]:
        tok_raw = deps.secret(self.token_secret)
        if not tok_raw:
            raise GmailAuthError(f"secret {self.token_secret!r} not set (carhunt secret set {self.token_secret})")
        tok = json.loads(tok_raw) if tok_raw.strip().startswith("{") else {"refresh_token": tok_raw.strip()}
        client = _client_fields(tok) if tok.get("client_id") else _client_fields(deps.secret(self.client_secret))
        if not client.get("client_id") or not tok.get("refresh_token"):
            raise GmailAuthError(f"secrets {self.client_secret!r}/{self.token_secret!r} lack client_id or refresh_token")
        return {"client_id": client["client_id"], "client_secret": client.get("client_secret", ""),
                "token_uri": client.get("token_uri") or TOKEN_URI, "refresh_token": tok["refresh_token"]}

    def access_token(self) -> str:
        if self._access and time.time() < self._access_exp - 60:
            return self._access
        c = self._creds()
        body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request(c["token_uri"], data=body, method="POST")
        try:
            r = self._retrying(lambda: self._open(req), idempotent=True, what="token refresh")
        except GmailHTTPError as e:
            raise GmailAuthError(f"token refresh failed: HTTP {e.status} (re-consent, then carhunt secret set "
                                 f"{self.token_secret})") from None
        self._access, self._access_exp = r["access_token"], time.time() + float(r.get("expires_in", 3600))
        return self._access

    # -- transport ------------------------------------------------------------------------------
    def _open(self, req: urllib.request.Request) -> Any:
        with self._urlopen(req, timeout=self.timeout_s) as r:
            raw = r.read()
        return json.loads(raw) if raw else {}

    def _retrying(self, fn: Callable[[], Any], *, idempotent: bool, what: str) -> Any:
        for k in range(self.retries + 1):
            try:
                return fn()
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode("utf-8", "replace") if e.fp else ""
                raise GmailHTTPError(e.code, detail) from None
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                reason = getattr(e, "reason", e)
                if not (idempotent or _pre_request(reason)) or k == self.retries:
                    raise GmailNetworkError(f"{what}: {reason}", maybe_sent=not _pre_request(reason)) from None
                print(f"gmail: network error ({reason}), retry {k + 1}/{self.retries} in {self.retry_wait_s:g} s",
                      file=sys.stderr)
                self._sleep(self.retry_wait_s)
        raise AssertionError("unreachable")

    def _raw(self, method: str, path: str, query: dict[str, Any] | None, body: Any) -> Any:
        """One attempt at one API call; raises urllib errors as-is. Tests replace this wire."""
        url = API + path + ("?" + urllib.parse.urlencode(query, doseq=True) if query else "")
        data = json.dumps(body).encode() if body is not None else None
        return self._open(urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.access_token(), "Content-Type": "application/json"}))

    def call(self, method: str, path: str, query: dict[str, Any] | None = None, body: Any = None) -> Any:
        for attempt in (1, 2):
            try:
                return self._retrying(lambda: self._raw(method, path, query, body),
                                      idempotent=method == "GET", what=f"{method} {path.split('?')[0]}")
            except GmailHTTPError as e:
                if e.status == 401 and attempt == 1:  # access token expired mid-run: refresh once
                    self._access = None
                    continue
                raise
        raise AssertionError("unreachable")

    # -- API ------------------------------------------------------------------------------------
    def _paged(self, kind: str, q: str, limit: int) -> list[dict]:
        out: list[dict] = []
        page = None
        while True:
            query = {"q": q, "maxResults": min(500, limit)}
            if page:
                query["pageToken"] = page
            r = self.call("GET", kind, query)
            out += r.get(kind, [])
            page = r.get("nextPageToken")
            if not page or len(out) >= limit:
                return out[:limit]

    def list_messages(self, q: str, *, limit: int = 500) -> list[dict]:
        """[{id, threadId}], newest first. Searches all mail but spam/trash."""
        return self._paged("messages", q, limit)

    def list_threads(self, q: str, *, limit: int = 5000) -> list[dict]:
        return self._paged("threads", q, limit)

    def get_message(self, mid: str, *, fmt: str = "full", headers: Iterable[str] = ()) -> dict:
        query: dict[str, Any] = {"format": fmt}
        if headers:
            query["metadataHeaders"] = list(headers)
        return self.call("GET", f"messages/{mid}", query)

    def get_thread(self, tid: str, *, fmt: str = "metadata", headers: Iterable[str] = ()) -> dict:
        query: dict[str, Any] = {"format": fmt}
        if headers:
            query["metadataHeaders"] = list(headers)
        return self.call("GET", f"threads/{tid}", query)

    def send_raw(self, raw: bytes, thread_id: str | None = None) -> dict:
        body: dict[str, Any] = {"raw": base64.urlsafe_b64encode(raw).decode()}
        if thread_id:
            body["threadId"] = thread_id
        return self.call("POST", "messages/send", body=body)

    def modify(self, mid: str, *, add: Iterable[str] = (), remove: Iterable[str] = ()) -> dict:
        return self.call("POST", f"messages/{mid}/modify",
                         body={"addLabelIds": list(add), "removeLabelIds": list(remove)})

    def batch_modify(self, ids: list[str], *, add: Iterable[str] = (), remove: Iterable[str] = ()) -> None:
        for i in range(0, len(ids), 1000):  # API max per call
            self.call("POST", "messages/batchModify",
                      body={"ids": ids[i:i + 1000], "addLabelIds": list(add), "removeLabelIds": list(remove)})

    def labels(self) -> list[dict]:
        return self.call("GET", "labels").get("labels", [])

    def create_label(self, name: str) -> dict:
        return self.call("POST", "labels", body={"name": name, "labelListVisibility": "labelShow",
                                                  "messageListVisibility": "show"})

    def label_id(self, name: str, *, create: bool = False) -> str | None:
        for lab in self.labels():
            if lab["name"].lower() == name.lower():
                return lab["id"]
        return self.create_label(name)["id"] if create else None


# -- helpers on API payloads ------------------------------------------------------------------------

def headers_of(m: dict) -> dict[str, str]:
    """Lower-cased header map of a message resource."""
    return {h["name"].lower(): h["value"] for h in (m.get("payload") or {}).get("headers", [])}


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def body_text(m: dict) -> tuple[str, list[str]]:
    """(plain text, attachment filenames) of a `format=full` message. HTML only → tags stripped."""
    plain: list[str] = []
    html: list[str] = []
    files: list[str] = []

    def walk(p: dict) -> None:
        mime = p.get("mimeType", "")
        if p.get("filename"):
            files.append(p["filename"])
        elif mime == "text/plain" and (p.get("body") or {}).get("data"):
            plain.append(_b64(p["body"]["data"]).decode("utf-8", "replace"))
        elif mime == "text/html" and (p.get("body") or {}).get("data"):
            html.append(_b64(p["body"]["data"]).decode("utf-8", "replace"))
        for c in p.get("parts") or []:
            walk(c)

    walk(m.get("payload") or {})
    if plain:
        return "\n".join(plain).strip(), files
    import html as _html
    import re

    text = re.sub(r"<(br|/p|/div)[^>]*>", "\n", "\n".join(html), flags=re.I)
    return _html.unescape(re.sub(r"<[^>]+>", "", text)).strip(), files


# -- one-time consent (installed-app loopback flow) ---------------------------------------------

def consent_url(client: Any, scopes: Iterable[str], redirect_uri: str, state: str) -> str:
    c = _client_fields(client)
    return (c.get("auth_uri") or AUTH_URI) + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(scopes), "access_type": "offline", "prompt": "consent", "state": state})


def exchange_code(client: Any, code: str, redirect_uri: str, *,
                  urlopen: Callable[..., Any] = urllib.request.urlopen) -> dict:
    """Code → token dict (has refresh_token). Store it as a secret; never print it."""
    c = _client_fields(client)
    body = urllib.parse.urlencode({"code": code, "client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                   "redirect_uri": redirect_uri, "grant_type": "authorization_code"}).encode()
    with urlopen(urllib.request.Request(c.get("token_uri") or TOKEN_URI, data=body, method="POST"), timeout=60) as r:
        return json.loads(r.read())


def local_consent(client: Any, scopes: Iterable[str] = DEFAULT_SCOPES, *,
                  open_url: Callable[[str], Any] | None = None, timeout_s: float = 300,
                  urlopen: Callable[..., Any] = urllib.request.urlopen) -> dict:
    """Open Google's consent page, catch the redirect on 127.0.0.1, return the token dict."""
    state = _pysecrets.token_urlsafe(16)
    got: dict[str, str] = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
            if q.get("state") == state:
                got.update(q)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"carhunt: Gmail access granted, you can close this tab.")

        def log_message(self, *a: Any) -> None:
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}/"
    srv.timeout = 1
    if open_url is None:
        import webbrowser

        open_url = webbrowser.open
    threading.Thread(target=open_url, args=(consent_url(client, scopes, redirect, state),), daemon=True).start()
    end = time.time() + timeout_s
    try:
        while not got and time.time() < end:
            srv.handle_request()
    finally:
        srv.server_close()
    if "code" not in got:
        raise GmailAuthError(f"no consent: {got.get('error', 'timed out')}")
    return exchange_code(client, got["code"], redirect, urlopen=urlopen)
