"""Site protocol, the plugin registry and the errors plugins raise.

A plugin is `carhunt/sites/<pkg>/plugin.py` exposing `Plugin` (a `BaseSite` subclass) next to its `site.yaml`
(`site:` = the id used in config and cardb, e.g. "mobile.de"; the package name is the id with dots → "_").
`carhunt/sites/fake/` registers only with CARHUNT_FAKE_SITES=1.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from carhunt.access.errors import Blocked, PaceExceeded  # noqa: F401  (re-exported for plugins + discover)
from carhunt.sites.model import Card, Liveness, RawAd, SearchQuery

ROOT = Path(__file__).resolve().parent
FAKE_ENV = "CARHUNT_FAKE_SITES"


class Gone(Exception):
    """The ad is no longer online (404/410 or the site's own marker). Not a block: skip it, keep going."""

    def __init__(self, url: str, evidence: str):
        self.url, self.evidence = url, evidence
        super().__init__(f"gone: {url} ({evidence})")


class Unsupported(Exception):
    """The plugin has no reader for this action (README-only site, or a step that needs a login/send)."""


@runtime_checkable
class Site(Protocol):
    id: str
    meta: dict

    def search(self, q: SearchQuery) -> Iterator[Card]: ...
    def ad(self, url: str) -> RawAd: ...
    def is_live(self, url: str) -> Liveness: ...
    def owns(self, url: str) -> bool: ...
    def ad_id(self, url: str) -> str | None: ...


class BaseSite:
    """Shared plumbing: metadata, URL ownership, ad ids, pacing + transport (see `carhunt.sites._net`).

    Subclasses set `pkg` (their package name) and implement search/ad/is_live; `phone` is optional.
    """
    pkg: str = ""

    def __init__(self, net: Any = None):
        from carhunt.sites import _net
        self.meta = load_meta(self.pkg)
        self.id: str = self.meta["site"]
        self.net = net or _net.Net(self.id, self.meta)
        self.codes = load_codes(self.pkg)

    # --- identity --------------------------------------------------------
    def owns(self, url: str) -> bool:
        host = (url.split("/")[2] if "://" in url else url).lower()
        return any(re.search(rx, host) for rx in self.meta.get("hosts", []))

    def ad_id(self, url: str) -> str | None:
        for rx in self.meta.get("ad_id", []):
            m = re.search(rx, url)
            if m:
                return m.group(1)
        return None

    # --- query codes (codes.yaml) -----------------------------------------
    def code(self, table: str, *keys: str | None, slug: bool = True) -> str | None:
        """Look up codes.yaml `table` by key path, case-insensitive (e.g. code("models", "Skoda", "Enyaq")).
        Missing → slugified last key when `slug`, else None (numeric-code sites must list every make/model)."""
        node: Any = self.codes.get(table) or {}
        for k in keys:
            if k is None or not isinstance(node, dict):
                return None
            node = {str(a).lower(): b for a, b in node.items()}.get(str(k).lower())
            if node is None:
                return slugify(keys[-1]) if slug and keys[-1] else None
        return None if isinstance(node, dict) else str(node)

    def need_code(self, table: str, *keys: str | None) -> str:
        c = self.code(table, *keys, slug=False)
        if c is None:
            raise Unsupported(f"{self.id}: no {table} code for {'/'.join(k or '?' for k in keys)} — add it to "
                              f"carhunt/sites/{self.pkg}/codes.yaml")
        return c

    # --- actions ---------------------------------------------------------
    def search(self, q: SearchQuery) -> Iterator[Card]:
        raise Unsupported(f"{self.id}: search has no reader yet (route {self.meta.get('route')})")

    def ad(self, url: str) -> RawAd:
        raise Unsupported(f"{self.id}: ad has no reader yet (route {self.meta.get('route')})")

    def phone(self, ad: RawAd, *, reveal: bool = False) -> list[str]:
        """Phones without a reveal = what the ad page already carries. `reveal=True` may call the site's phone
        endpoint (pace kind `phone`, day cap from site.yaml); never used in tests or dry runs."""
        return list(ad.phones)

    def is_live(self, url: str, *, country: str | None = None) -> Liveness:
        """Default: one read without following redirects, classified by `carhunt.sites.live` + site.yaml markers.
        `country`: check through that country's proxy exit (site.yaml `liveness.proxy_country`)."""
        if not self.meta.get("liveness", {}).get("supported", True):
            raise Unsupported(f"{self.id}: no liveness check")
        from carhunt.sites import live
        return live.check(self, url, country=country)

    def close(self) -> None:
        self.net.close()


# --- metadata ----------------------------------------------------------------

def overrides(site_id: str) -> dict:
    """config `sites.overrides[<id>]` ({} without a config: plugins and tests run on defaults)."""
    try:
        from carhunt.access import _core
        sec = _core.section("sites")
    except Exception:   # no config file yet / core not installed
        return {}
    return dict((sec.get("overrides") or {}).get(site_id) or {})


def slugify(s: str) -> str:
    """"Q4 e-tron" → "q4-e-tron", "ID.4" → "id.4" (dots kept: AS24/standvirtual slugs keep them)."""
    return re.sub(r"[^a-z0-9.]+", "-", s.lower()).strip("-")


def pkg_of(site_id: str) -> str:
    return site_id.replace(".", "_").replace("-", "_")


@cache
def load_meta(pkg: str) -> dict:
    data = yaml.safe_load((ROOT / pkg / "site.yaml").read_text(encoding="utf-8")) or {}
    data.setdefault("site", pkg)
    if hasattr(data.get("measured"), "isoformat"):   # YAML reads 2026-11-06 as a date
        data["measured"] = data["measured"].isoformat()
    return data


@cache
def load_codes(pkg: str) -> dict:
    """`codes.yaml`: make/model slugs + filter codes for the query builder (data, not code)."""
    p = ROOT / pkg / "codes.yaml"
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _pkgs() -> list[str]:
    fake = os.environ.get(FAKE_ENV) == "1"
    out = []
    for p in sorted(ROOT.glob("*/site.yaml")):
        name = p.parent.name
        if name == "fake" and not fake:
            continue
        if (p.parent / "plugin.py").exists():
            out.append(name)
    return out


def ids() -> list[str]:
    """Registered site ids (no plugin import)."""
    return [load_meta(p)["site"] for p in _pkgs()]


def metas() -> dict[str, dict]:
    return {load_meta(p)["site"]: load_meta(p) for p in _pkgs()}


def get(site_id: str, **kw) -> BaseSite:
    """Plugin instance for a site id (or package name). KeyError when unknown or not registered."""
    by_id = {load_meta(p)["site"]: p for p in _pkgs()}
    pkg = by_id.get(site_id) or (site_id if site_id in by_id.values() else None)
    if pkg is None:
        raise KeyError(f"unknown site {site_id!r} (known: {', '.join(sorted(by_id))})")
    mod = importlib.import_module(f"carhunt.sites.{pkg}.plugin")
    return mod.Plugin(**kw)


def for_url(url: str, **kw) -> BaseSite | None:
    """The plugin that owns an ad URL, or None."""
    host = url.split("/")[2].lower() if "://" in url else url.lower()
    for p in _pkgs():
        if any(re.search(rx, host) for rx in load_meta(p).get("hosts", [])):
            return get(p, **kw)
    return None


@contextlib.contextmanager
def fake_sites() -> Iterator[None]:
    """Test helper: register the synthetic site for the duration."""
    old = os.environ.get(FAKE_ENV)
    os.environ[FAKE_ENV] = "1"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(FAKE_ENV, None)
        else:
            os.environ[FAKE_ENV] = old
