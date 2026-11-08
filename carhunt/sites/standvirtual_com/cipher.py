"""Standvirtual's own client-side field cipher (phones, VIN), as pure functions.

Token = "b64(ciphertext+tag).<ver>.b64(iv)", AES-GCM-256. Key = PBKDF2-SHA256(password, salt, 10 iterations;
10000 for ver "0"), password = hex(sha256(key_source)[:16]). key_source = seller uuid (dealer stands: standId) for
`advert.phoneNumbers`, advert id for `parametersDict.vin`. The salt is a string literal in the site's own webpack
bundle next to the PBKDF2 call: `salt_candidates()` lists literals there, a token decrypting under one proves it
(GCM authenticates), so a wrong guess can never yield a wrong phone.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
import urllib.parse
from collections.abc import Iterable

_TOKEN = re.compile(r"^([A-Za-z0-9+/=_-]+)\.(\d+)\.([A-Za-z0-9+/=_-]+)$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_LITERAL = re.compile(r"""(["'`])((?:\\.|(?!\1)[^\\\n])*)\1""")   # string literals, scanned in order
_SCRIPT = re.compile(r"""<(?:script[^>]+src|link[^>]+href)=["']([^"']+\.js(?:\?[^"']*)?)["']""", re.I)
_RUNTIME = re.compile(r"/(webpack|framework|polyfills)[-.]")
_API_WORDS = {"PBKDF2", "AES-GCM", "SHA-256", "deriveKey", "deriveBits", "importKey", "decrypt"}
WINDOW = 1500   # chars around "PBKDF2" searched for the salt literal


class CipherError(Exception):
    """Token malformed or did not authenticate under this key/salt."""


def is_token(s: object) -> bool:
    return isinstance(s, str) and bool(_TOKEN.match(s))


def password(key_source: str) -> bytes:
    return hashlib.sha256(key_source.encode()).digest()[:16].hex().encode()


def iterations(ver: str) -> int:
    return 10000 if ver == "0" else 10


def _b64(s: str) -> bytes:
    return base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_" if ("-" in s or "_" in s) else None)


def decrypt(token: str, key_source: str, salt: str) -> str:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    m = _TOKEN.match(token or "")
    if not m:
        raise CipherError("not a token")
    data, ver, iv = m.groups()
    key = PBKDF2HMAC(hashes.SHA256(), 32, salt.encode(), iterations(ver)).derive(password(key_source))
    try:
        return AESGCM(key).decrypt(_b64(iv), _b64(data), None).decode()
    except (InvalidTag, ValueError, binascii.Error) as e:
        raise CipherError(type(e).__name__) from e


def decode(token: str, key_sources: Iterable[str | None], salt: str) -> str | None:
    """Plaintext under the first key source that authenticates, else None."""
    for k in key_sources:
        if not k:
            continue
        try:
            return decrypt(token, str(k), salt)
        except CipherError:
            continue
    return None


def salt_candidates(js: str) -> list[str]:
    """String literals near each "PBKDF2" in a bundle, nearest first, UUID-shaped before the rest."""
    anchors = [m.start() for m in re.finditer("PBKDF2", js)]
    found: dict[str, tuple[int, int]] = {}
    if not anchors:
        return []
    for lit in _LITERAL.finditer(js):
        s = lit.group(2)
        dist = min(abs(lit.start() - a) for a in anchors)
        if dist > WINDOW or not 8 <= len(s) <= 64 or re.search(r"\s", s) or s in _API_WORDS:
            continue
        rank = (0 if _UUID.match(s) else 1, dist)
        found[s] = min(found.get(s, rank), rank)
    return sorted(found, key=found.__getitem__)


def script_urls(html: str, origin: str) -> list[str]:
    """The page's own JS bundles (script src + preload links), app chunks before the webpack/framework runtime."""
    out: list[str] = []
    for src in _SCRIPT.findall(html):
        u = urllib.parse.urljoin(origin + "/", src)
        if u not in out and urllib.parse.urlparse(u).scheme == "https":
            out.append(u)
    return sorted(out, key=lambda u: bool(_RUNTIME.search(u)))
