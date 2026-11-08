"""Secrets by name. Lookup: env CARHUNT_SECRET_<NAME> -> configured backend (keychain | op | file).

Nothing here prints a value: callers get it as a return value and pass it on (an HTTP header, a child env).
Why: in the EV run a masked `grep` on a creds folder put ~12 passwords into a transcript (2026-11-06).
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

from carhunt.core import paths

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
BACKENDS = ("keychain", "op", "file")


class SecretError(Exception):
    pass


class SecretNotFound(SecretError, KeyError):
    def __str__(self) -> str:  # KeyError would repr-quote the message
        return self.args[0] if self.args else "secret not found"


def check_name(name: str) -> str:
    if not _NAME.match(name or "") or ".." in name:
        raise SecretError(f"invalid secret name {name!r} (letters, digits, _ . - ; max 64)")
    return name


def env_var(name: str) -> str:
    return "CARHUNT_SECRET_" + re.sub(r"[^A-Z0-9]", "_", name.upper())


class Backend(Protocol):
    name: str

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> bool: ...
    def names(self) -> list[str]: ...
    def available(self) -> tuple[bool, str]: ...


class FileBackend:
    """$CARHUNT_HOME/secrets/NAME, dir 0700, files 0600."""

    name = "file"

    def __init__(self, root: Path | None = None):
        self.root = root or paths.secrets_dir()

    def _dir(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        return self.root

    def get(self, name: str) -> str | None:
        f = self.root / name
        return f.read_text().removesuffix("\n") if f.is_file() else None

    def set(self, name: str, value: str) -> None:
        d = self._dir()
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")  # mkstemp creates 0600
        with os.fdopen(fd, "w") as fh:
            fh.write(value)
        os.replace(tmp, d / name)

    def delete(self, name: str) -> bool:
        f = self.root / name
        if f.is_file():
            f.unlink()
            return True
        return False

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_file() and not p.name.startswith("."))

    def available(self) -> tuple[bool, str]:
        if self.root.exists() and (self.root.stat().st_mode & 0o077):
            return False, f"{self.root} is readable by others (chmod 700)"
        return True, str(self.root)


class KeychainBackend:
    """macOS login keychain, generic passwords: service = `carhunt` (configurable), account = NAME.

    Values go in through `security -i` on stdin as hex, so they never appear in a process list.
    Printable ASCII is stored raw (other tools, e.g. cardb, can read it); anything else as `b64:<base64>`.
    """

    name = "keychain"

    def __init__(self, service: str = "carhunt"):
        self.service = service

    def _run(self, args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["security", *args], input=stdin, capture_output=True, text=True)

    def get(self, name: str) -> str | None:
        r = self._run(["find-generic-password", "-s", self.service, "-a", name, "-w"])
        if r.returncode == 44:
            return None
        if r.returncode:
            raise SecretError(f"keychain read of {name} failed (exit {r.returncode})")
        v = r.stdout.removesuffix("\n")
        return base64.b64decode(v[4:]).decode() if v.startswith("b64:") else v

    def set(self, name: str, value: str) -> None:
        raw = value if value.isascii() and value.isprintable() else "b64:" + base64.b64encode(value.encode()).decode()
        cmd = f"add-generic-password -U -s {self.service} -a {name} -l carhunt -X {raw.encode().hex()}\n"
        r = self._run(["-i"], stdin=cmd)
        if r.returncode or "error" in (r.stderr or "").lower():
            raise SecretError(f"keychain write of {name} failed (exit {r.returncode})")

    def delete(self, name: str) -> bool:
        return self._run(["delete-generic-password", "-s", self.service, "-a", name]).returncode == 0

    def names(self) -> list[str]:
        r = self._run(["dump-keychain"])  # attributes only; no -d, so no secret data
        out: list[str] = []
        for block in r.stdout.split("keychain: "):
            if f'"svce"<blob>="{self.service}"' in block and (m := re.search(r'"acct"<blob>="([^"]*)"', block)):
                out.append(m.group(1))
        return sorted(dict.fromkeys(out))

    def available(self) -> tuple[bool, str]:
        if sys.platform != "darwin" or not shutil.which("security"):
            return False, "macOS `security` not found (use secrets.backend: file or op)"
        return True, f"login keychain, service {self.service}"


class OpBackend:
    """1Password CLI: item title = NAME in vault `carhunt` (configurable), field `password`."""

    name = "op"

    def __init__(self, vault: str = "carhunt"):
        self.vault = vault

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(["op", *args], capture_output=True, text=True)

    def get(self, name: str) -> str | None:
        r = self._run(["read", f"op://{self.vault}/{name}/password"])
        if r.returncode:
            if "isn't an item" in r.stderr or "not found" in r.stderr.lower():
                return None
            raise SecretError(f"op read of {name} failed (exit {r.returncode})")
        return r.stdout.removesuffix("\n")

    def set(self, name: str, value: str) -> None:
        self.delete(name)
        tpl = {"title": name, "category": "PASSWORD",
               "fields": [{"id": "password", "type": "CONCEALED", "purpose": "PASSWORD", "value": value}]}
        fd, tmp = tempfile.mkstemp(suffix=".json")  # 0600, removed right after
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(tpl, fh)
            r = self._run(["item", "create", "--vault", self.vault, "--template", tmp])
        finally:
            os.unlink(tmp)
        if r.returncode:
            raise SecretError(f"op write of {name} failed (exit {r.returncode})")

    def delete(self, name: str) -> bool:
        return self._run(["item", "delete", name, "--vault", self.vault]).returncode == 0

    def names(self) -> list[str]:
        r = self._run(["item", "list", "--vault", self.vault, "--format", "json"])
        return sorted(i["title"] for i in json.loads(r.stdout or "[]")) if r.returncode == 0 else []

    def available(self) -> tuple[bool, str]:
        if not shutil.which("op"):
            return False, "1Password CLI `op` not found (brew install 1password-cli)"
        return True, f"1Password vault {self.vault}"


def backend(kind: str | None = None) -> Backend:
    """Env CARHUNT_SECRETS_BACKEND > config secrets.backend > keychain on macOS, file elsewhere."""
    from carhunt.core import config

    cfg = None
    try:
        cfg = config.load_or_none()
    except config.ConfigError:
        cfg = None  # a broken config must not lock the user out of their secrets
    kind = kind or os.environ.get("CARHUNT_SECRETS_BACKEND") or (cfg.get("secrets.backend") if cfg else None) \
        or ("keychain" if sys.platform == "darwin" else "file")
    if kind == "keychain":
        return KeychainBackend((cfg.get("secrets.keychain_service") if cfg else None) or "carhunt")
    if kind == "op":
        return OpBackend((cfg.get("secrets.op_vault") if cfg else None) or "carhunt")
    if kind == "file":
        return FileBackend()
    raise SecretError(f"unknown secrets backend {kind!r} (one of {', '.join(BACKENDS)})")


def source(name: str) -> str | None:
    """Where NAME would be read from (`env` or the backend name), or None if it is missing."""
    check_name(name)
    if os.environ.get(env_var(name)):
        return "env"
    b = backend()
    return b.name if b.get(name) is not None else None


def get(name: str) -> str:
    check_name(name)
    if v := os.environ.get(env_var(name)):
        return v
    b = backend()
    v = b.get(name)
    if v is None:
        raise SecretNotFound(f"secret {name} not set (carhunt secret set {name}; backend {b.name})")
    return v


def exists(name: str) -> bool:
    return source(name) is not None


def set(name: str, value: str) -> str:  # noqa: A001 - design API name
    """Store in the configured backend; returns the backend name."""
    check_name(name)
    if not value:
        raise SecretError("empty value")
    b = backend()
    b.set(name, value)
    return b.name


def delete(name: str) -> bool:
    check_name(name)
    return backend().delete(name)


def names() -> list[tuple[str, str]]:
    """(name, source) pairs: backend items plus CARHUNT_SECRET_* env overrides. Names only."""
    b = backend()
    out = {n: b.name for n in b.names()}
    for k in os.environ:
        if k.startswith("CARHUNT_SECRET_") and os.environ[k]:
            out[k.removeprefix("CARHUNT_SECRET_").lower()] = "env"
    return sorted(out.items())
