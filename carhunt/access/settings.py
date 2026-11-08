"""Browser-stack settings: config `browsers` section + defaults, and the $CARHUNT_HOME/browsers layout.

Ports and the launchd label prefix differ from any pre-existing personal browser stack
(default 8931/9331, com.<user>.*) so both can run side by side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from carhunt.access import _core

POOL_LETTERS = "abcdefgh"


@dataclass(frozen=True)
class Settings:
    chrome_app: Path = Path("/Applications/Google Chrome.app")
    lanes: int = 4                 # named lane registrations (ch-lane-a…), all on one --isolated server
    identity_pool: int = 4         # identity copies identity-a… (one MCP server + profile each)
    mcp_base_port: int = 18931     # lanes = base, identity master = base+1, copy i = base+2+i
    debug_base_port: int = 19331   # same offsets, Chrome --remote-debugging-port
    plain_debug_port: int = 19341  # plain-chrome's shared browser
    launchd_prefix: str = "carhunt."
    mcp_name_prefix: str = "ch-"   # MCP registrations ch-lane-a…, ch-identity…: never clash with the user's own
    idle_release_s: int = 180      # identity lease auto-release after this much idle
    reaper_max_age_h: float = 6.0
    headless: bool = True          # MCP servers; plain-chrome is always headed (off-screen)
    captcha: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return _core.home() / "browsers"

    def dir(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # layout under $CARHUNT_HOME/browsers/
    @property
    def agent_chrome_dir(self) -> Path:   # re-signed Chrome clone
        return self.dir("agent-chrome")

    @property
    def profiles(self) -> Path:           # identity (master), identity-<x>, plain, geo-<cc>
        return self.dir("profiles")

    @property
    def run_dir(self) -> Path:            # pid records of browsers WE started (reaper reads these)
        return self.dir("run")

    @property
    def leases_dir(self) -> Path:
        return self.dir("leases")

    @property
    def jar_path(self) -> Path:           # trust-cookie jar (datadome/_abck/cf_clearance/…)
        return self.dir("jar") / "jar.sqlite"

    @property
    def mcp_out(self) -> Path:
        return self.dir("mcp-out")

    @property
    def logs(self) -> Path:
        return self.dir("logs")

    def pool_names(self) -> list[str]:
        return [f"identity-{c}" for c in POOL_LETTERS[: self.identity_pool]]

    def lane_names(self) -> list[str]:
        return [f"{self.mcp_name_prefix}lane-{c}" for c in POOL_LETTERS[: self.lanes]]

    def mcp_port(self, server: str) -> int:
        return self.mcp_base_port + self._offset(server)

    def debug_port(self, server: str) -> int:
        return self.debug_base_port + self._offset(server)

    def profile_dir(self, server: str) -> Path:
        return self.profiles / server

    def label(self, job: str) -> str:
        return f"{self.launchd_prefix}{job}"

    def _offset(self, server: str) -> int:
        if server == "lanes":
            return 0
        if server == "identity":
            return 1
        if server.startswith("identity-"):
            i = POOL_LETTERS.index(server.removeprefix("identity-"))
            if i >= self.identity_pool:
                raise ValueError(f"{server}: pool has {self.identity_pool} copies")
            return 2 + i
        raise ValueError(f"unknown MCP server {server!r}")


def load() -> Settings:
    b = _core.section("browsers")
    ports = b.get("ports") or {}
    kw = {}
    if "chrome_app" in b:
        kw["chrome_app"] = Path(b["chrome_app"]).expanduser()
    for key in ("lanes", "identity_pool", "launchd_prefix", "mcp_name_prefix", "idle_release_s", "reaper_max_age_h", "headless", "captcha"):
        if key in b:
            kw[key] = b[key]
    if "mcp_base" in ports:
        kw["mcp_base_port"] = int(ports["mcp_base"])
    if "debug_base" in ports:
        kw["debug_base_port"] = int(ports["debug_base"])
    if "plain_debug" in ports:
        kw["plain_debug_port"] = int(ports["plain_debug"])
    return Settings(**kw)
