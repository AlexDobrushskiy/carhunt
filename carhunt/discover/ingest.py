"""Normalized listing → cardb. Facts only: identity, specs, evidence. No scoring, no merging (both live in cardb).

Rules:
- Upsert the car WITHOUT photos, then add photos to the listing's car — photo-based auto-merge on dealer stock
  galleries can merge different cars into one.
- Every later write resolves the car by listing URL (`find_listing`), never a car id kept from earlier: after a
  merge the old id may point at another car.
- Identity keys (VIN, plate, phone, dealer stock ref) go in as fields/facts; cardb decides links and duplicates.
- cardb fills empty car fields only (no `overwrite`): a re-read never replaces photo / seller / PR-code evidence.
- A known listing whose site ask did not move and that is still live = no write at all (re-runs are free); a price
  change (re-read + normalized, so derived gross / cash asks stay right) or a relisting = one minimal upsert.
- A phone cardb did not attach (owned by another seller) → fact `phone_route` = site chat.
- Price refused by cardb's sanity check (422 `reason`): `price_lease` = a monthly rate / deposit, not a sale → dropped.
  Any other reason (`price_x100`, `price_range`, `price_net`) → the car is stored WITHOUT a price and the ask goes
  in `price_note` for an agent to check the ad (`cardb listing set … --price-vat` / `--force`). Why: newest-first
  cursors move past the ad, so a dropped car is never seen again; a stored ×100 price skews every ranking.
- A 400 on one ad (a field cardb refuses) rejects that ad only; cardb down / 5xx stops the run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from carhunt.discover.normalize import Listing


def _is_not_found(e: Exception) -> bool:
    return type(e).__name__ == "NotFound" or getattr(e, "status", None) == 404


def _is_api_error(e: Exception) -> bool:
    return type(e).__name__ in ("ApiError", "NotFound", "Conflict") or hasattr(e, "status")


def _refused(e: Exception) -> bool:
    """cardb refused this one write (400 bad field, 422 sanity); not an outage."""
    return _is_api_error(e) and getattr(e, "status", None) in (400, 422)


def _price_reason(e: Exception) -> str | None:
    body = getattr(e, "body", None)
    return body.get("reason") if getattr(e, "status", None) == 422 and isinstance(body, dict) else None


DROP_PRICE_REASONS = ("price_lease",)   # not a sale price: drop the ad


@dataclass
class Result:
    action: str                     # created | linked | updated | unchanged | rejected | would_create | would_update
    url: str
    car_id: int | None = None
    listing_id: int | None = None
    linked_by: str | None = None
    reason: str | None = None
    duplicates: list[Any] = field(default_factory=list)
    photos_added: int = 0
    photo_errors: list[str] = field(default_factory=list)
    payload: dict | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], 0) or k == "action"}


class Ingest:
    def __init__(self, db: Any, *, dry_run: bool = False, max_photos: int = 40):
        self.db, self.dry_run, self.max_photos = db, dry_run, max_photos

    def known(self, url: str) -> dict | None:
        """The cardb listing for this URL, or None. Other errors (cardb down) propagate: stop the run."""
        try:
            return self.db.find_listing(url)
        except Exception as e:
            if _is_not_found(e):
                return None
            raise

    def sighting(self, lst: Listing, existing: dict, *, price_changed: bool = False) -> Result:
        """Known listing seen again in search results. `price_changed` = the site's ask moved since the last sweep
        (compared on the site's own number: cardb's stored price can be a derived gross or a cash ask)."""
        live = existing.get("status") in (None, "live")
        if not price_changed and live:
            return Result("unchanged", lst.url, car_id=existing.get("car_id"), listing_id=existing.get("id"))
        body: dict[str, Any] = {"url": lst.url}
        if price_changed and lst.price is not None:
            body.update(price=lst.price, price_vat="gross")
            if lst.price_note:
                body["price_note"] = lst.price_note
        if self.dry_run:
            return Result("would_update", lst.url, payload=body)
        try:
            res = self.db.upsert_listing(body)
        except Exception as e:
            if _refused(e):  # the stored price stays; the report + dispositions name the ad
                return Result("rejected", lst.url, reason=_reason(e))
            raise
        return Result("updated", lst.url, car_id=res.get("car_id"), listing_id=res.get("listing_id"))

    def write(self, lst: Listing) -> Result:
        body = lst.to_upsert()
        if self.dry_run:
            return Result("would_create", lst.url, payload=body)
        held = None
        try:
            res = self.db.upsert_listing(body)
        except Exception as e:
            if not _refused(e):
                raise
            why = _price_reason(e)
            if not why or why in DROP_PRICE_REASONS or body.get("price") is None:
                return Result("rejected", lst.url, reason=_reason(e))
            held = f"price held ({why}): stored without price"
            body = _without_price(body, why)
            try:
                res = self.db.upsert_listing(body)
            except Exception as e2:
                if _refused(e2):
                    return Result("rejected", lst.url, reason=_reason(e2))
                raise
        action = "created" if res.get("car_created") else "linked" if res.get("listing_created") else "updated"
        out = Result(action, lst.url, linked_by=res.get("linked_by"), duplicates=res.get("duplicate_candidates") or [])
        hit = self.db.find_listing(lst.url)                 # resolve by URL, never by the id we just got
        out.car_id, out.listing_id = hit["car_id"], hit["id"]
        for i, url in enumerate(lst.photos[: self.max_photos]):
            try:
                self.db.photo_add(hit["car_id"], url=url, source="ad", listing=hit["id"])
                out.photos_added += 1
            except Exception as e:  # one bad photo must not lose the car
                if not _is_api_error(e):
                    raise
                out.photo_errors.append(f"#{i}: {e}")
        if lst.phones:
            self._check_phones(lst, out)
        if held:
            out.reason = "; ".join(r for r in (held, out.reason) if r)
        return out

    def _check_phones(self, lst: Listing, out: Result) -> None:
        car_id = self.db.find_listing(lst.url)["car_id"]
        car = self.db.car(car_id)
        got = {re.sub(r"\D", "", c.get("value", "")) for c in ((car.get("seller") or {}).get("contacts") or [])
               if c.get("kind") in ("phone", "whatsapp")}
        missing = [p for p in lst.phones if p not in got]
        if missing:
            self.db.fact(car_id, "phone_route", "site chat: phone not attached (owned by another seller in cardb)",
                         source="agent_inference")
            out.reason = "phone not attached"


def _without_price(body: dict, why: str) -> dict:
    out = {k: v for k, v in body.items() if k not in ("price", "price_vat")}
    note = f"site ask {body['price']} € refused by cardb ({why}): check the ad, then set the price"
    out["price_note"] = f"{note}; {body['price_note']}" if body.get("price_note") else note
    return out


def _reason(e: Exception) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return f"cardb 422 {body.get('reason') or ''}: {body.get('error') or ''}".strip()
    return f"cardb 422: {e}"
