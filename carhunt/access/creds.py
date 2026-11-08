"""Site account credentials through core secrets: `site_<domain>_user` / `site_<domain>_pass` (dots → `_`).

    from carhunt.access import creds
    user, pw = creds.login("coches.net")       # use inside the script that types it; never print, log or snapshot
    creds.new("coches.net", "<YOUR_EMAIL>")     # generate + store a strong password (refuses to overwrite)

Never print a credential, not even masked (no `grep` on a creds folder: output lands in the transcript).
Never snapshot/screenshot a sign-in page with the password typed.
"""
from __future__ import annotations

import re
import secrets as _rand
import string

from carhunt.access import _core


class CredentialsMissing(KeyError):
    pass


def key(site: str) -> str:
    """Secret-name stem for a site domain: `www.Leboncoin.fr` → `leboncoin_fr`."""
    d = site.strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0].removeprefix("www.")
    return re.sub(r"[^a-z0-9]+", "_", d).strip("_")


def names(site: str) -> tuple[str, str]:
    k = key(site)
    return f"site_{k}_user", f"site_{k}_pass"


def exists(site: str) -> bool:
    u, p = names(site)
    return _core.secret_exists(u) and _core.secret_exists(p)


def login(site: str) -> tuple[str, str]:
    """(user, password) for `site`; raises CredentialsMissing with the fix line. The result must never be printed."""
    u, p = names(site)
    user, pw = _core.secret(u), _core.secret(p)
    if not user or not pw:
        raise CredentialsMissing(f"no stored login for {site}: `carhunt secret set {u}` and `carhunt secret set {p}`, "
                                 f"or creds.new({site!r}, USER)")
    return user, pw


def new_password(n: int = 18) -> str:
    """Letters + digits + one symbol every site form accepts; always upper, lower, digit and symbol."""
    alpha = string.ascii_letters + string.digits
    while True:
        pw = "".join(_rand.choice(alpha) for _ in range(n - 2)) + _rand.choice("!#%*") + _rand.choice(string.digits)
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


def new(site: str, user: str, *, overwrite: bool = False) -> str:
    """Generate a password for `site` and store user + password in core secrets. Returns the secret names
    (never the password). Refuses when a password is already stored: overwriting it loses the live login."""
    if not user:
        raise ValueError("user is required (the account's email/login; there is no default)")
    u, p = names(site)
    if _core.secret_exists(p) and not overwrite:
        raise FileExistsError(f"{p} already stored; refusing to overwrite a live password")
    _core.set_secret(u, user)
    _core.set_secret(p, new_password())
    return f"{u}, {p}"


# ---------- CLI: carhunt creds new|status (prints secret NAMES only, never a value) ----------

def _cmd_new(a) -> int:
    import sys
    user = sys.stdin.readline().strip() if a.user == "-" else a.user
    try:
        names_ = new(a.site, user, overwrite=a.overwrite)
    except (ValueError, FileExistsError) as e:
        print(f"creds: {e}", file=sys.stderr)
        return 3
    print(f"stored {names_} (password generated; type it with creds.login() inside the signup script)")
    return 0


def _cmd_status(a) -> int:
    u, p = names(a.site)
    ok = exists(a.site)
    print(f"{a.site}: {'stored' if ok else 'missing'} ({u}, {p})")
    return 0 if ok else 1


def register_cli(sub) -> None:
    p = sub.add_parser("creds", help="site account credentials (core secrets; values are never printed)")
    p.set_defaults(_parser=p)
    s = p.add_subparsers(dest="creds_cmd", metavar="<cmd>")
    x = s.add_parser("new", help="generate + store a password for SITE's account (refuses to overwrite)")
    x.add_argument("site", help="site id or domain, e.g. coches.net")
    x.add_argument("--user", required=True, help="the account's login/email ('-' = read one line from stdin)")
    x.add_argument("--overwrite", action="store_true", help="replace a stored password (loses the live login)")
    x.set_defaults(func=_cmd_new)
    x = s.add_parser("status", help="is a login stored for SITE? (exit 0 stored, 1 missing)")
    x.add_argument("site")
    x.set_defaults(func=_cmd_status)
