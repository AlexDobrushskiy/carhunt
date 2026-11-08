"""Trust-cookie jar: bot-check cookies (DataDome, Akamai, Cloudflare, Imperva, PerimeterX…) shared between profiles.

A captcha solved in one browser carries to the others, so a site is never solved twice.
Only bot-check cookies move, never logins. The jar is a Chrome `Cookies` SQLite DB at `settings.jar_path`
holding Chrome's encrypted values; every profile we launch uses `--use-mock-keychain --password-store=basic`,
so all share one fixed key and the encrypted values are portable.

    export_from(profile)   profile → jar (after its Chrome closed cleanly)
    import_into(profile)   jar → profile (before its Chrome starts)
    get(domain, name)      decrypted value for plain-HTTP helpers; never log it
    delete(domain, name)   drop a poisoned cookie (a banned datadome cookie keeps every browser blocked
                           on that site; test with --fresh first)
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from carhunt.access import _core
from carhunt.access import settings as _settings

TRUST = re.compile(r"^(datadome|_abck|bm_sz|bm_sv|bm_mi|ak_bmsc|cf_clearance|__cf_bm|reese84|"
                   r"incap_ses_.*|visid_incap_.*|nlbi_.*|_px.*|__ddg.*|aws-waf-token)$")
_EPOCH_DELTA_S = 11644473600  # Chrome timestamps: µs since 1601-01-01
# Mock keychain (macOS) / basic store (Linux) passwords; key = PBKDF2-SHA1(pw, "saltysalt", 1003), 16 bytes.
_PASSWORDS = (b"mock_password", b"peanuts")


def jar_path() -> Path:
    return _settings.load().jar_path


def cookie_db(profile: Path | str) -> Path:
    """The profile's Cookies DB: Default/Cookies on macOS/Linux, Default/Network/ on Windows."""
    d = Path(profile) / "Default"
    for p in (d / "Cookies", d / "Network" / "Cookies"):
        if p.exists():
            return p
    return d / "Network" / "Cookies" if sys.platform == "win32" else d / "Cookies"


def chrome_now() -> int:
    return int((time.time() + _EPOCH_DELTA_S) * 1_000_000)


def chrome_to_unix(t: int) -> float:
    return t / 1e6 - _EPOCH_DELTA_S


def _cols(con: sqlite3.Connection) -> list[str]:
    return [r[1] for r in con.execute("PRAGMA table_info(cookies)")]


def _read_rows(db: Path) -> list[dict]:
    """All cookie rows, read from a copy (a running Chrome may hold the DB)."""
    if not db.exists():
        return []
    tmp = Path(tempfile.mkdtemp(prefix="carhunt-ck-"))
    try:
        shutil.copy2(db, tmp / "c")
        for suffix in ("-journal", "-wal"):
            side = db.with_name(db.name + suffix)
            if side.exists():
                shutil.copy2(side, tmp / f"c{suffix}")
        con = sqlite3.connect(tmp / "c")
        try:
            cols = _cols(con)
            return [dict(zip(cols, r, strict=True)) for r in con.execute("select * from cookies")]
        finally:
            con.close()
    except (OSError, sqlite3.Error) as e:
        print(f"jar: could not read {db}: {e}", file=sys.stderr)
        return []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def trust_rows(db: Path) -> list[dict]:
    """Unexpired persistent trust cookies in a Cookies DB."""
    now = chrome_now()
    return [r for r in _read_rows(db)
            if TRUST.match(r["name"]) and r.get("has_expires", 1) and r["expires_utc"] > now]


def _merge(rows: Iterable[dict], db: Path) -> int:
    """Upsert rows into a Cookies DB no running Chrome uses; the newer last_update_utc wins."""
    con = sqlite3.connect(db)
    n = 0
    try:
        cols = set(_cols(con))
        for r in rows:
            k = (r["host_key"], r["name"], r["path"])
            cur = con.execute("select max(last_update_utc) from cookies where host_key=? and name=? and path=?",
                              k).fetchone()[0]
            if cur is not None and cur >= r["last_update_utc"]:
                continue
            keys = [c for c in r if c in cols]
            try:
                con.execute("delete from cookies where host_key=? and name=? and path=?", k)
                con.execute(f"insert into cookies ({','.join(keys)}) values ({','.join('?' * len(keys))})",
                            [r[c] for c in keys])
                n += 1
            except sqlite3.Error as e:
                print(f"jar: skip cookie {k[1]}@{k[0]}: {e}", file=sys.stderr)
        con.commit()
    finally:
        con.close()
    return n


def _init_jar(template: Path, jar: Path) -> None:
    """New jar = a copy of a real Cookies DB (same schema + meta version), emptied."""
    jar.parent.mkdir(parents=True, exist_ok=True)
    tmp = jar.with_suffix(".new")
    shutil.copy2(template, tmp)
    con = sqlite3.connect(tmp)
    con.execute("delete from cookies")
    con.commit()
    con.execute("vacuum")
    con.close()
    tmp.replace(jar)


def export_from(profile: Path | str) -> int:
    """Copy a profile's trust cookies into the jar. Returns the number of rows written."""
    db = cookie_db(profile)
    rows = trust_rows(db)
    if not rows:
        return 0
    with _core.flock("jar"):
        jar = jar_path()
        if not jar.exists():
            _init_jar(db, jar)
        return _merge(rows, jar)


def import_into(profile: Path | str) -> int:
    """Seed a profile (its Chrome must not be running) with the jar's trust cookies."""
    with _core.flock("jar"):
        jar = jar_path()
        rows = trust_rows(jar)
        if not rows:
            return 0
        db = cookie_db(profile)
        if not db.exists():
            db.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(jar, db)
            return len(rows)
    return _merge(rows, db)


def _hosts(domain: str) -> tuple[str, str]:
    d = domain.lstrip(".")
    return d, "." + d


def delete(domain: str, name: str, *, profiles: Iterable[Path | str] = ()) -> int:
    """Remove a cookie from the jar (and from the given profiles, whose Chrome must be closed).

    Clear it from the profiles too, else the next export_from() puts the poisoned value back.
    """
    n = 0
    dbs = [jar_path()] + [cookie_db(p) for p in profiles]
    with _core.flock("jar"):
        for db in dbs:
            if not db.exists():
                continue
            con = sqlite3.connect(db)
            try:
                n += con.execute("delete from cookies where host_key in (?, ?) and name = ?",
                                 (*_hosts(domain), name)).rowcount
                con.commit()
            finally:
                con.close()
    return n


def decrypt(encrypted: bytes, host_key: str | None = None) -> str | None:
    """Chrome `v10` cookie value with the mock-keychain key (AES-128-CBC, IV = 16 spaces).

    Chrome ≥130 (DB meta version 24) prefixes the plaintext with SHA-256(host_key).
    """
    if not encrypted or not encrypted.startswith(b"v10"):
        return None
    for pw in _PASSWORDS:
        key = hashlib.pbkdf2_hmac("sha1", pw, b"saltysalt", 1003, 16)
        plain = _aes_cbc_decrypt(key, encrypted[3:])
        if plain is None:
            continue
        if host_key is not None and plain[:32] == hashlib.sha256(host_key.encode()).digest():
            plain = plain[32:]
        for q in (plain, plain[32:]):  # host hash unknown → printable heuristic
            if q and all(32 <= c < 127 for c in q):
                return q.decode()
    return None


def encrypt(value: str, host_key: str, *, host_hash: bool = True) -> bytes:
    """Inverse of decrypt() (mock-keychain key); used by tests and fixture builders."""
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    key = hashlib.pbkdf2_hmac("sha1", _PASSWORDS[0], b"saltysalt", 1003, 16)
    plain = (hashlib.sha256(host_key.encode()).digest() if host_hash else b"") + value.encode()
    padder = padding.PKCS7(128).padder()
    data = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + enc.update(data) + enc.finalize()


def _aes_cbc_decrypt(key: bytes, data: bytes) -> bytes | None:
    try:
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:  # fall back to the system openssl (no extra package)
        r = subprocess.run(["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", "20" * 16],
                           input=data, capture_output=True)
        return None if r.returncode else r.stdout
    try:
        dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        raw = dec.update(data) + dec.finalize()
        unpad = padding.PKCS7(128).unpadder()
        return unpad.update(raw) + unpad.finalize()
    except ValueError:
        return None


def get(domain: str, name: str) -> str | None:
    """Newest value of a jar cookie (e.g. get("leboncoin.fr", "datadome")), or None. Never log it."""
    jar = jar_path()
    if not jar.exists():
        return None
    con = sqlite3.connect(f"file:{jar}?mode=ro", uri=True)
    try:
        rows = con.execute("select host_key, value, encrypted_value from cookies where host_key in (?, ?) "
                           "and name = ? order by last_update_utc desc", (*_hosts(domain), name)).fetchall()
    finally:
        con.close()
    for host, v, ev in rows:
        if v:
            return v
        d = decrypt(ev, host)
        if d:
            return d
    return None


def profile_cookies(domain: str, profile: Path | str) -> dict[str, str]:
    """{name: value} of a site's cookies in a profile (works while its Chrome runs: reads a copy).

    For HTTP clients acting as a logged-in browser. Values are secrets: never log them.
    """
    d = domain.lstrip(".")
    out: dict[str, str] = {}
    rows = sorted(_read_rows(cookie_db(profile)), key=lambda r: r.get("last_update_utc", 0))
    for r in rows:
        h = r["host_key"]
        if h == d or h.endswith("." + d):
            v = r.get("value") or decrypt(r.get("encrypted_value") or b"", h)
            if v:
                out[r["name"]] = v
    return out


def listing() -> list[dict]:
    """Jar rows without values: host, name, expires (unix s), for `plain-chrome cookies`."""
    return [{"host": r["host_key"], "name": r["name"], "expires": chrome_to_unix(r["expires_utc"])}
            for r in sorted(trust_rows(jar_path()), key=lambda r: (r["host_key"], r["name"]))]


def main(argv: list[str] | None = None) -> int:
    """`python -m carhunt.access.jar [list | has DOMAIN NAME | delete DOMAIN NAME]` — never prints values."""
    a = list(sys.argv[1:] if argv is None else argv) or ["list"]
    if a[0] == "list":
        for r in listing():
            print(f"{r['host']:32} {r['name']:16} until {time.strftime('%Y-%m-%d', time.localtime(r['expires']))}")
    elif a[0] == "has" and len(a) == 3:
        v = get(a[1], a[2])
        print(f"{a[1]} {a[2]}: {'len ' + str(len(v)) if v else 'missing'}")
    elif a[0] == "delete" and len(a) == 3:
        print(f"deleted {delete(a[1], a[2])} row(s)")
    else:
        print(main.__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
