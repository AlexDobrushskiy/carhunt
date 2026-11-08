"""The one send guard for every channel. Pure: inputs in, Decision out; `say` does the I/O.

Rule order follows the EV guard (ev-say): mode → pause → caller → target → text → quiet hours
→ rate limits → mode rules (opener / nudge / reply) → seller hours → duplicate.
Campaign predicates (which cars may be nudged) come from config, never from code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .channels.base import URL_RE, Msg
from .ledger import Entry

OPENER, REPLY, NUDGE, APPROVED = "opener", "reply", "nudge", "approved"

# Multi-language heuristics (PT ES DE FR IT NL EN). Extend via contact.nudge.price_extra / no_extra.
PRICE_RE = (r"€|\beur(o|os)?\b|preç|precio|\bprix\b|\bpreis|prezzo|\bprijs|\bprices?\b|propost|\boferta|offerta"
            r"|\boffers?\b|\bbod\b|desconto|descuento|rabatt|sconto|remise|korting|negoci|negoti|verhandl|\bvb\b"
            r"|trattabil|onderhandel|last price|best price")
NO_SOLD_RE = (r"vendid[oa]|\bsold\b|verkauft|\bvendue?\b|vendut[oa]|verkocht|reservad|reserviert|réservée?|riservat"
              r"|gereserveerd|já não est|ya no est|nicht mehr (verfügbar|da|zu haben)|plus disponible"
              r"|non (è )?più disponibile|niet meer beschikbaar|no longer available|not available any"
              r"|interessad[oa]s? não|não (estou |estamos )?interessad|no me interesa|kein interesse"
              r"|pas intéressé|non (sono )?interessat|geen interesse|not interested")


@dataclass
class Request:
    channel: str
    channel_kind: str  # chat | email | site
    to: str
    text: str
    mode: str = REPLY
    role: str = ""
    max_len: int = 500
    channel_refusal: str | None = None  # Channel.check_text result


@dataclass
class Context:
    settings: dict[str, Any]
    now: datetime  # aware, owner tz
    ledger: list[Entry]
    thread: list[Msg] | None = None  # None = channel can't read it and cardb had nothing
    car: dict[str, Any] | None = None
    paused: bool = False
    caller_problem: str | None = None  # set by say when the active-agent check fails
    overrides: dict[str, int] = field(default_factory=dict)  # limit name → max, today only


@dataclass
class Decision:
    ok: bool
    rule: str = ""
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


class Refused(Exception):
    def __init__(self, rule: str, reason: str):
        super().__init__(reason)
        self.rule, self.reason = rule, reason


def _no(rule: str, reason: str) -> None:
    raise Refused(rule, reason)


# ---- small helpers ---------------------------------------------------------------------------

def parse_window(s: str) -> tuple[time, time]:
    a, b = s.split("-")
    return time.fromisoformat(a.strip()), time.fromisoformat(b.strip())


def in_window(t: datetime, window: str) -> bool:
    """[start, end); a window crossing midnight (22:00-06:00) wraps."""
    a, b = parse_window(window)
    x = t.timetz().replace(tzinfo=None)
    return a <= x < b if a <= b else (x >= a or x < b)


_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def day_window(profile: dict[str, str], wd: int) -> str | None:
    """Pick the window for weekday `wd` from keys like 'mon-fri', 'sat', 'mon-sun'."""
    for key, win in profile.items():
        if "-" in key:
            a, b = key.split("-")
            if _DAYS.index(a) <= wd <= _DAYS.index(b):
                return win
        elif _DAYS.index(key) == wd:
            return win
    return None


def digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


def norm_target(to: str, kind: str) -> str:
    if kind == "chat":
        return digits(to)
    if kind == "email":
        return to.strip().lower().partition("#")[0]  # 'addr#thread' → addr
    return to.strip()


def seller_tz(s: dict[str, Any], req: Request, car: dict[str, Any] | None) -> ZoneInfo | None:
    if req.channel_kind == "chat":
        n = digits(req.to)
        for k in (n[:3], n[:2], n[:1]):
            if k in s["phone_tz"]:
                return ZoneInfo(s["phone_tz"][k])
    country = _car_country(car)
    if country and country in s["country_tz"]:
        return ZoneInfo(s["country_tz"][country])
    return None


def _car_country(car: dict[str, Any] | None) -> str | None:
    if not car:
        return None
    for key in ("country", "seller.country"):
        v = get_field(car, key)
        if v:
            return str(v).upper()
    for li in car.get("listings") or []:
        if li.get("country"):
            return str(li["country"]).upper()
    return None


def get_field(car: dict[str, Any], dotted: str) -> Any:
    if dotted == "power_hp":
        kw = car.get("power_kw")
        return round(kw * 1.36) if kw else None
    cur: Any = car
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def matches(pred: dict[str, Any], car: dict[str, Any]) -> bool:
    """Config predicate: {field, eq|ne|in|not_in|between|gte|lte|truthy} or {all: [...]}/{any: [...]}."""
    if "all" in pred:
        return all(matches(p, car) for p in pred["all"])
    if "any" in pred:
        return any(matches(p, car) for p in pred["any"])
    v = get_field(car, pred["field"])
    if "eq" in pred:
        return v == pred["eq"]
    if "ne" in pred:
        return v != pred["ne"]
    if "in" in pred:
        return v in pred["in"]
    if "not_in" in pred:
        return v not in pred["not_in"]
    if "between" in pred:
        lo, hi = pred["between"]
        return v is not None and lo <= v <= hi
    if "gte" in pred:
        return v is not None and v >= pred["gte"]
    if "lte" in pred:
        return v is not None and v <= pred["lte"]
    if "truthy" in pred:
        return bool(v) == bool(pred["truthy"])
    raise ValueError(f"bad predicate {pred!r}")


def car_contacts(car: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    seller = car.get("seller") or {}
    for c in seller.get("contacts") or []:
        if c.get("shared"):
            continue  # a shared call-centre number never identifies the seller (cardb rule)
        v = str(c.get("value") or "")
        out.add(digits(v) if c.get("kind") in ("phone", "whatsapp") else v.strip().lower())
    for li in car.get("listings") or []:
        if li.get("url"):
            out.add(str(li["url"]).strip())
    return out


# ---- rate limits -----------------------------------------------------------------------------

def _limit_applies(lim: dict[str, Any], channel: str, is_site: bool, mode: str) -> bool:
    chans = lim.get("channels", "*")
    if chans != "*" and channel not in chans and not (is_site and "sites" in chans):
        return False
    kind = lim.get("kind", "any")
    return kind == "any" or kind == mode


def _entry_in_scope(lim: dict[str, Any], e: Entry, channel: str) -> bool:
    chans = lim.get("channels", "*")
    site = e.channel not in ("whatsapp", "email")
    if chans != "*" and e.channel not in chans and not (site and "sites" in chans):
        return False
    if lim.get("per_channel") and e.channel != channel:
        return False
    kind = lim.get("kind", "any")
    return kind == "any" or e.kind == kind


def check_limits(req: Request, ctx: Context) -> None:
    now_ts = ctx.now.timestamp()
    today = ctx.now.date()
    tz = ctx.now.tzinfo
    is_site = req.channel_kind == "site"
    for lim in ctx.settings["limits"]:
        if not _limit_applies(lim, req.channel, is_site, req.mode):
            continue
        rows = [e for e in ctx.ledger if e.counts and _entry_in_scope(lim, e, req.channel)]
        name = lim["name"]
        if lim.get("min_gap_s") and rows:
            last = max(e.t for e in rows)
            if now_ts - last < lim["min_gap_s"]:
                nxt = datetime.fromtimestamp(last + lim["min_gap_s"], tz).strftime("%H:%M:%S")
                _no(name, f"{name}: last send {int(now_ts - last)} s ago (< {lim['min_gap_s']} s); next allowed {nxt}")
        per = lim.get("per")
        if per:
            cap = int(ctx.overrides.get(name, lim["max"]))
            if per == "hour":
                n = sum(1 for e in rows if now_ts - e.t < 3600)
            else:
                n = sum(1 for e in rows if datetime.fromtimestamp(e.t, tz).date() == today)
            if n >= cap:
                _no(name, f"{name}: cap {cap}/{per} reached ({n})")
            res = lim.get("reserve")
            if res and req.role != res["role"] and n >= cap - int(res["slots"]):
                until = time.fromisoformat(res["until"])
                if ctx.now.timetz().replace(tzinfo=None) < until:
                    _no(name, f"{name}: the last {res['slots']} slots are {res['role']}'s until {res['until']}")


# ---- the guard -------------------------------------------------------------------------------

def evaluate(req: Request, ctx: Context) -> Decision:
    try:
        _evaluate(req, ctx)
    except Refused as r:
        return Decision(False, r.rule, r.reason)
    return Decision(True, "ok", "all rules pass")


def _evaluate(req: Request, ctx: Context) -> None:
    s = ctx.settings
    text = req.text.strip()
    to = norm_target(req.to, req.channel_kind)
    mine = [e for e in ctx.ledger if norm_target(e.to, req.channel_kind) == to and e.channel == req.channel]
    own_texts = "\n".join(e.text for e in ctx.ledger)
    thread = ctx.thread

    if ctx.paused:
        _no("pause", "PAUSE file present")
    if ctx.caller_problem:
        _no("caller", ctx.caller_problem)

    # target: a known contact of a known car (allow-list)
    car = ctx.car
    if car is not None:
        if car.get("status") in s.get("blocked_statuses", ["dropped", "closed", "bought"]) and req.mode != APPROVED:
            _no("target", f"car status {car.get('status')}: target is closed")
        if not s["allow_unlisted"] and to not in car_contacts(car):
            _no("target", f"{to} is not a contact/listing of car {car.get('id')} in cardb")
    elif not s["allow_unlisted"]:
        _no("target", "no car: pass --car so the target can be checked against cardb")

    # text
    if not text:
        _no("text", "empty text")
    if req.channel_refusal:
        _no("text", req.channel_refusal)
    if len(text) > req.max_len:
        _no("text", f"text length {len(text)} > {req.max_len}: split at a sentence")
    if req.mode == OPENER:
        o = s["opener"]
        if URL_RE.search(text):
            _no("opener-text", "URL in an opener (the seller knows the ad; a link reads like a bot)")
        if re.search(o["spec_pattern"], text, re.I):
            _no("opener-text", "specs in an opener (no km/kWh/hp/price: the ad already says it)")
        if len(text) > o["max_chars"]:
            _no("opener-text", f"opener is {len(text)} chars (> {o['max_chars']}): short openers get answered")
        if text.count("?") > o["max_questions"]:
            _no("opener-text", f"{text.count('?')} questions (max {o['max_questions']})")

    # time
    if in_window(ctx.now, s["quiet_hours"]):
        _no("quiet-hours", f"quiet hours {s['quiet_hours']} ({ctx.now:%H:%M} owner time)")

    check_limits(req, ctx)

    if req.mode == OPENER:
        if (thread and any(m.from_me for m in thread)) or any(e.counts for e in mine):
            _no("opener", "chat already has a message from us/the owner: not an opener")
        tz = seller_tz(s, req, car) or ctx.now.tzinfo
        local = ctx.now.astimezone(tz)
        if not in_window(local, s["opener_window"]):
            _no("opener", f"openers only {s['opener_window']} seller-local (now {local:%a %H:%M})")
    elif req.mode == NUDGE:
        _nudge(req, ctx, mine, own_texts)
    else:
        if thread is None:
            if not any(e.counts for e in mine):
                _no("reply", "no thread and no earlier send: use --opener for a first message")
        elif not thread:
            _no("reply", "empty chat: use --opener for a first message")
        else:
            last = thread[-1]
            if req.mode != APPROVED and last.from_me:
                _no("double", "latest message is already ours: no double messages (--nudge for the one follow-up)")
            if not last.from_me and (ctx.now - last.at).total_seconds() < s["reply"]["min_seller_age_s"]:
                _no("reply-age", f"seller's message is < {s['reply']['min_seller_age_s'] // 60} min old: wait")
            back = timedelta(minutes=s["reply"]["owner_backoff_min"])
            for m in thread:
                if m.from_me and ctx.now - m.at < back and m.text[:60] not in own_texts:
                    _no("owner", f"the owner wrote in this chat in the last {s['reply']['owner_backoff_min']} min: "
                                 "he's handling it")

    # seller-local business hours for channels that need them (abroad email/site)
    ch_cfg = _channel_cfg(s, req)
    profile = ch_cfg.get("seller_hours")
    if profile and req.mode != NUDGE:
        if profile is True:
            profile = (get_field(car or {}, "seller.type") or get_field(car or {}, "seller_type") or "dealer")
            profile = "private" if profile == "private" else "dealer"
        _seller_hours(s, req, car, ctx.now, str(profile))

    # duplicate
    head = text[: s["duplicate_prefix"]]
    if any(e.counts and head and head in e.text for e in mine) or \
            (thread and any(m.from_me and head and head in m.text for m in thread)):
        _no("duplicate", "the same text was already sent to this target")


def _channel_cfg(s: dict[str, Any], req: Request) -> dict[str, Any]:
    chans = s.get("channels") or {}
    base = dict(chans.get("sites") or {}) if req.channel_kind == "site" else {}
    base.update(chans.get(req.channel) or {})
    return base


def _seller_hours(s: dict[str, Any], req: Request, car: dict[str, Any] | None, now: datetime, profile: str) -> None:
    tz = seller_tz(s, req, car)
    if tz is None:
        _no("seller-hours", f"no timezone for target {req.to[:6]}…: add its prefix/country to contact.phone_tz/country_tz")
    local = now.astimezone(tz)
    win = day_window(s["seller_hours"][profile], local.weekday())
    if not win or not in_window(local, win):
        _no("seller-hours", f"seller-local {local:%a %H:%M} outside {win or 'closed day'} ({profile})")


def _nudge(req: Request, ctx: Context, mine: list[Entry], own_texts: str) -> None:
    s, n = ctx.settings, ctx.settings["nudge"]
    thread = ctx.thread
    if thread is None:
        _no("nudge", "nudge: thread unreadable (needs the channel or cardb messages)")
    if not thread:
        _no("nudge", "nudge: empty chat")
    last = thread[-1]
    if not last.from_me:
        _no("nudge", "nudge: latest message is the seller's: reply normally instead")
    age = ctx.now - last.at
    if age < timedelta(hours=n["after_h"]):
        _no("nudge", f"nudge: our last message is {age.total_seconds() / 3600:.1f} h old (< {n['after_h']} h)")
    for m in thread:
        if m.from_me and (not m.text.strip() or m.text[:60] not in own_texts):
            _no("nudge", "nudge: the owner wrote in this chat himself (a message of ours not in the ledger): his chat")
    real, prev_ours = False, None
    for m in thread:
        if m.from_me:
            prev_ours = m.at
            continue
        if not m.is_content:
            continue
        if prev_ours and (m.at - prev_ours).total_seconds() < n["auto_reply_s"]:
            continue
        real = True
    if not real:
        _no("nudge", "nudge: the seller never really replied in this chat (only our messages / auto-replies)")
    if any(e.kind == NUDGE and e.counts for e in mine):
        _no("nudge", "nudge: this chat already had its one nudge")
    if any(e.kind == APPROVED and e.counts for e in mine):
        _no("nudge", "nudge: the owner approved a message here (price stage / his call)")
    price = re.compile(PRICE_RE + ("|" + n["price_extra"] if n.get("price_extra") else ""), re.I)
    nosold = re.compile(NO_SOLD_RE + ("|" + n["no_extra"] if n.get("no_extra") else ""), re.I)
    for m in thread:
        if price.search(m.text):
            _no("nudge", f"nudge: price talk in this chat ({m.text[:50]!r})")
        if not m.from_me and nosold.search(m.text):
            _no("nudge", f"nudge: seller said no/sold ({m.text[:50]!r})")
    car = ctx.car
    if car is None:
        _no("nudge", "nudge: car unknown in cardb")
    if car.get("status") not in n["statuses"]:
        _no("nudge", f"nudge: cardb status {car.get('status')} (only {'/'.join(n['statuses'])})")
    for p in n.get("exclude") or []:
        if matches(p, car):
            _no("nudge", f"nudge: car matches exclude rule {p.get('why') or p}")
    if not any(matches(p, car) for p in n.get("qualify") or []):
        _no("nudge", f"nudge: car {car.get('id')} isn't really good (no qualify rule matches)")
    _seller_hours(s, req, car, ctx.now, n.get("seller_hours") or "dealer")
