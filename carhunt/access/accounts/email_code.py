r"""Read-only Gmail lookups for site verification codes and confirm links.

    from carhunt.access.accounts import email_code, wait_code, wait_link
    t0 = time.time()                       # BEFORE asking the site to send the mail
    code = wait_code("wallapop.com", since=t0)
    url = wait_link("milanuncios.com", since=t0, pattern=r"https://www\.milanuncios\.com/cuenta-verificada[^\"' <]+")

Auth: config `accounts.gmail.oauth_client` (secret: Google client JSON, "installed"/"web" or flat
{client_id, client_secret}) and `accounts.gmail.token` (secret: JSON with refresh_token, or the bare refresh token).
Scope gmail.readonly; nothing is ever written to the mailbox or to the secrets.
Codes and confirm links: check mail first, a "texted" code once arrived by email (10-31).
Publish the Google OAuth app **In production**: a Testing app's refresh tokens die after 7 days, and every
Gmail-dependent agent died at once (11-06).
Query per site: site.yaml `account.mail_from` (Gmail query, e.g. `from:(example.com)`), else `from:<domain>`.
"""
from __future__ import annotations

import base64
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from carhunt.access import _core

API = "https://gmail.googleapis.com/gmail/v1/users/me/"
TOKEN_URI = "https://oauth2.googleapis.com/token"
CODE_RE = r"(?<![\w#])(\d{6})(?!\w)"

# transport(method, url, headers, body) -> (status, body bytes)
Transport = Callable[[str, str, dict, "bytes | None"], tuple[int, bytes]]


def _urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class GmailError(RuntimeError):
    pass


def _secret_name(ref: Any, default: str) -> str:
    if ref is None:
        return default
    return (getattr(ref, "name", None) or str(ref)).removeprefix("secret:")


class Gmail:
    def __init__(self, transport: Transport | None = None, *, client_secret: str | None = None,
                 token_secret: str | None = None):
        cfg = _core.section("accounts").get("gmail") or {}
        self.transport = transport or _urllib_transport
        self.client_secret = client_secret or _secret_name(cfg.get("oauth_client"), "gmail_oauth_client")
        self.token_secret = token_secret or _secret_name(cfg.get("token"), "gmail_token")
        self._access: tuple[str, float] | None = None

    def _creds(self) -> dict:
        client, token = _core.secret(self.client_secret), _core.secret(self.token_secret)
        if not client or not token:
            raise GmailError(f"Gmail not set up: secrets {self.client_secret} (OAuth client JSON) and "
                             f"{self.token_secret} (refresh token) are needed; see docs/browsers.md")
        c = json.loads(client)
        c = c.get("installed") or c.get("web") or c
        try:
            t = json.loads(token)
            refresh = t.get("refresh_token") if isinstance(t, dict) else None
        except ValueError:
            refresh = token.strip()
        if not refresh:
            raise GmailError(f"secret {self.token_secret} has no refresh_token")
        return {"client_id": c["client_id"], "client_secret": c["client_secret"],
                "token_uri": c.get("token_uri") or TOKEN_URI, "refresh_token": refresh}

    def _token(self) -> str:
        if self._access and self._access[1] > time.time() + 60:
            return self._access[0]
        c = self._creds()
        body = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                       "refresh_token": c["refresh_token"], "grant_type": "refresh_token"}).encode()
        st, raw = self.transport("POST", c["token_uri"], {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if st != 200:
            # invalid_grant after ~7 days = OAuth app still in Testing (publish it In production, 11-06)
            raise GmailError(f"token refresh failed (HTTP {st}); invalid_grant → re-authorize and publish the "
                             f"OAuth app In production")
        d = json.loads(raw)
        self._access = (d["access_token"], time.time() + float(d.get("expires_in", 3600)))
        return self._access[0]

    def api(self, path: str) -> dict:
        st, raw = self.transport("GET", API + path, {"Authorization": "Bearer " + self._token()}, None)
        if st != 200:
            raise GmailError(f"Gmail API HTTP {st} for {path.split('?')[0]}")
        return json.loads(raw)

    def messages(self, query: str, since: float | None, limit: int = 5) -> list[dict]:
        q = query + (f" after:{int(since) - 60}" if since else " newer_than:1h")
        ids = self.api("messages?" + urllib.parse.urlencode({"q": q, "maxResults": limit})).get("messages", [])
        out = []
        for m in ids:
            d = self.api(f"messages/{m['id']}?format=full")
            if since and int(d.get("internalDate", 0)) / 1000 < since - 5:
                continue  # Gmail's after: is day-granular in places; re-check the real receive time
            out.append(d)
        return out


def _text(payload: dict, *, links: bool = False) -> str:
    """Visible text of a message; links=True → the href/URLs instead (codes live in text, links in hrefs)."""
    out, parts = [], [payload]
    while parts:
        p = parts.pop()
        parts += p.get("parts", []) or []
        data = (p.get("body") or {}).get("data")
        mime = p.get("mimeType", "")
        if not data or not mime.startswith("text/"):
            continue
        t = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
        if mime == "text/html":
            t = " ".join(re.findall(r'href="([^"]+)"', t)) if links else \
                re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(style|script|head)\b.*?</\1>", "", t))
        elif links:
            t = " ".join(re.findall(r"https?://\S+", t))
        out.append(html.unescape(t))
    return "\n".join(out)


def site_query(site: str) -> str:
    from carhunt.access import pace
    acct = pace.site_config(site).get("account") or {}
    return str(acct.get("mail_from") or f"from:{site}")


def email_code(site: str, since: float | None = None, pattern: str = CODE_RE, *, query: str | None = None,
               links: bool = False, gmail: Gmail | None = None) -> str | None:
    """First `pattern` match (group 1 if any) in the newest matching mail received after `since`; one look, no wait."""
    g = gmail or Gmail()
    for d in g.messages(query or site_query(site), since):
        text = _text(d["payload"], links=True) if links else _text(d["payload"])
        m = re.search(pattern, text)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return None


def _wait(site, since, pattern, timeout, poll, links, query, gmail, sleep) -> str | None:
    end = time.monotonic() + timeout
    g = gmail or Gmail()
    while True:
        r = email_code(site, since, pattern, query=query, links=links, gmail=g)
        if r or time.monotonic() >= end:
            return r
        sleep(poll)


def wait_code(site: str, since: float, pattern: str = CODE_RE, *, timeout: float = 180, poll: float = 8,
              query: str | None = None, gmail: Gmail | None = None, sleep=time.sleep) -> str | None:
    """Poll for a code (visible text only); None on timeout."""
    return _wait(site, since, pattern, timeout, poll, False, query, gmail, sleep)


def wait_link(site: str, since: float, pattern: str, *, timeout: float = 180, poll: float = 8,
              query: str | None = None, gmail: Gmail | None = None, sleep=time.sleep) -> str | None:
    """Poll for a confirm link matching `pattern` (searched in hrefs/URLs); None on timeout."""
    return _wait(site, since, pattern, timeout, poll, True, query, gmail, sleep)
