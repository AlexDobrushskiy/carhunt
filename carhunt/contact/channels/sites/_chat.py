"""Selector-driven engine shared by the marketplace senders (not a channel itself: `_` modules are
skipped by the registry).

A site module subclasses `ChatSite`, sets selectors/markers as class attrs, and overrides a hook
only where the site's flow differs. Selectors can be overridden per site without a code change:
`contact.sites.<site>.selectors.<attr>` in config (sites change their DOM; EV run, Nov 2026).

send():  open → walls/login/gone checks → open the form → duplicate guard → fill → submit →
         post-submit dialogs → read the page. Outcome in `SendResult.raw`:
         confirmed (site's own success text/URL), in_thread (our text now in the thread and the box
         cleared), submitted (the click happened), refused/blocked/gone/login.
verify(): delivered on confirmed|in_thread; failed when nothing was submitted; else unknown
         (a timeout after the click may still have delivered: network errors ≠ failed, 2026-11-05).
"""
from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar

from ..base import DELIVERED, FAILED, UNKNOWN, ChannelError, Msg, SendResult
from .base import SiteChannel


def norm(s: str | None) -> str:
    return " ".join((s or "").split())


def head(text: str) -> str:
    """What the duplicate guard compares: the text's first 60 chars, whitespace-normalised."""
    return norm(text)[:60]


class Abort(Exception):
    """Stop before (or without) a successful submit; `raw` lands in SendResult.raw."""

    def __init__(self, error: str, **raw: Any):
        super().__init__(error)
        self.raw = raw


# Bubbles: when a site has no `msg_sel`, a message is the innermost element whose class/data-* tokens
# say message/bubble; ours when its row carries an own/outgoing/sent/me token. Unverified per site:
# confirm on the first live read and pin real selectors in config when it misses.
_MSGS_JS = r"""
([msgSel, mineSel, textSel, timeSel]) => {
  const toks = e => {
    let s = (typeof e.className === 'string' ? e.className : (e.getAttribute('class') || '')) + ' ' + (e.getAttribute('data-testid') || '');
    for (const a of e.attributes) if (a.name.startsWith('data-') && !/^(false|0)$/i.test(a.value)) s += ' ' + a.name.slice(5) + ' ' + a.value;
    return ' ' + s.toLowerCase().replace(/[_\-]+/g, ' ') + ' ';
  };
  const MSG = / (message|msg|bubble|chat item)s? /;
  const NOT = / (list|input|form|composer|header|count|counter|badge|preview|date|time|timestamp|status|avatar|inbox|unread|actions|menu|icon|editor|textarea|placeholder|empty) /;
  const MINE = / (own|outgoing|outbound|sent|me|mine|self|right|from me|is me|buyer) /;
  let els;
  if (msgSel) els = [...document.querySelectorAll(msgSel)];
  else {
    const c = [...document.body.querySelectorAll('*')].filter(e => {
      const t = toks(e); return MSG.test(t) && !NOT.test(t) && (e.innerText || '').trim() &&
        !e.querySelector('textarea,input,[contenteditable="true"]');
    });
    els = c.filter(e => !c.some(o => o !== e && e.contains(o)));
  }
  const row = e => { let r = e;
    while (r.parentElement && r.parentElement !== document.body && els.filter(o => r.parentElement.contains(o)).length === 1) r = r.parentElement;
    return r; };
  return els.map(e => {
    const r = row(e);
    const t = textSel ? (e.querySelector(textSel) || e) : e;
    let mine;
    if (mineSel) mine = e.matches(mineSel) || !!e.closest(mineSel);
    else { mine = false; for (let x = e; x; x = x === r ? null : x.parentElement) if (MINE.test(toks(x))) { mine = true; break; } }
    const tm = timeSel ? r.querySelector(timeSel) : r.querySelector('time');
    return {text: (t.innerText || '').trim(), mine, label: e.getAttribute('aria-label') || '',
            at: tm ? (tm.getAttribute('datetime') || tm.getAttribute('title') || (tm.innerText || '').trim()) : ''};
  });
}
"""

_CONVS_JS = r"""
([convSel, unreadSel]) => [...document.querySelectorAll(convSel)].map((e, i) => {
  const a = e.matches('a[href]') ? e : e.querySelector('a[href]');
  const t = ' ' + [e, ...e.querySelectorAll('*')].map(x => (typeof x.className === 'string' ? x.className : '')).join(' ').toLowerCase().replace(/[_\-]+/g, ' ') + ' ';
  const unread = unreadSel ? !!(e.matches(unreadSel) || e.querySelector(unreadSel)) : / (unread|not read|badge|new) /.test(t);
  return {i, href: a ? a.href : '', title: ((e.innerText || '').trim().split('\n')[0] || '').slice(0, 120), unread};
})
"""


class ChatSite(SiteChannel):
    # --- page checks (plain substrings; blocked_html is searched in the HTML, the rest in title+text) --
    blocked_markers: ClassVar[tuple[str, ...]] = ("Zugriff verweigert", "Access denied", "Pardon Our Interruption",
                                                  "Request blocked", "eres un bot")
    blocked_html: ClassVar[tuple[str, ...]] = ()
    login_url_parts: ClassVar[tuple[str, ...]] = ()
    login_markers: ClassVar[tuple[str, ...]] = ()
    gone_markers: ClassVar[tuple[str, ...]] = ()
    error_markers: ClassVar[tuple[str, ...]] = ()  # the site's own "not sent" text after submit
    success_url_parts: ClassVar[tuple[str, ...]] = ()  # URL after submit that means sent (only if not there before)

    # --- form -------------------------------------------------------------------------------------
    consent_buttons: ClassVar[tuple[str, ...]] = ()  # cookie banner, by button name
    consent_css: ClassVar[str] = "#onetrust-accept-btn-handler, #didomi-notice-agree-button"
    open_form: ClassVar[tuple[Any, ...]] = ()  # button/link names (str or regex) that reveal the form
    form_css: ClassVar[str] = ""  # submit/persona/clear/uncheck are looked up inside this ("" → page)
    box: ClassVar[str] = "textarea"
    submit_names: ClassVar[tuple[Any, ...]] = ()  # submit button by name (tried first, last match wins)
    submit_css: ClassVar[str] = ""  # fallback submit selector; neither → press Enter in the box
    confirm_names: ClassVar[tuple[str, ...]] = ()  # post-submit "send anyway" dialogs
    persona_fields: ClassVar[dict[str, str]] = {}  # selector → persona key, filled before submit
    clear_css: ClassVar[str] = ""  # fields emptied before submit (keep the buyer's phone private)
    uncheck_css: ClassVar[str] = ""  # checkboxes unticked before submit (newsletter, share phone)

    # --- thread / inbox ---------------------------------------------------------------------------
    open_thread: ClassVar[tuple[Any, ...]] = ()  # names that reveal the chat panel on an ad page
    thread_css: ClassVar[str] = ""  # container the duplicate guard reads ("" → whole page)
    msg_sel: ClassVar[str] = ""  # "" → heuristic (see _MSGS_JS)
    mine_sel: ClassVar[str] = ""
    text_sel: ClassVar[str] = ""
    time_sel: ClassVar[str] = ""
    inbox_url: ClassVar[str] = ""
    conv_sel: ClassVar[str] = ""
    unread_sel: ClassVar[str] = ""
    max_poll_threads: ClassVar[int] = 8

    # --- timing -----------------------------------------------------------------------------------
    load_ms: ClassVar[int] = 5000
    settle_ms: ClassVar[int] = 5000
    box_timeout_ms: ClassVar[int] = 15000
    # Off-screen plain-chrome windows ignore Playwright's mouse clicks: click in the DOM (Subito/KA, 2026-11-02).
    js_click: ClassVar[bool] = True
    can_poll: ClassVar[bool] = False

    def __init__(self, cfg: dict[str, Any] | None = None, **kw: Any):
        super().__init__(cfg, **kw)
        site = ((self.cfg.get("contact") or {}).get("sites") or {}).get(self.name) or {}
        self._sel = site.get("selectors") or {}

    def s(self, key: str) -> Any:
        """Selector/marker by attr name, config override first."""
        return self._sel.get(key, getattr(self, key))

    @property
    def persona(self) -> dict[str, Any]:
        return (self.cfg.get("contact") or {}).get("persona") or {}

    # ================================================================ send
    def send(self, to: str, text: str) -> SendResult:
        submitted = False
        try:
            with self.tab() as page, self.own_pages(page):
                start = self.target_url(page, self.normalize_to(to))
                self.goto(page, start)
                page = self.reveal_form(page)
                box = self.find_box(page)
                before = self.thread_text(page)
                if self.already_in_thread(self.messages(page), text) or head(text) in norm(before):
                    # An opener went out twice (2026-11-01): never send what the thread already shows.
                    return SendResult(False, error="duplicate: this text is already in the thread",
                                      raw={"refused": "duplicate", "submitted": False})
                self.fill(page, box, text)
                self.prepare(page)
                url_before = page.url
                submitted = True
                self.submit(page, box)
                self.after_submit(page)
                page.wait_for_timeout(self.settle_ms)
                return self.outcome(page, box, text, before, url_before)
        except Abort as e:
            return SendResult(False, error=str(e), raw={"submitted": submitted, **e.raw})
        except Exception as e:  # Playwright timeouts/target closed; after the click → unknown, not failed
            return SendResult(False, error=f"{type(e).__name__}: {e}"[:400], raw={"submitted": submitted})

    def verify(self, to: str, text: str, result: SendResult) -> str:
        raw = result.raw or {}
        if raw.get("confirmed") or raw.get("in_thread"):
            return DELIVERED
        if not raw.get("submitted") or raw.get("site_error"):
            return FAILED
        return UNKNOWN

    # -- hooks (override per site) ----------------------------------------------------------------
    def target_url(self, page: Any, to: str) -> str:
        """URL to open for a send (ad or conversation)."""
        return to

    def thread_url(self, page: Any, to: str) -> str:
        return self.target_url(page, to)

    def goto(self, page: Any, url: str) -> None:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(self.load_ms)
        self.dismiss_consent(page)
        self.check_page(page)

    def reveal_form(self, page: Any) -> Any:
        """Make the message box visible; may return another page (form in a new tab)."""
        if self.s("open_form") and not self.visible(page, self.s("box")):
            btn = self.find_button(page, self.s("open_form"))
            if btn is None:
                raise Abort("no message button on the page (already contacted, ad gone or layout changed)",
                            no_form=True)
            self.click(btn)
            page.wait_for_timeout(2500)
            self.check_page(page)
        return page

    def find_box(self, page: Any) -> Any:
        box = page.locator(self.s("box")).first
        try:
            box.wait_for(state="visible", timeout=self.box_timeout_ms)
        except Exception:
            self.check_page(page)
            raise Abort("message box not found", no_form=True)
        return box

    def fill(self, page: Any, box: Any, text: str) -> None:
        box.fill(text)
        page.wait_for_timeout(600)

    def prepare(self, page: Any) -> None:
        scope = self.scope(page)
        for sel, key in self.s("persona_fields").items():
            loc = scope.locator(sel)
            if not loc.count():
                continue
            val = self.persona.get(key)
            if not val:
                if not (loc.first.input_value() or "").strip():
                    raise Abort(f"form needs contact.persona.{key}", config=True)
                continue
            loc.first.fill(str(val))
        if self.s("clear_css"):
            for el in scope.locator(self.s("clear_css")).all():
                try:
                    el.fill("")
                except Exception:
                    pass
        if self.s("uncheck_css"):
            for cb in scope.locator(self.s("uncheck_css")).all():
                try:
                    if cb.is_checked():
                        cb.evaluate("e => e.click()")
                except Exception:
                    pass

    def submit(self, page: Any, box: Any) -> None:
        scope = self.scope(page)
        btn = self.find_button(scope, self.s("submit_names"), last=True) if self.s("submit_names") else None
        if btn is None and self.s("submit_css"):
            loc = scope.locator(self.s("submit_css"))
            btn = loc.last if loc.count() else None
        if btn is None:
            box.press("Enter")
        else:
            self.click(btn)

    def after_submit(self, page: Any) -> None:
        if not self.s("confirm_names"):
            return
        page.wait_for_timeout(2500)
        btn = self.find_button(page, self.s("confirm_names"))
        if btn is not None:
            self.click(btn)

    def outcome(self, page: Any, box: Any, text: str, before: str, url_before: str) -> SendResult:
        body = self.page_text(page)
        confirmed = self.confirmed(body) or any(p in page.url and p not in url_before
                                                for p in self.s("success_url_parts"))
        try:
            cleared = not (box.input_value(timeout=2000) or "").strip()
        except Exception:
            try:
                cleared = not (box.inner_text(timeout=2000) or "").strip()  # contenteditable boxes
            except Exception:
                cleared = None  # box gone (form replaced by a confirmation)
        h = head(text)
        in_thread = bool(cleared) and h in norm(self.thread_text(page)) and h not in norm(before)
        err = next((m for m in self.s("error_markers") if m.lower() in body.lower()), "")
        raw = {"submitted": True, "confirmed": confirmed, "in_thread": in_thread, "cleared": cleared,
               "url": page.url}
        if err and not (confirmed or in_thread):
            raw["site_error"] = err
            return SendResult(False, error=f"site says: {err}", raw=raw)
        return SendResult(True, raw=raw)

    # ================================================================ read
    def read_thread(self, to: str, limit: int = 50) -> list[Msg]:
        if not self.can_read:
            raise ChannelError(f"{self.name}: reading threads is not supported")
        try:
            with self.tab() as page, self.own_pages(page):
                self.goto(page, self.thread_url(page, self.normalize_to(to)))
                self.reveal_thread(page)
                msgs = self.messages(page)
        except Abort as e:
            raise ChannelError(f"{self.name}: {e}") from e
        except ChannelError:
            raise
        except Exception as e:
            raise ChannelError(f"{self.name}: thread read failed: {type(e).__name__}: {e}"[:300]) from e
        if not msgs:
            raise ChannelError(f"{self.name}: no messages found (no thread yet, or selectors need updating)")
        return msgs[-limit:]

    def reveal_thread(self, page: Any) -> None:
        names = self.s("open_thread")
        if names:
            btn = self.find_button(page, names)
            if btn is not None:
                self.click(btn)
                page.wait_for_timeout(3000)

    def messages(self, page: Any) -> list[Msg]:
        try:
            rows = page.evaluate(_MSGS_JS, [self.s("msg_sel"), self.s("mine_sel"), self.s("text_sel"),
                                            self.s("time_sel")])
        except Exception:
            return []
        now = datetime.now(UTC)
        out = []
        for r in rows:
            if not r["text"]:
                continue
            at = parse_time(r.get("at", ""))
            out.append(Msg(at=at or now, from_me=self.is_mine(r), text=r["text"],
                           raw={"at_parsed": at is not None, "label": r.get("label", "")}))
        return out

    def is_mine(self, row: dict[str, Any]) -> bool:
        return bool(row.get("mine"))

    def poll(self, since: datetime) -> list[tuple[str, Msg]]:
        """Inbound tail (after our last message) of unread conversations. `at` is the bubble time when
        the site shows one, else the poll time: the watcher dedupes by thread + text."""
        if not (self.can_poll and self.s("inbox_url") and self.s("conv_sel")):
            return []
        since = since if since.tzinfo else since.replace(tzinfo=UTC)
        out: list[tuple[str, Msg]] = []
        try:
            with self.tab() as page:
                self.goto(page, self.s("inbox_url"))
                convs = page.evaluate(_CONVS_JS, [self.s("conv_sel"), self.s("unread_sel")])
                todo = [c for c in convs if c["unread"]]
                if not todo:  # Wallapop: no per-row flag, the tab title says "(N) …" (site_poll, 2026-11-02)
                    m = re.match(r"\s*\((\d+)\)", page.title())
                    todo = convs[: int(m.group(1))] if m else []
                for c in todo[: self.max_poll_threads]:
                    page.locator(self.s("conv_sel")).nth(c["i"]).evaluate("e => e.click()")
                    page.wait_for_timeout(4000)
                    msgs = self.messages(page)
                    last_mine = max((i for i, m in enumerate(msgs) if m.from_me), default=-1)
                    who = c["href"] or c["title"]
                    for m in msgs[last_mine + 1:]:
                        if m.raw.get("at_parsed") and m.at < since:
                            continue
                        m.sender = c["title"]
                        out.append((who, m))
                    if not page.locator(self.s("conv_sel")).count():  # single-pane UI: back to the list
                        page.go_back()
                        page.wait_for_timeout(3000)
        except Abort as e:
            raise ChannelError(f"{self.name}: {e}") from e
        return out

    # ================================================================ helpers
    def scope(self, page: Any) -> Any:
        css = self.s("form_css")
        return page.locator(css).first if css and page.locator(css).count() else page

    @staticmethod
    @contextlib.contextmanager
    def own_pages(page: Any) -> Iterator[None]:
        """Close tabs the step opened (mobile.de's form opens a new one); the tab factory closes its own."""
        try:
            known = {id(p) for p in page.context.pages}
        except Exception:
            known = None
        try:
            yield
        finally:
            if known is not None:
                for p in list(page.context.pages):
                    if id(p) not in known:
                        try:
                            p.close()
                        except Exception:
                            pass

    def dismiss_consent(self, page: Any) -> None:
        try:
            css = self.s("consent_css")
            if css and page.locator(css).count():
                page.locator(css).first.evaluate("e => e.click()")
                page.wait_for_timeout(1000)
                return
            btn = self.find_button(page, self.s("consent_buttons"))
            if btn is not None:
                btn.evaluate("e => e.click()")
                page.wait_for_timeout(1000)
        except Exception:
            pass

    def check_page(self, page: Any) -> None:
        url = page.url
        text = self.page_text(page)[:4000]
        low = (page.title() + " " + text).lower()
        hit = next((m for m in self.s("blocked_markers") if m.lower() in low), None)
        if hit is None and self.s("blocked_html"):
            html = page.content()
            hit = next((m for m in self.s("blocked_html") if m in html), None)
        if hit:
            raise Abort(f"blocked: {hit!r}: stop this site for now", blocked=True)
        if any(p in url for p in self.s("login_url_parts")) or any(m.lower() in low for m in self.s("login_markers")):
            raise Abort("not logged in", login=True)
        gone = next((m for m in self.s("gone_markers") if m.lower() in low), None)
        if gone:
            raise Abort(f"ad gone: {gone!r}", gone=True)

    def find_button(self, page: Any, names: Sequence[Any], last: bool = False) -> Any:
        for n in names:
            for role in ("button", "link"):
                loc = page.get_by_role(role, name=n)  # str = case-insensitive substring; regex for exact
                if loc.count():
                    return loc.last if last else loc.first
        for n in names:
            if isinstance(n, str):
                loc = page.get_by_text(n, exact=False).filter(visible=True)
                if loc.count():
                    return loc.last if last else loc.first
        return None

    def click(self, loc: Any) -> None:
        if self.js_click:
            loc.evaluate("e => e.click()")
        else:
            loc.click(timeout=10000)

    @staticmethod
    def visible(page: Any, sel: str) -> bool:
        loc = page.locator(sel)
        return bool(loc.count()) and loc.first.is_visible()

    @staticmethod
    def page_text(page: Any) -> str:
        try:
            return page.inner_text("body", timeout=5000)
        except Exception:
            return ""

    def thread_text(self, page: Any) -> str:
        css = self.s("thread_css")
        if css and page.locator(css).count():
            try:
                return page.locator(css).first.inner_text(timeout=5000)
            except Exception:
                pass
        return self.page_text(page)


def parse_time(s: str) -> datetime | None:
    s = (s or "").strip()
    if not re.match(r"\d{4}-\d{2}-\d{2}", s):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def item_ref(url: str, pattern: str) -> str | None:
    m = re.search(pattern, url)
    return m.group(1) if m else None
