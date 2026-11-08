"""Where run data lives. Everything a run produces is under $CARHUNT_HOME, never in the repo."""
import os
import re
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def safe_name(name: str, what: str = "name") -> str:
    """Reject names that could escape their directory (agent roles, lock names, secret names)."""
    if not _NAME.match(name or "") or ".." in name:
        raise ValueError(f"invalid {what}: {name!r} (letters, digits, _ . - only)")
    return name


def home() -> Path:
    return Path(os.environ.get("CARHUNT_HOME") or "~/.carhunt").expanduser()


def path(*parts: str) -> Path:
    """$CARHUNT_HOME/<parts>, parent directories created."""
    p = home().joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def config_file() -> Path:
    env = os.environ.get("CARHUNT_CONFIG")
    return Path(env).expanduser() if env else home() / "config.yaml"


def agent_dir(role: str) -> Path:
    d = home() / "agents" / safe_name(role, "agent")
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_dir(module: str) -> Path:
    """Per-module run data, e.g. ledger_dir("contact") / "ledger.jsonl"."""
    d = home() / safe_name(module, "module")
    d.mkdir(parents=True, exist_ok=True)
    return d


def locks_dir() -> Path:
    d = home() / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def secrets_dir() -> Path:
    return home() / "secrets"


def pause_file() -> Path:
    return home() / "PAUSE"


def paused() -> bool:
    return pause_file().exists()
