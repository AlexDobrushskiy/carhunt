"""One-time SMS numbers for site signups: provider adapters behind a policy gate.

    from carhunt.access.accounts import sms
    sms.policy("leboncoin.fr")                          # Policy(allowed, reason)
    r = sms.rent("fr", "<service id>", site="leboncoin.fr")
    code = sms.wait_code(r)                             # no code in time → cancelled (refund)

Policy (site.yaml `account.verification`): rent only for **verify-once** sites (`sms-once`).
- `sms-own` (the site needs a phone that stays reachable): refused, use the owner's own mobile.
- Never for SMS-2FA-at-every-login sites (`sms-every-login`, e.g. marktplaats/2dehands): the rented number dies
  and the next login locks the account (11-02).
- A rented number dies right after its one SMS: the site can't change the phone later without a code to the dead
  number, so any future SMS challenge = lockout (leboncoin, 11-02). Try the owner's own mobile first
  (subito accepted a foreign EU mobile, 11-02); prefer a long-lived real number if the account matters.
- Some sites only receive domestic numbers (leboncoin: foreign SMS never arrived) → rent in the site's country.
Provider choice: compare per-service success rate, not price (5sim FR leboncoin 0.4–3.7 % vs SMSPool ~30 %, 11-02);
the cheapest pool returned a recycled number "already linked to an account" → cancel, take the next pool.
Pay only on a received code: cancel refunds when no SMS came.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from carhunt.access import _core, pace

VERIFY_ONCE = {"sms-once", "verify-once", "sms_once"}
SMS_EVERY_LOGIN = {"sms-every-login", "sms-2fa", "sms_2fa", "sms-each-login"}
SMS_OWN = {"sms-own"}

# transport(method, url, form) -> (status, json-decoded body)
Transport = Callable[[str, str, "dict | None"], tuple[int, Any]]


class SMSError(RuntimeError):
    pass


class PolicyRefused(SMSError):
    pass


@dataclass(frozen=True)
class Policy:
    site: str
    allowed: bool
    reason: str
    verification: str | None


def policy(site: str) -> Policy:
    """May we rent a one-time number for `site`? Unknown → no (fail closed)."""
    v = (pace.site_config(site).get("account") or {}).get("verification")
    v = str(v).strip().lower() if v else None
    if v in VERIFY_ONCE:
        return Policy(site, True, "verify-once site: a one-time number is acceptable, but the account will have no "
                                  "SMS recovery (the rented number dies after one SMS). Try the owner's own mobile "
                                  "first.", v)
    if v in SMS_EVERY_LOGIN:
        return Policy(site, False, "SMS 2FA at every new-device login: a rented number dies and the next login "
                                   "locks the account (11-02). Use the owner's own mobile or skip the site.", v)
    if v in SMS_OWN:
        return Policy(site, False, "the site needs a phone that stays reachable (login/recovery SMS): use the owner's "
                                   "own mobile, never a rented one-time number.", v)
    if v in {"none", "email", "email-link", "email-code", "google"}:
        return Policy(site, False, f"verification is {v!r}: no phone needed", v)
    return Policy(site, False, f"account.verification is {v!r} in site.yaml; renting needs an explicit "
                               "`sms-once` (fail closed)", v)


@dataclass
class Rental:
    id: str
    number: str
    country: str
    service: str
    provider: str
    cost: float | None = None
    pool: str | None = None
    created_at: float = field(default_factory=time.time)


class Provider:
    name = "base"

    def rent(self, country: str, service: str, *, pool: str | None = None) -> Rental:
        raise NotImplementedError

    def check(self, rental: Rental) -> str | None:
        """The received code, or None while waiting."""
        raise NotImplementedError

    def cancel(self, rental: Rental) -> bool:
        raise NotImplementedError

    def success_rates(self, country: str, service: str) -> list[tuple[str, float]]:
        """[(pool, success %)] best first; [] when the provider doesn't say."""
        return []


def _urllib_transport(method: str, url: str, form: dict | None) -> tuple[int, Any]:
    data = urllib.parse.urlencode(form or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "carhunt"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            st, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        st, raw = e.code, e.read()
    try:
        return st, json.loads(raw or b"null")
    except ValueError:
        return st, {"raw": raw.decode("utf-8", "replace")[:200]}


class SMSPoolProvider(Provider):
    """smspool.net API (key = orders-scope API key from secrets; never logged)."""
    name = "smspool"
    BASE = "https://api.smspool.net"

    def __init__(self, api_key_secret: str = "sms_api_key", transport: Transport | None = None):
        self.api_key_secret = api_key_secret
        self.transport = transport or _urllib_transport

    def __repr__(self) -> str:
        return "SMSPoolProvider()"

    def _key(self) -> str:
        k = _core.secret(self.api_key_secret)
        if not k:
            raise SMSError(f"secret {self.api_key_secret} missing (carhunt secret set {self.api_key_secret})")
        return k

    def _post(self, path: str, form: dict) -> Any:
        st, d = self.transport("POST", self.BASE + path, {"key": self._key(), **form})
        if st != 200:
            raise SMSError(f"smspool {path}: HTTP {st}")
        return d

    def rent(self, country: str, service: str, *, pool: str | None = None) -> Rental:
        form = {"country": country.upper(), "service": service}
        if pool:
            form["pool"] = pool
        d = self._post("/purchase/sms", form)
        if not isinstance(d, dict) or not d.get("success") or not d.get("order_id"):
            msg = (d or {}).get("message") if isinstance(d, dict) else None
            raise SMSError(f"smspool purchase refused: {msg or 'no order'}")
        return Rental(str(d["order_id"]), str(d.get("phonenumber") or d.get("number") or ""), country, service,
                      self.name, float(d["cost"]) if d.get("cost") not in (None, "") else None, pool)

    def check(self, rental: Rental) -> str | None:
        d = self._post("/sms/check", {"orderid": rental.id})
        code = d.get("sms") or d.get("code") if isinstance(d, dict) else None
        return str(code) if code and str(code) not in ("0", "") else None

    def cancel(self, rental: Rental) -> bool:
        d = self._post("/sms/cancel", {"orderid": rental.id})
        return bool(isinstance(d, dict) and d.get("success"))

    def success_rates(self, country: str, service: str) -> list[tuple[str, float]]:
        d = self._post("/request/success_rate", {"country": country.upper(), "service": service})
        rows = d if isinstance(d, list) else (d or {}).get("pools", []) if isinstance(d, dict) else []
        out = []
        for r in rows:
            try:
                out.append((str(r.get("pool") or r.get("name")), float(r.get("success_rate"))))
            except (TypeError, ValueError, AttributeError):
                continue
        return sorted(out, key=lambda x: -x[1])


PROVIDERS: dict[str, type[Provider]] = {"smspool": SMSPoolProvider}


def provider() -> Provider:
    cfg = _core.section("accounts").get("sms") or {}
    kind = str(cfg.get("provider") or "none").lower()
    if kind == "none":
        raise SMSError("no SMS provider configured: config accounts.sms.provider (smspool) + "
                       "`carhunt secret set sms_api_key`")
    if kind not in PROVIDERS:
        raise SMSError(f"unknown accounts.sms.provider {kind!r} (one of {', '.join(PROVIDERS)})")
    ref = cfg.get("api_key")
    name = (getattr(ref, "name", None) or str(ref)).removeprefix("secret:") if ref else "sms_api_key"
    return PROVIDERS[kind](name)


def rent(country: str, service: str, *, site: str, prov: Provider | None = None, pool: str | None = None,
         dry_run: bool = False) -> Rental | dict:
    """Rent one number for `site` after the policy gate. dry_run → the plan as a dict, nothing bought."""
    pol = policy(site)
    if not pol.allowed:
        raise PolicyRefused(f"{site}: {pol.reason}")
    if dry_run:
        return {"dry_run": True, "site": site, "country": country.upper(), "service": service, "pool": pool,
                "policy": pol.reason}
    p = prov or provider()
    if pool is None:
        rates = p.success_rates(country, service)
        pool = rates[0][0] if rates else None  # best success rate, not cheapest
    return p.rent(country, service, pool=pool)


def wait_code(rental: Rental, *, prov: Provider | None = None, timeout: float = 600, poll: float = 5,
              sleep=time.sleep) -> str:
    """Poll for the SMS code; on timeout cancel (refund) and raise TimeoutError. Pay only on a received code."""
    p = prov or provider()
    end = time.monotonic() + timeout
    while True:
        code = p.check(rental)
        if code:
            return code
        if time.monotonic() >= end:
            p.cancel(rental)
            raise TimeoutError(f"no SMS for order {rental.id} in {timeout:g}s; cancelled for a refund")
        sleep(poll)


def cancel(rental: Rental, *, prov: Provider | None = None) -> bool:
    return (prov or provider()).cancel(rental)


# ---------- CLI: carhunt sms policy SITE | carhunt sms rent … --dry-run ----------

def _cmd_policy(a) -> int:
    pol = policy(a.site)
    print(f"{'ALLOWED' if pol.allowed else 'REFUSED'} {a.site} (verification: {pol.verification}): {pol.reason}")
    return 0 if pol.allowed else 3


def _cmd_rent(a) -> int:
    try:
        r = rent(a.country, a.service, site=a.site, pool=a.pool, dry_run=a.dry_run)
    except PolicyRefused as e:
        print(f"REFUSED: {e}")
        return 3
    except SMSError as e:
        print(f"FAIL: {e}")
        return 1
    print(json.dumps(r if isinstance(r, dict) else asdict(r)))
    return 0


def register_cli(sub) -> None:
    p = sub.add_parser("sms", help="one-time SMS numbers (policy-gated)")
    p.set_defaults(_parser=p)
    s = p.add_subparsers(dest="sms_cmd", metavar="<cmd>")
    x = s.add_parser("policy", help="may we rent a number for SITE? (exit 0 allowed, 3 refused)")
    x.add_argument("site")
    x.set_defaults(func=_cmd_policy)
    x = s.add_parser("rent", help="rent one number (costs money unless --dry-run)")
    x.add_argument("--site", required=True)
    x.add_argument("--country", required=True)
    x.add_argument("--service", required=True, help="provider's service id for the site")
    x.add_argument("--pool")
    x.add_argument("--dry-run", action="store_true")
    x.set_defaults(func=_cmd_rent)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sms")
    register_cli(ap.add_subparsers(dest="group"))
    a = ap.parse_args(["sms", *(argv or [])])
    return int(a.func(a)) if hasattr(a, "func") else 2


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
