"""CLI groups of the access package: `carhunt browser|pace|proxy|sms|captcha …` (auto-discovered by carhunt.cli)."""
from __future__ import annotations

import importlib

# modules adding subcommands under `carhunt browser`
BROWSER_PARTS = ("mcp", "identity", "plainchrome", "reaper", "sitetable", "geo")
# modules adding their own top-level group
GROUPS = (("pace", "register_cli"), ("proxy", "register_cli"), ("accounts.sms", "register_cli"),
          ("captcha.cli", "register"))


def register(subparsers) -> None:
    p = subparsers.add_parser("browser", help="agent browsers: MCP config, launchd, identity pool, plain-chrome, reaper")
    p.set_defaults(_parser=p)
    sub = p.add_subparsers(dest="browser_cmd", metavar="<cmd>")
    for name in BROWSER_PARTS:
        mod = importlib.import_module(f"carhunt.access.{name}")
        if hasattr(mod, "register_cli"):
            mod.register_cli(sub)
    for name, fn in GROUPS:
        getattr(importlib.import_module(f"carhunt.access.{name}"), fn)(subparsers)
