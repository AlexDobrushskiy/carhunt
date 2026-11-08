"""Ad liveness classifier (measured on real ads 11-04) and the default `is_live` for plugins.

Verdicts: live · gone (404/410 or the site's own marker → removed at once) · gone_soft (redirect from the ad to a
list page → removed only on a 2nd soft signal ≥1 h later) · blocked (403/429/5xx/bot page: stop the site, write
nothing) · unknown (200 without the ad id, network error: write nothing) · follow (same ad id under a new URL).

Per-site markers live in site.yaml `liveness:` — `gone_redirect` (regex on the redirect target), `gone_text`
(regex on the page), `gone_title` (regex on <title> only: the phrase may sit in every page's i18n data),
`sold_text` (regex: the site keeps the page but flags it sold).
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING

from carhunt.access.errors import Blocked
from carhunt.sites._net import Response, bot_page
from carhunt.sites.extract import title
from carhunt.sites.model import Liveness

if TYPE_CHECKING:
    from carhunt.sites.base import BaseSite


def classify(url: str, status: int, final: str | None, hint: dict, *, rules: dict | None = None,
             ad_id=None) -> tuple[str, str]:
    """status/final = the ad URL's answer (final = Location or post-redirect URL); hint = page facts
    {title, has_id, bot, sold, gone_text}. `ad_id(url)` extracts ids to tell a slug move from a list redirect."""
    rules = rules or {}
    if hint.get("bot") or status in (401, 403, 429) or status >= 500:
        return "blocked", f"{status} bot" if hint.get("bot") else f"{status}"
    if status in (404, 410):
        return "gone", f"{status} {hint.get('title') or ''}".strip()[:80]
    if status == 0:
        return "unknown", "network error"
    if final and final.split("#")[0] != url and (status == 200 or 300 <= status < 400):
        gr = rules.get("gone_redirect")
        if gr and re.search(gr, final):                   # the site's own "ad gone" redirect
            return "gone", f"{status} redirect {final[:100]}"
        fid = ad_id(final) if ad_id else None
        if fid and fid == (ad_id(url) if ad_id else None):
            return ("live", f"moved {final[:100]}") if status == 200 else ("follow", final)
        return "gone_soft", f"redirect to {final[:100]}"
    if status == 200:
        if hint.get("sold"):
            return "gone", "200 sold flag"
        if hint.get("gone_text"):
            return "gone", f"200 {hint.get('title') or 'gone marker'}"[:80]
        if hint.get("has_id"):
            return "live", "200"
        return "unknown", f"200 without ad id ({hint.get('title') or ''})"[:80]
    return "unknown", f"{status}"


def hint_of(text: str, aid: str | None, rules: dict | None = None) -> dict:
    rules = rules or {}
    has_id = bool(aid and aid in text)
    return {"title": (title(text) or "")[:80] or None, "has_id": has_id, "bot": bot_page(text, aid),
            "sold": bool(rules.get("sold_text") and re.search(rules["sold_text"], text)),
            "gone_text": bool(rules.get("gone_text") and re.search(rules["gone_text"], text, re.I))
            or bool(rules.get("gone_title") and re.search(rules["gone_title"], title(text) or "", re.I))}


def to_liveness(site: str, url: str, verdict: str, signal: str, moved: str | None = None) -> Liveness:
    if verdict == "blocked":
        raise Blocked(signal, site=site, url=url)
    if verdict == "gone":
        return Liveness("removed", signal)
    if verdict == "gone_soft":
        return Liveness("removed", signal, soft=True)
    if verdict == "live":
        return Liveness("live", signal, moved_to=moved)
    return Liveness("unknown", signal)


def with_price(site: BaseSite, url: str, lv: Liveness, text: str) -> Liveness:
    """Add the current price of a live ad from the page we already have (liveness catches price drops on known
    listings; newest-first sweeps never revisit them)."""
    if lv.state != "live" or not text:
        return lv
    ad = site.ad_from_page(lv.moved_to or url, text)
    if ad is None or ad.price is None:
        return lv
    return replace(lv, price=ad.price, price_is_net=ad.price_is_net, ad_status=ad.status)


def check(site: BaseSite, url: str, *, country: str | None = None) -> Liveness:
    """Default is_live: one read-only GET without following redirects (HTTP route, or via a `country` exit) or
    one in-tab fetch (browser routes)."""
    rules = site.meta.get("liveness") or {}
    aid = site.ad_id(url)
    if country or site.meta.get("route", "http") == "http":   # Net.get adds the site's own country_ip
        r: Response = site.net.get(url, follow=False, check=False, ad_id=aid, country=country)
        final = r.location
    else:
        r = site.net.browser_get(url, mode=rules.get("mode", "fetch"), check=False, ad_id=aid)
        final = r.final_url
    v, sig = classify(url, r.status, final, hint_of(r.text, aid, rules), rules=rules, ad_id=site.ad_id)
    if v == "follow" and final:   # AS24 308: same ad, new slug → check the new URL once
        r2 = site.net.get(final, follow=False, check=False, ad_id=aid, country=country)
        v, sig2 = classify(final, r2.status, r2.location, hint_of(r2.text, aid, rules), rules=rules, ad_id=site.ad_id)
        lv = to_liveness(site.id, url, "unknown" if v == "follow" else v, f"moved→{sig2}", moved=final)
        return with_price(site, url, lv, r2.text)
    return with_price(site, url, to_liveness(site.id, url, v, sig), r.text)
