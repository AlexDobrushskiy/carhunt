"""Pull a page's own data out of HTML: one parse instead of scraping markup (fewer loads, stable fields).

Shapes seen on the supported sites: Next.js `__NEXT_DATA__`, Next.js RSC flight chunks (`self.__next_f.push`),
`window.__INITIAL_PROPS__` (coches/milanuncios), `window.__CONFIG__` (marktplaats), JSON-LD.
"""
from __future__ import annotations

import json
import re
from typing import Any

_NEXT = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)', re.S)
_LDJSON = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict | None:
    m = _NEXT.search(html)
    return json.loads(m.group(1)) if m else None


def page_props(html: str) -> dict | None:
    d = next_data(html)
    return ((d or {}).get("props") or {}).get("pageProps") if d else None


def flight(html: str) -> str:
    """Concatenated RSC flight payload (the JSON strings pushed into self.__next_f), decoded."""
    return "".join(json.loads(s) for s in _FLIGHT.findall(html))


def objects_after(text: str, key: str) -> list[Any]:
    """Every JSON value that follows `"key":` in already-decoded text (objects/arrays via raw_decode)."""
    out, dec = [], json.JSONDecoder()
    for m in re.finditer(rf'"{re.escape(key)}":', text):
        try:
            out.append(dec.raw_decode(text, m.end())[0])
        except json.JSONDecodeError:
            continue
    return out


def flight_objects(html: str, key: str) -> list[Any]:
    """`objects_after` on the page's decoded flight payload (decode once and use objects_after for many keys)."""
    return objects_after(flight(html), key)


def flight_ref_text(stream: str, ref: str) -> str | None:
    """RSC text record: '$4a' → the text at '\\n4a:T<hex byte length>,<text>' (length in UTF-8 bytes)."""
    m = re.search(rf"(?:^|\n){re.escape(ref[1:])}:T([0-9a-fA-F]+),", stream)
    if not m:
        return None
    return stream[m.end():].encode("utf-8")[:int(m.group(1), 16)].decode("utf-8", "ignore")


def window_var(html: str, name: str) -> Any:
    """`window.NAME = {...};` or `window.NAME = JSON.parse("...")`."""
    m = re.search(rf"window\.{re.escape(name)}\s*=\s*", html)
    if not m:
        return None
    rest = html[m.end():]
    if rest.startswith("JSON.parse("):
        s, _ = json.JSONDecoder().raw_decode(rest[len("JSON.parse("):])
        return json.loads(s)
    return json.JSONDecoder().raw_decode(rest)[0]


def json_ld(html: str) -> list[dict]:
    out: list[dict] = []
    for raw in _LDJSON.findall(html):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for x in d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []:
            if isinstance(x, dict):
                out.append(x)
    return out


def title(html: str) -> str | None:
    m = re.search(r"<title[^>]*>([^<]*)", html)
    return m.group(1).strip() if m else None


# --- value helpers --------------------------------------------------------------

def num(v: Any) -> int | None:
    """Integer from 34900, "34.900 €", "34 900", "299.0" (decimal, not thousands), "1,234". None when no digits."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    s = str(v).strip()
    if re.fullmatch(r"-?\d+\.\d{1,2}", s):        # "299.0" / "12.5": a decimal (Wallapop hp bug, fixed 11-04)
        return int(round(float(s)))
    digits = re.sub(r"[^\d]", "", s.split(",")[0] if re.search(r",\d{1,2}$", s) else s)
    return int(digits) if digits else None


def year_month(v: Any) -> str | None:
    """"YYYY-MM" from "2022-03-15", "03/2022", "2022-03", 2022 → "2022"."""
    if v is None:
        return None
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d{1,2})[/.-](\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"(\d{4})$", s)
    return m.group(1) if m else None


def year_of(v: Any) -> int | None:
    ym = year_month(v)
    return int(ym[:4]) if ym else None
