"""Trust-cookie jar on synthetic Chrome-shaped Cookies DBs (no real profile, fake values)."""
import sqlite3
from pathlib import Path

import pytest

from carhunt.access import jar

SCHEMA = """
CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR);
CREATE TABLE cookies(creation_utc INTEGER NOT NULL, host_key TEXT NOT NULL, top_frame_site_key TEXT NOT NULL,
  name TEXT NOT NULL, value TEXT NOT NULL, encrypted_value BLOB NOT NULL, path TEXT NOT NULL,
  expires_utc INTEGER NOT NULL, is_secure INTEGER NOT NULL, is_httponly INTEGER NOT NULL,
  last_access_utc INTEGER NOT NULL, has_expires INTEGER NOT NULL, is_persistent INTEGER NOT NULL,
  priority INTEGER NOT NULL, samesite INTEGER NOT NULL, source_scheme INTEGER NOT NULL,
  source_port INTEGER NOT NULL, last_update_utc INTEGER NOT NULL, source_type INTEGER NOT NULL,
  has_cross_site_ancestor INTEGER NOT NULL);
CREATE UNIQUE INDEX cookies_unique_index ON cookies(host_key, top_frame_site_key, has_cross_site_ancestor, name,
  path, source_scheme, source_port);
INSERT INTO meta VALUES ('version', '24'), ('last_compatible_version', '24');
"""
HOUR = 3600 * 1_000_000


def make_profile(root: Path, cookies: list[tuple], network_dir: bool = False) -> Path:
    """cookies: (host, name, value, expires_delta_us, last_update_delta_us)."""
    db = root / "Default" / ("Network/Cookies" if network_dir else "Cookies")
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    now = jar.chrome_now()
    for host, name, value, exp, upd in cookies:
        con.execute("insert into cookies values (?,?,'',?,'',?,'/',?,1,1,?,1,1,1,0,2,443,?,0,0)",
                    (now, host, name, jar.encrypt(value, host), now + exp, now, now + upd))
    con.commit()
    con.close()
    return root


def names(db: Path) -> set[tuple[str, str]]:
    con = sqlite3.connect(db)
    try:
        return set(con.execute("select host_key, name from cookies"))
    finally:
        con.close()


@pytest.fixture
def src(tmp_path, carhunt_home):
    return make_profile(tmp_path / "src", [
        (".example.invalid", "datadome", "SYN-dd-1", HOUR, 0),
        (".example.invalid", "session_login", "SYN-login", HOUR, 0),   # login cookie: must never move
        ("shop.example.invalid", "_abck", "SYN-abck", HOUR, 0),
        (".example.invalid", "cf_clearance", "SYN-cf-old", -HOUR, 0),  # expired: must not move
        (".other.invalid", "_px3", "SYN-px", HOUR, 0),
    ])


def test_encrypt_decrypt_roundtrip():
    ev = jar.encrypt("SYN-value", ".example.invalid")
    assert ev.startswith(b"v10")
    assert jar.decrypt(ev, ".example.invalid") == "SYN-value"
    assert jar.decrypt(jar.encrypt("SYN-nohash", "x", host_hash=False)) == "SYN-nohash"
    assert jar.decrypt(b"v11garbage") is None


def test_export_moves_only_unexpired_trust_cookies(src):
    assert jar.export_from(src) == 3
    assert names(jar.jar_path()) == {(".example.invalid", "datadome"), ("shop.example.invalid", "_abck"),
                                     (".other.invalid", "_px3")}
    assert jar.get("example.invalid", "datadome") == "SYN-dd-1"
    assert jar.get(".example.invalid", "datadome") == "SYN-dd-1"
    assert jar.get("shop.example.invalid", "_abck") == "SYN-abck"
    assert jar.get("example.invalid", "session_login") is None
    assert [r["name"] for r in jar.listing()] == ["datadome", "_px3", "_abck"]


def test_import_into_new_and_existing_profile(src, tmp_path):
    jar.export_from(src)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert jar.import_into(empty) == 3
    assert jar.cookie_db(empty) == empty / "Default/Cookies"
    other = make_profile(tmp_path / "other", [(".example.invalid", "datadome", "SYN-dd-stale", HOUR, -HOUR),
                                              (".example.invalid", "prefs", "SYN-prefs", HOUR, 0)],
                         network_dir=True)  # Windows layout
    assert jar.import_into(other) == 3
    assert jar.cookie_db(other) == other / "Default/Network/Cookies"
    assert jar.profile_cookies("example.invalid", other) == {"datadome": "SYN-dd-1", "prefs": "SYN-prefs",
                                                                 "_abck": "SYN-abck"}  # subdomains included


def test_newer_cookie_wins(src, tmp_path):
    jar.export_from(src)
    newer = make_profile(tmp_path / "newer", [(".example.invalid", "datadome", "SYN-dd-2", HOUR, HOUR)])
    older = make_profile(tmp_path / "older", [(".example.invalid", "datadome", "SYN-dd-0", HOUR, -HOUR)])
    assert jar.export_from(newer) == 1
    assert jar.export_from(older) == 0
    assert jar.get("example.invalid", "datadome") == "SYN-dd-2"


def test_delete_poisoned_cookie_from_jar_and_profile(src, tmp_path):
    jar.export_from(src)
    plain = tmp_path / "plain"
    plain.mkdir()
    jar.import_into(plain)
    assert jar.delete("example.invalid", "datadome", profiles=[plain]) == 2
    assert jar.get("example.invalid", "datadome") is None
    assert (".example.invalid", "datadome") not in names(jar.cookie_db(plain))
    jar.export_from(plain)  # the poisoned value does not come back from the profile
    assert jar.get("example.invalid", "datadome") is None
    assert jar.get("shop.example.invalid", "_abck") == "SYN-abck"


def test_empty_jar(carhunt_home, tmp_path):
    assert jar.get("example.invalid", "datadome") is None
    assert jar.import_into(tmp_path) == 0
    assert jar.export_from(tmp_path / "missing") == 0
    assert jar.listing() == []
