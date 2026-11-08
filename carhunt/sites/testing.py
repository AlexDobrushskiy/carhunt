"""Offline transport for tests (sites, discover, integrator): serves canned answers, records every request."""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from carhunt.sites._net import Response, raise_for

Answer = Response | str | dict | list | Callable[[str], "Response | str | dict | list"]


class FakeNet:
    """`routes`: {url or regex: answer}. A str answer = 200 text, dict/list = 200 JSON, Response = as is.
    Unmatched URLs → AssertionError (a test must never reach the network)."""

    def __init__(self, site: str = "fake", routes: dict[str, Answer] | None = None):
        self.site = site
        self.routes: dict[str, Answer] = dict(routes or {})
        self.calls: list[tuple[str, str, str]] = []   # (via, kind, url)
        self.loads = 0

    def add(self, pattern: str, answer: Answer) -> FakeNet:
        self.routes[pattern] = answer
        return self

    def _answer(self, url: str) -> Response:
        for pat, ans in self.routes.items():
            if pat == url or re.search(pat, url):
                if callable(ans) and not isinstance(ans, Response):
                    ans = ans(url)
                if isinstance(ans, Response):
                    return ans
                if isinstance(ans, (dict, list)):
                    import json
                    return Response(200, url, json.dumps(ans))
                return Response(200, url, str(ans))
        raise AssertionError(f"FakeNet: no route for {url}")

    def gate(self, kind: str = "load", *, country: str | None = None) -> None:
        if kind == "load" and not country:
            self.loads += 1

    def get(self, url: str, *, kind: str = "load", ad_id: str | None = None, check: bool = True,
            follow: bool = True, country: str | None = None, **_: Any) -> Response:
        self.gate(kind, country=country)
        self.calls.append((f"http@{country}" if country else "http", kind, url))
        r = self._answer(url)
        if follow and r.location and 300 <= r.status < 400:
            r = Response(200, url, self._answer(r.location).text, final_url=r.location)
        return raise_for(self.site, r, ad_id=ad_id) if check else r

    def json(self, url: str, **kw: Any) -> Any:
        return self.get(url, **kw).json()

    def browser_get(self, url: str, *, kind: str = "load", ad_id: str | None = None, check: bool = True,
                    **_: Any) -> Response:
        self.gate(kind)
        self.calls.append(("tab", kind, url))
        r = self._answer(url)
        return raise_for(self.site, r, ad_id=ad_id) if check else r

    def close(self) -> None:
        pass


def fixture(path: str | Path, name: str) -> str:
    """Read a fixture file next to a test module: fixture(__file__, 'search.html')."""
    p = Path(path)
    base = p.parent if p.suffix else p
    return (base / "fixtures" / name).read_text(encoding="utf-8")
