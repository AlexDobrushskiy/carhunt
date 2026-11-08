"""Minimal cardb REST client, used only until carhunt.core.db lands (same method names and errors).

Covers what discover calls: upsert_listing, find_listing, listing, car, photo_add, fact. Token from env
CARHUNT_SECRET_CARDB_TOKEN (never printed), URL from env CARDB_URL or config `cardb.url`.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlencode

API = "/api/v1"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status, self.body = status, body


class NotFound(ApiError):
    pass


class Unreachable(ApiError):
    pass


class Client:
    def __init__(self, url: str, token: str | None = None, *, author: str | None = None, timeout: float = 30):
        self.url, self.timeout = url.rstrip("/"), timeout
        self.headers = {"Accept": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        if author:
            self.headers["X-Author"] = author

    @classmethod
    def from_env(cls, cfg: dict, **kw) -> Client:
        url = os.environ.get("CARDB_URL") or (cfg.get("cardb") or {}).get("url") or "http://127.0.0.1:8484"
        return cls(url, os.environ.get("CARHUNT_SECRET_CARDB_TOKEN"), **kw)

    def request(self, method: str, path: str, *, params: dict | None = None, json_body: Any = None) -> Any:
        url = self.url + API + path
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(json_body).encode() if json_body is not None else None
        h = dict(self.headers)
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                parsed = json.loads(raw)
            except ValueError:
                parsed = raw.decode("utf-8", "replace")
            msg = f"{method} {path}: {e.code} {parsed.get('error') if isinstance(parsed, dict) else e.reason}"
            raise (NotFound if e.code == 404 else ApiError)(msg, e.code, parsed) from None
        except (urllib.error.URLError, OSError) as e:
            raise Unreachable(f"cardb unreachable at {self.url}: {type(e).__name__}") from None
        return json.loads(body) if body else None

    def upsert_listing(self, listing: dict) -> dict:
        return self.request("POST", "/listings/upsert", json_body=listing)

    def find_listing(self, url: str) -> dict:
        res = self.request("GET", "/listings", params={"url": url})
        items = res.get("items", res) if isinstance(res, dict) else res
        if not items:
            raise NotFound("listing not found", 404)
        return items[0]

    def listing(self, listing_id: int) -> dict:
        return self.request("GET", f"/listings/{listing_id}")

    def car(self, car: int | str) -> dict:
        return self.request("GET", f"/cars/{quote(str(car), safe='')}")

    def fact(self, car: int | str, key: str, value: Any, *, source: str | None = None) -> Any:
        return self.request("PUT", f"/cars/{quote(str(car), safe='')}/facts/{quote(key, safe='')}",
                            json_body={"value": value, "source": source})

    def photo_add(self, car: int | str, *, url: str, source: str | None = None, listing: int | None = None,
                  caption: str | None = None) -> dict:
        body = {k: v for k, v in {"url": url, "source": source, "listing_id": listing, "caption": caption}.items()
                if v is not None}
        return self.request("POST", f"/cars/{quote(str(car), safe='')}/photos", json_body=body)
