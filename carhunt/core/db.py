"""Thin REST client for cardb (contract: cardb/api/openapi.yaml). JSON in, JSON out.

Base URL from config `cardb.url` (env CARDB_URL wins), token from secret `cardb_token`,
author from env CARDB_AUTHOR (set per agent by `carhunt agent launch`).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

API = "/api/v1"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 0, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class NotFound(ApiError):
    pass


class Conflict(ApiError):
    """409/412: a concurrent edit (If-Match version mismatch) or a duplicate."""


class Unreachable(ApiError):
    pass


def _seg(v: Any) -> str:
    return quote(str(v), safe="")


DEFAULT_URL = "http://127.0.0.1:8484"


class Client:
    def __init__(self, url: str, token: str | None = None, *, author: str | None = None, timeout: float = 30):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers["Accept"] = "application/json"
        if token:
            self.s.headers["Authorization"] = f"Bearer {token}"
        if author:
            self.s.headers["X-Author"] = author

    @classmethod
    def from_config(cls, cfg=None, **kw) -> Client:
        """URL: $CARDB_URL > cardb.url > DEFAULT_URL. Token: cardb.token > secret `cardb_token` > none.

        No config file is fine (fresh setup, tests, one-off scripts); an invalid one still raises.
        """
        from carhunt.core import config, secrets

        cfg = cfg if cfg is not None else config.load_or_none()
        get = cfg.get if cfg is not None else (lambda key, default=None: default)
        url = os.environ.get("CARDB_URL") or get("cardb.url") or DEFAULT_URL
        try:
            token = cfg.secret("cardb.token") if get("cardb.token") else secrets.get("cardb_token")
        except secrets.SecretNotFound:
            token = None
        return cls(url, token, author=kw.pop("author", None) or os.environ.get("CARDB_AUTHOR"), **kw)

    def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                headers: dict | None = None, files: Any = None, data: Any = None, api: bool = True) -> Any:
        url = self.url + (API if api else "") + path
        if params:
            params = {k: (",".join(map(str, v)) if isinstance(v, (list, tuple)) else v)
                      for k, v in params.items() if v is not None}
        try:
            r = self.s.request(method, url, params=params, json=json, headers=headers, files=files,
                               data=data, timeout=self.timeout)
        except requests.RequestException as e:
            raise Unreachable(f"cardb unreachable at {self.url}: {type(e).__name__}") from None
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("error") if isinstance(body, dict) else None
            except ValueError:
                body, msg = r.text, None
            msg = f"{method} {path}: {r.status_code} {msg or r.reason}"
            cls = NotFound if r.status_code == 404 else Conflict if r.status_code in (409, 412) else ApiError
            raise cls(msg, r.status_code, body)
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    # --- health -----------------------------------------------------------
    def health(self) -> Any:
        return self.request("GET", "/healthz", api=False)

    # --- listings ---------------------------------------------------------
    def upsert_listing(self, listing: dict) -> dict:
        return self.request("POST", "/listings/upsert", json=listing)

    def find_listing(self, url: str | None = None, *, site: str | None = None, site_ref: str | None = None) -> dict:
        """The listing by URL, or by (site, site_ref). site_ref is cardb's own ref, derived from the ad URL
        (what upsert stored) — not the site's internal data id; the two differ on standvirtual and olx.pt."""
        res = self.request("GET", "/listings", params={"url": url, "site": site, "site_ref": site_ref})
        items = res.get("items", res) if isinstance(res, dict) and "items" in res else res
        if isinstance(items, list):
            if not items:
                raise NotFound("listing not found", 404)
            return items[0]
        return items

    def listing(self, listing_id: int) -> dict:
        return self.request("GET", f"/listings/{_seg(listing_id)}")

    def listing_patch(self, listing_id: int, fields: dict, *, version: int | str | None = None) -> dict:
        h = {"If-Match": str(version)} if version is not None else None
        return self.request("PATCH", f"/listings/{_seg(listing_id)}", json=fields, headers=h)

    # --- cars -------------------------------------------------------------
    def car(self, car: int | str) -> dict:
        return self.request("GET", f"/cars/{_seg(car)}")

    def cars(self, **filters: Any) -> Any:
        return self.request("GET", "/cars", params=filters)

    def car_patch(self, car: int | str, fields: dict, *, version: int | str | None = None) -> dict:
        h = {"If-Match": str(version)} if version is not None else None
        return self.request("PATCH", f"/cars/{_seg(car)}", json=fields, headers=h)

    def queue(self, *, tier: Any = None, spec: str | None = None, limit: int | None = None,
              offset: int | None = None) -> dict:
        return self.request("GET", "/queue", params={"tier": tier, "spec": spec, "limit": limit, "offset": offset})

    def status(self, car: int | str, status: str, *, reason: str | None = None) -> dict:
        return self.request("POST", f"/cars/{_seg(car)}/status", json={"status": status, "reason": reason})

    def fact(self, car: int | str, key: str, value: Any, *, source: str | None = None, ref: str | None = None) -> Any:
        if value is None:
            return self.request("DELETE", f"/cars/{_seg(car)}/facts/{_seg(key)}")
        return self.request("PUT", f"/cars/{_seg(car)}/facts/{_seg(key)}",
                            json={"value": value, "source": source, "ref": ref})

    def opt(self, car: int | str, key: str, value: str | None, *, source: str | None = None,
            ref: str | None = None) -> Any:
        """value: yes | no | unknown; None removes the row."""
        if value is None:
            return self.request("DELETE", f"/cars/{_seg(car)}/options/{_seg(key)}")
        return self.request("PUT", f"/cars/{_seg(car)}/options/{_seg(key)}",
                            json={"value": value, "source": source, "ref": ref})

    def verdict(self, car: int | str, value: str, *, note: str | None = None) -> Any:
        """value: up | maybe | down | clear."""
        if value == "clear":
            return self.request("DELETE", f"/cars/{_seg(car)}/verdict")
        return self.request("PUT", f"/cars/{_seg(car)}/verdict", json={"verdict": value, "note": note})

    def event(self, car: int | str, type: str, summary: str, *, data: dict | None = None, key: str | None = None,
              at: str | None = None, listing: int | None = None) -> dict:
        body = {"type": type, "summary": summary, "data": data, "dedupe_key": key, "at": at, "listing_id": listing}
        return self.request("POST", f"/cars/{_seg(car)}/events", json={k: v for k, v in body.items() if v is not None})

    def events(self, car: int | str) -> Any:
        return self.request("GET", f"/cars/{_seg(car)}/events")

    # --- messages ---------------------------------------------------------
    def msg(self, **fields: Any) -> dict:
        """POST /messages: car_id|url|counterpart, channel, direction, text, at, external_id, dedupe_key…"""
        return self.request("POST", "/messages", json={k: v for k, v in fields.items() if v is not None})

    def msgs(self, car: int | str) -> Any:
        return self.request("GET", f"/cars/{_seg(car)}/messages")

    # --- photos -----------------------------------------------------------
    def photo_add(self, car: int | str, *, url: str | None = None, file: str | Path | None = None,
                  source: str | None = None, listing: int | None = None, caption: str | None = None) -> dict:
        meta = {k: v for k, v in {"source": source, "listing_id": listing, "caption": caption}.items() if v is not None}
        if url:
            return self.request("POST", f"/cars/{_seg(car)}/photos", json={"url": url, **meta})
        if not file:
            raise ValueError("photo_add needs url or file")
        with open(file, "rb") as fh:
            return self.request("POST", f"/cars/{_seg(car)}/photos", files={"file": fh},
                                data={k: str(v) for k, v in meta.items()})
