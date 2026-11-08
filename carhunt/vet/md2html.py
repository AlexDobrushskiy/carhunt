"""Markdown report -> one self-contained, phone-friendly HTML page (light/dark).

Extras over plain markdown: [V]/[A]/[I] and [verified]/[anecdotal] tags -> pills,
**low/medium/high** -> risk pills, "- [ ] " -> checkboxes, tables scroll on phones,
and with `cards=True` every table turns into label/value cards below 720 px.

    python -m carhunt.vet.md2html report.md [-o report.html] [--title T] [--cards]
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

CSS = """
:root{--bg:#f7f6f3;--card:#fff;--ink:#1d1d1b;--muted:#6b6a66;--line:#e3e1db;--accent:#1f5fbf;
--good:#1b7f4b;--warn:#a86400;--bad:#b3261e;--goodbg:#e6f4ec;--warnbg:#fbf0dc;--badbg:#fbe6e4;--th:#f0eee9}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141413;--card:#1e1e1c;--ink:#ecebe7;
--muted:#a3a29c;--line:#34332f;--accent:#7fb0ff;--good:#5fd394;--warn:#f0b35a;--bad:#ff8a80;--goodbg:#163325;
--warnbg:#3a2c12;--badbg:#3d1c1a;--th:#262624}}
:root[data-theme="dark"]{--bg:#141413;--card:#1e1e1c;--ink:#ecebe7;--muted:#a3a29c;--line:#34332f;--accent:#7fb0ff;
--good:#5fd394;--warn:#f0b35a;--bad:#ff8a80;--goodbg:#163325;--warnbg:#3a2c12;--badbg:#3d1c1a;--th:#262624}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,sans-serif}
main{max-width:1060px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0 0 6px}h2{font-size:20px;margin:36px 0 10px;padding-top:12px;border-top:2px solid var(--line)}
h3{font-size:16px;margin:22px 0 6px}a{color:var(--accent);overflow-wrap:anywhere}p,li{overflow-wrap:break-word}
ul{padding-left:20px}li{margin:3px 0}
li.chk{list-style:none;margin-left:-20px;padding-left:24px;position:relative}
li.chk::before{content:"";position:absolute;left:2px;top:5px;width:12px;height:12px;border:1.5px solid var(--muted);border-radius:3px}
.tw{overflow-x:auto;margin:10px 0;border:1px solid var(--line);border-radius:8px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}
th{background:var(--th);font-weight:600}tr:last-child td{border-bottom:none}
.tag,.res{display:inline-block;font-size:11px;font-weight:700;padding:0 6px;border-radius:9px;vertical-align:1px}
.tag.v,.res.low{background:var(--goodbg);color:var(--good)}
.tag.a,.res.medium{background:var(--warnbg);color:var(--warn)}
.tag.i{background:var(--th);color:var(--muted)}
.res.high{background:var(--badbg);color:var(--bad)}.res.none{background:var(--th);color:var(--muted)}
blockquote{margin:10px 0;padding:8px 12px;border-left:3px solid var(--accent);background:var(--card);border-radius:0 8px 8px 0}
code{font-size:13px;background:var(--th);padding:0 4px;border-radius:4px}
@media (max-width:720px){.cards thead{display:none}.cards tr{display:block;padding:10px 0;border-bottom:1px solid var(--line)}
.cards td{display:block;border:none;padding:3px 12px}
.cards td::before{content:attr(data-label);display:block;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase}}
"""

_TAGS = {"V": ("v", "verified"), "A": ("a", "anecdotal"), "I": ("i", "inferred")}


def _pills(body: str) -> str:
    body = re.sub(r"(?:<strong>)?\[(verified|anecdotal)\](?:</strong>)?",
                  lambda m: f'<span class="tag {m.group(1)[0]}">{m.group(1)}</span>', body)
    body = re.sub(r"(?:<strong>)?\[([VAI])\](?:</strong>)?",
                  lambda m: f'<span class="tag {_TAGS[m.group(1)][0]}" title="{_TAGS[m.group(1)][1]}">'
                            f'{m.group(1)}</span>', body)
    return re.sub(r"<strong>((?:[Ll]ow|[Mm]edium|[Hh]igh|[Nn]one)(?:[–-](?:low|medium|high))?)</strong>",
                  lambda m: f'<span class="res {m.group(1).lower().split("–")[-1].split("-")[-1]}">'
                            f'{m.group(1).lower()}</span>', body)


def _cards(table: str) -> str:
    heads = [re.sub("<[^>]+>", "", h) for h in re.findall(r"<th[^>]*>(.*?)</th>", table, flags=re.S)]

    def row(m: re.Match) -> str:
        it = iter(heads)
        return re.sub(r"<td([^>]*)>", lambda t: f'<td{t.group(1)} data-label="{html.escape(next(it, ""))}">',
                      m.group(0))
    table = re.sub(r"<tr>.*?</tr>", row, table, flags=re.S)
    return table.replace("<table>", '<table class="cards">', 1)


def convert(md_text: str, *, title: str | None = None, cards: bool = False) -> str:
    import markdown  # optional dependency: pip install carhunt[vet]

    body = markdown.markdown(md_text, extensions=["tables", "toc", "sane_lists", "attr_list"])
    body = _pills(body).replace("<li>[ ] ", '<li class="chk">')
    if cards:
        body = re.sub(r"<table>.*?</table>", lambda m: _cards(m.group(0)), body, flags=re.S)
    body = re.sub(r"<table([^>]*)>", r'<div class="tw"><table\1>', body).replace("</table>", "</table></div>")
    if not title:
        m = re.search(r"^#\s+(.+)$", md_text, flags=re.M)
        title = m.group(1).strip() if m else "Report"
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{html.escape(title)}</title>\n<style>{CSS}</style></head>\n"
            f"<body><main>\n{body}\n</main></body></html>\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="md2html", description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--title")
    ap.add_argument("--cards", action="store_true", help="tables become cards on phones")
    a = ap.parse_args(argv)
    src = Path(a.src)
    out = Path(a.out) if a.out else src.with_suffix(".html")
    out.write_text(convert(src.read_text(encoding="utf-8"), title=a.title, cards=a.cards), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
