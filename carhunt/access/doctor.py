"""`carhunt doctor` checks for the access layer. Missing optional providers are warn, never fail."""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import sys

from carhunt.access import _core, chrome, settings

try:
    from carhunt.core.doctor import Check
except ImportError:  # core not installed: same shape
    from dataclasses import dataclass

    @dataclass
    class Check:  # type: ignore[no-redef]
        name: str
        status: str
        detail: str = ""
        fix: str = ""
        module: str = ""


def _c(name: str, status: str, detail: str, fix: str = "") -> Check:
    return Check(f"access: {name}", status, detail, fix, module="access")


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def checks() -> list[Check]:
    s = settings.load()
    out: list[Check] = []

    exe = s.chrome_app / "Contents" / "MacOS" / "Google Chrome"
    out.append(_c("chrome", "ok" if exe.exists() or os.environ.get("CARHUNT_CHROME") else "fail",
                  str(s.chrome_app), "install Google Chrome (https://www.google.com/chrome/)"))
    try:
        p = chrome.agent_chrome_path(update=False)
        out.append(_c("agent-chrome", "ok", str(p)))
    except (subprocess.CalledProcessError, OSError):
        out.append(_c("agent-chrome", "warn", "re-signed Chrome clone not built yet",
                      "browsers/bin/agent-chrome   (builds it; ~1 min)"))

    node = os.environ.get("CARHUNT_NODE") or shutil.which("node")
    mcp_pkg = chrome.REPO / "browsers" / "node_modules" / "@playwright" / "mcp"
    out.append(_c("node", "ok" if node else "fail", node or "node not on PATH", "brew install node@22"))
    out.append(_c("playwright-mcp", "ok" if mcp_pkg.exists() else "fail", str(mcp_pkg),
                  "cd browsers && npm ci"))
    out.append(_c("playwright (python)", "ok" if _has("playwright") else "fail", "session.tab lane/plain/identity",
                  "pip install -e '.[browsers]'"))

    servers = ["lanes", "identity", *s.pool_names()]
    down = [n for n in servers if not _listening(s.mcp_port(n))]
    out.append(_c("mcp servers", "ok" if not down else "warn",
                  f"{len(servers) - len(down)}/{len(servers)} listening" + (f"; down: {', '.join(down)}" if down else ""),
                  "" if not down else "carhunt browser launchd install   (macOS) or browsers/bin/serve <name>"))
    master = s.profile_dir("identity")
    out.append(_c("identity master", "ok" if master.exists() else "warn", str(master),
                  "pw-identity login   (sign in to your sites once), then pw-identity seed --all"))

    leftovers = chrome.read_pid_records()
    out.append(_c("browsers running", "ok", f"{len(leftovers)} recorded by carhunt",
                  "browser-reaper --dry-run" if leftovers else ""))

    proxy = (_core.section("net").get("proxy") or {})
    prov = proxy.get("provider", "none")
    if prov == "none":
        out.append(_c("proxy", "warn", "no residential proxy: country-gated sites (contact/phone APIs) unreachable",
                      "set net.proxy.provider + carhunt secret set proxy_credentials; carhunt proxy test ES"))
    else:
        out.append(_c("proxy", "ok", f"provider {prov} (run `carhunt proxy test <CC>` to verify the exit)"))

    sms = (_core.section("accounts").get("sms") or {}).get("provider", "none")
    out.append(_c("sms", "ok" if sms != "none" else "warn", f"provider {sms}",
                  "" if sms != "none" else "optional: only for verify-once sites (see docs/browsers.md)"))
    out.append(_c("camoufox", "ok" if _has("camoufox") else "warn",
                  "anti-detect Firefox for Imperva-walled sends" if _has("camoufox") else "not installed (optional)",
                  "" if _has("camoufox") else "pip install camoufox && python -m camoufox fetch"))
    if sys.platform != "darwin":
        out.append(_c("platform", "warn", f"{sys.platform}: agent-chrome/launchd/open -g are macOS-only",
                      "set CARHUNT_CHROME to a Chrome binary; run serve under your own supervisor"))

    from carhunt.access.captcha import doctor as captcha_doctor
    for d in captcha_doctor.checks():
        out.append(Check(f"access: {d['name']}", d["status"], d.get("detail", ""), d.get("fix", ""), module="access"))
    return out
