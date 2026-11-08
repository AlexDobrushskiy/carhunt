"""Saved HTML -> a page `detect` can classify, without a browser (CLI `detect --html`, tests).

A small DOM (html.parser) + a CSS subset: tag, #id, .class, [attr], [attr=v], [attr*=v], [attr^=v],
[attr$=v], descendant combinator, comma lists. "Visible" = no `hidden` attribute and no inline
display:none / visibility:hidden on the element or an ancestor. Boxes come from width/height
attributes or inline px styles (default 40x40; iframes 300x150 like a browser).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .detect import PROBES, TOKEN_SEL, FrameSnap, PageSnap

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


@dataclass
class Node:
    tag: str
    attrs: dict
    parent: Node | None = None
    children: list = field(default_factory=list)
    text: list = field(default_factory=list)

    def iter(self):
        for c in self.children:
            yield c
            yield from c.iter()

    @property
    def classes(self) -> list[str]:
        return (self.attrs.get("class") or "").split()

    def style(self) -> dict:
        out = {}
        for part in (self.attrs.get("style") or "").split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                out[k.strip().lower()] = v.strip().lower()
        return out

    def hidden_self(self) -> bool:
        st = self.style()
        return "hidden" in self.attrs or st.get("display") == "none" or st.get("visibility") == "hidden" \
            or (self.tag == "input" and (self.attrs.get("type") or "").lower() == "hidden")

    def visible(self) -> bool:
        n = self
        while n is not None:
            if n.hidden_self():
                return False
            n = n.parent
        return True

    def box(self) -> dict:
        st = self.style()
        dw, dh = (300, 150) if self.tag == "iframe" else (40, 40)

        def px(v, d):
            m = re.match(r"^\s*([\d.]+)\s*(px)?\s*$", v or "")
            return float(m.group(1)) if m else d
        return dict(x=0.0, y=0.0, width=px(st.get("width") or self.attrs.get("width"), dw),
                    height=px(st.get("height") or self.attrs.get("height"), dh))

    def inner_text(self) -> str:
        if self.tag in ("script", "style", "noscript", "template") or self.hidden_self():
            return ""
        parts = list(self.text)
        for c in self.children:
            parts.append(c.inner_text())
        return " ".join(p for p in (s.strip() for s in parts) if p)


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.text.append(data)


def parse(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


_SIMPLE = re.compile(r"""(?P<tag>^[a-zA-Z][\w-]*|^\*)|\#(?P<id>[\w-]+)|\.(?P<cls>[\w-]+)|
                         \[(?P<attr>[\w-]+)(?:(?P<op>[*^$]?=)["']?(?P<val>[^"'\]]*)["']?)?\]""", re.X)


def _compound(sel: str):
    conds, pos = [], 0
    while pos < len(sel):
        m = _SIMPLE.match(sel, pos)
        if not m or m.end() == pos:
            raise ValueError(f"unsupported selector part: {sel[pos:]!r}")
        conds.append(m.groupdict())
        pos = m.end()
    return conds


def _match_compound(n: Node, conds) -> bool:
    for c in conds:
        if c["tag"] and c["tag"] != "*" and n.tag != c["tag"].lower():
            return False
        if c["id"] and n.attrs.get("id") != c["id"]:
            return False
        if c["cls"] and c["cls"] not in n.classes:
            return False
        if c["attr"]:
            if c["attr"] not in n.attrs:
                return False
            v, op, want = n.attrs[c["attr"]], c["op"], c["val"]
            if op == "=" and v != want or op == "*=" and want not in v or op == "^=" and not v.startswith(want) \
                    or op == "$=" and not v.endswith(want):
                return False
    return True


def select(root: Node, selector: str) -> list[Node]:
    """Document-order elements matching a selector list."""
    chains = [[_compound(p) for p in part.split()] for part in selector.split(",") if part.strip()]
    out = []
    for n in root.iter():
        for chain in chains:
            if not _match_compound(n, chain[-1]):
                continue
            anc, ok = n.parent, True
            for conds in reversed(chain[:-1]):
                while anc is not None and anc.tag != "#document" and not _match_compound(anc, conds):
                    anc = anc.parent
                if anc is None or anc.tag == "#document":
                    ok = False
                    break
                anc = anc.parent
            if ok:
                out.append(n)
                break
    return out


def _probe(root: Node) -> dict:
    out = {}
    for k, sel in PROBES.items():
        els = select(root, sel)
        v = next((e for e in els if e.visible()), None)
        out[k] = {"present": bool(els), "box": v.box() if v else None}
    return out


class StaticFrame:
    def __init__(self, url: str, html: str, iframe: Node | None = None):
        self.url, self.html, self.root, self.iframe = url, html, parse(html), iframe

    def snap(self) -> FrameSnap:
        body = select(self.root, "body")
        text = (body[0] if body else self.root).inner_text()[:4000]
        fs = FrameSnap(self.url, text, _probe(self.root), ref=self)
        if self.iframe is not None:
            fs.box = self.iframe.box()
            fs.box_visible = fs.box if self.iframe.visible() else None
        return fs


class StaticPage:
    """A page from saved HTML. `frames` maps iframe src -> that frame's HTML (missing = empty document)."""

    def __init__(self, html: str, url: str = "https://example.invalid/", frames: dict[str, str] | None = None,
                 status: int = 200):
        self.url, self.html, self.status = url, html, status
        self.main_frame = StaticFrame(url, html)
        self.frames = [self.main_frame]
        for el in select(self.main_frame.root, "iframe"):
            src = el.attrs.get("src", "")
            self.frames.append(StaticFrame(src, (frames or {}).get(src, ""), el))

    def title(self) -> str:
        t = select(self.main_frame.root, "title")
        return t[0].inner_text() if t else ""

    def content(self) -> str:
        return self.html

    def static_token_len(self) -> int:
        n = 0
        for f in self.frames:
            for el in select(f.root, TOKEN_SEL):
                n = max(n, len(el.attrs.get("value") or "".join(el.text)))
        return n

    def static_snapshot(self, status: int | None = None) -> PageSnap:
        return PageSnap(self.url, self.title(), self.html[:6000], [f.snap() for f in self.frames],
                        self.static_token_len(), self.status if status is None else status)
