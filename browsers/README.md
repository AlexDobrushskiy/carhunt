# browsers

Shell side of the browser stack (owner: browsers module). Docs: [docs/browsers.md](../docs/browsers.md); agent rules: [skills/carhunt-browsers](../skills/carhunt-browsers/SKILL.md).

| path | what |
|---|---|
| `bin/agent-chrome` | re-signed clone of the installed Chrome (never the owner's Chrome) |
| `bin/serve` | Playwright MCP servers: lanes, identity master, identity copies |
| `bin/pw-identity` | identity leases, pool copies, cookie sync, manual login window |
| `bin/plain-chrome` | normal-launch Chrome, attach after first load; trust-cookie jar |
| `bin/browser-reaper` | kills only browsers carhunt started (pid records) |
| `mcp.json.tmpl` | MCP registration template (`carhunt browser mcp-config`) |
| `launchd/` | job templates (label prefix `browsers.launchd_prefix`, default `carhunt.`) |

Shell tools are thin wrappers over `carhunt.access.<module>`; all state lives in `$CARHUNT_HOME/browsers/`.
