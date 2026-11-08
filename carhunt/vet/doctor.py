"""Doctor checks for vet: bundled tables load, knowledge for the configured destination exists."""
from __future__ import annotations

from pathlib import Path

from carhunt.core.doctor import Check

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"


def checks() -> list[Check]:
    from carhunt.vet import prcodes, vin

    out = []
    try:
        out.append(Check("vet: WMI table", "ok", f"{len(vin.wmi_table())} WMIs", module="vet"))
        out.append(Check("vet: PR codes (vag)", "ok", f"{len(prcodes.table('vag'))} codes", module="vet"))
    except Exception as e:
        out.append(Check("vet: data tables", "fail", str(e), "reinstall: pip install -e '.[vet]'", module="vet"))
    try:
        import markdown  # noqa: F401
        out.append(Check("vet: markdown", "ok", "md2html available", module="vet"))
    except ImportError:
        out.append(Check("vet: markdown", "warn", "md2html needs `markdown`", "pip install -e '.[vet]'", module="vet"))
    dest = None
    try:
        from carhunt.core import config
        dest = (config.load().get("vet.destination_country") or "").lower() or None
    except Exception:
        pass
    if dest:
        guide = KNOWLEDGE / "import" / f"{dest}-registration.md"
        out.append(Check("vet: import guide", "ok" if guide.exists() else "warn",
                         str(guide.name) if guide.exists() else f"no knowledge/import/{dest}-registration.md",
                         "" if guide.exists() else "write one: see knowledge/import/README.md", module="vet"))
    return out
