"""Doctor framework: each package may expose `carhunt/<pkg>/doctor.py: checks() -> list[Check]`.

`run_all()` gathers them; a package without checks shows as warn, a crashing one as fail (never a crash).
"""
from __future__ import annotations

import importlib
import pkgutil
import traceback
from dataclasses import asdict, dataclass

STATUSES = ("ok", "warn", "fail")


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str = ""
    fix: str = ""
    module: str = ""

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status!r}")

    def to_dict(self) -> dict:
        return asdict(self)


# modules from docs/design.md: a missing one is reported (warn) so a half-installed setup is visible
EXPECTED = ("core", "access", "sites", "discover", "contact", "vet", "orchestrate")


def packages(root=None) -> list[str]:
    import carhunt

    root = root or carhunt
    return sorted(m.name for m in pkgutil.iter_modules(root.__path__) if m.ispkg)


def run_all(root=None, expected: tuple[str, ...] = EXPECTED) -> list[Check]:
    import carhunt

    root = root or carhunt
    found = packages(root)
    out: list[Check] = []
    for pkg in sorted(set(found) | set(expected)):
        if pkg not in found:
            out.append(Check(f"{pkg}: installed", "warn", "module not built/installed yet", module=pkg))
            continue
        modname = f"{root.__name__}.{pkg}.doctor"
        try:
            mod = importlib.import_module(modname)
        except ModuleNotFoundError as e:
            if e.name == modname:
                if pkg in expected:
                    out.append(Check(f"{pkg}: checks", "warn", "no doctor checks yet", module=pkg))
                continue
            out.append(Check(f"{pkg}: checks", "fail", f"import failed: {e}", module=pkg))
            continue
        except Exception as e:  # noqa: BLE001 - a broken module must not kill doctor
            out.append(Check(f"{pkg}: checks", "fail", f"import failed: {type(e).__name__}: {e}", module=pkg))
            continue
        try:
            for c in mod.checks():
                c.module = c.module or pkg
                out.append(c)
        except Exception as e:  # noqa: BLE001
            last = traceback.extract_tb(e.__traceback__)[-1]
            out.append(Check(f"{pkg}: checks", "fail", f"{type(e).__name__}: {e} ({last.filename}:{last.lineno})",
                             module=pkg))
    return out


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == "fail" for c in checks) else 0


def render(checks: list[Check]) -> str:
    mark = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}
    lines = []
    for c in checks:
        lines.append(f"{mark[c.status]}  {c.name}" + (f": {c.detail}" if c.detail else ""))
        if c.fix and c.status != "ok":
            lines.append(f"      fix: {c.fix}")
    n = {s: sum(c.status == s for c in checks) for s in STATUSES}
    lines.append(f"\n{n['ok']} ok, {n['warn']} warn, {n['fail']} fail")
    return "\n".join(lines)


# --- core's own checks ------------------------------------------------------

def checks() -> list[Check]:
    import os
    import shutil
    import sys

    from carhunt.core import config, paths, secrets

    out: list[Check] = []
    v = sys.version_info
    out.append(Check("python", "ok" if v >= (3, 12) else "fail", f"{v.major}.{v.minor}.{v.micro}",
                     "use Python 3.12+ (scripts/bootstrap makes .venv)"))

    for tool, why, fix in (
        ("agterm", "agent sessions run in agterm", "install agterm: https://github.com/umputun/agterm"),
        ("claude", "the agents are Claude Code sessions", "install Claude Code: https://claude.com/claude-code"),
        ("docker", "cardb + web run in compose", "install Docker Desktop or OrbStack"),
        ("gitleaks", "privacy hook scans for secrets", "brew install gitleaks"),
    ):
        found = shutil.which(tool) or (tool == "agterm" and shutil.which("agtermctl"))
        out.append(Check(f"tool {tool}", "ok" if found else "warn", found or f"missing ({why})", fix))

    h = paths.home()
    if not h.is_dir():
        out.append(Check("home", "fail", f"{h} missing", "scripts/bootstrap (or mkdir -p and copy the config)"))
        return out
    ok = os.access(h, os.W_OK)
    out.append(Check("home", "ok" if ok else "fail", str(h), f"chmod u+w {h}"))

    try:
        cfg = config.load()
        out.append(Check("config", "ok", str(cfg.source)))
    except config.ConfigError as e:
        out.append(Check("config", "fail", str(e), "edit it until `carhunt config validate` passes"))
        cfg = None

    try:
        b = secrets.backend()
        avail, detail = b.available()
        out.append(Check(f"secrets backend {b.name}", "ok" if avail else "fail", detail,
                         "set secrets.backend in config (keychain | op | file)"))
    except secrets.SecretError as e:
        out.append(Check("secrets backend", "fail", str(e), "set secrets.backend: keychain | op | file"))

    if cfg is not None:
        out += _notify_checks(cfg)
        out += _cardb_checks(cfg)

    p = paths.pause_file()
    out.append(Check("pause", "ok", f"PAUSED ({p})" if p.exists() else "not paused"))
    return out


def _notify_checks(cfg) -> list[Check]:
    import json
    from datetime import datetime

    from carhunt.core import clock, paths
    from carhunt.core.config import SecretRef

    kind = cfg.get("notify.backend") or "none"
    out = []
    if kind != "telegram":
        out.append(Check("notify", "ok", f"backend {kind} (Telegram is optional, see docs/notify.md)"))
    else:
        missing = []
        for key in ("bot_token", "chat_id"):
            ref = cfg.get(f"notify.telegram.{key}")
            if ref is None or (isinstance(ref, SecretRef) and not _secret_exists(ref.name)):
                missing.append(str(ref or f"notify.telegram.{key}"))
        out.append(Check("notify telegram", "fail" if missing else "ok",
                         f"missing: {', '.join(missing)}" if missing else "bot token + chat id set",
                         "carhunt secret set telegram_bot_token; carhunt secret set telegram_chat_id"))
    held = paths.home() / "notify" / "held.jsonl"
    if held.exists():
        items = [json.loads(x) for x in held.read_text().splitlines() if x.strip()]
        late = [i for i in items if datetime.fromisoformat(i["until"]) < clock.now()]
        if late:
            out.append(Check("notify held", "warn", f"{len(late)} held message(s) past their window",
                             "carhunt notify poll --once (flushes held messages)"))
    return out


def _secret_exists(name: str) -> bool:
    from carhunt.core import secrets

    try:
        return secrets.exists(name)
    except secrets.SecretError:
        return False


def _cardb_checks(cfg) -> list[Check]:
    from carhunt.core import db

    url = cfg.get("cardb.url") or "http://127.0.0.1:8484"
    try:
        db.Client.from_config(cfg, timeout=3).health()
        return [Check("cardb", "ok", url)]
    except db.ApiError as e:
        return [Check("cardb", "warn", f"{url}: {e}", "docker compose -f deploy/compose.yaml up -d")]
