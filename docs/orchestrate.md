# orchestrate

Agent sessions on agterm: launch from role briefs, state + handover, messages, pause, digest, nightly learning, launchd schedule, Claude Code guard hooks. Code: `carhunt/orchestrate/`; briefs: `agents/`; hooks: `hooks/`.

## Setup (once)
| step | command | why |
|---|---|---|
| agterm | install [agterm](https://github.com/umputun/agterm), enable `agtermctl` | the only session backend in v1 (sessions, screens, mailboxes) |
| statusline | `carhunt hooks statusline` (sets it in the agent settings; agents only) | handover is measured, not felt: `carhunt agent ctx` reads `$CARHUNT_HOME/ctx/<session>.json`; scraping `ctx:N%` off the screen fails when the statusline is truncated (seen in the smoke test) |
| hooks | `carhunt hooks install` → `$CARHUNT_HOME/claude/settings.json` (diff of the `hooks` section, asks, backs up) | guards in code, not prose (see below); launch passes the file to every claude agent with `--settings` and refuses to start one without guards |
| trust | done by `scripts/bootstrap` (marks `$CARHUNT_HOME` trusted in `.claude.json`); without bootstrap, run `claude` once there and accept | agent sessions start in `$CARHUNT_HOME/agents/<role>/`; an unanswered trust dialog blocks an unattended start |
| permissions | `orchestrate.agent_args.claude`, e.g. `["--allowedTools", "Bash(carhunt:*)", "Bash(cardb:*)"]`, or your own `permissions.allow` | no `--dangerously-*` flag by default; opt in via config if you accept that |
| schedule | `carhunt schedule install` | the day runs on launchd, not on the overseer's loop |
| check | `carhunt doctor` | agterm, agent CLI, statusline, hooks, schedule, state files |

## Commands
| command | what |
|---|---|
| `carhunt agent launch ROLE [--var K=V]… [--name N] [--force]` | render `agents/templates/common.md` + role brief + local learned rules → `$CARHUNT_HOME/agents/ROLE/brief.md`, init `state.json` (`active_agent` = new session id), spawn `claude --settings <agent settings>` (or `codex`) with "Read and execute <brief>". Env: `CARHUNT_HOME`, `CARHUNT_AGENT=ROLE`, `CARDB_AUTHOR=ROLE`; agterm sets the session's own `AGTERM_SESSION_ID` (what `carhunt say` checks against `active_agent`). Refuses if the role already runs |
| `carhunt agent side NAME --task-file F` | one-off side session (`agents/templates/side-task.md`, role `side-NAME`) |
| `carhunt agent ls [--json]` · `screen [ROLE\|ID] [--lines N]` · `ctx [ROLE\|ID]` · `close ROLE\|ID` | inspect; no target = own session |
| `carhunt state get [KEY]` · `set KEY VALUE` · `add KEY VALUE` · `done [--summary S]` | agent state (dotted keys, JSON values, locked + schema-checked writes) |
| `carhunt state handover --notes-file F` | old agent: notes (must list `unanswered_inbound`, `[]` if none) → spawns successor with the same brief next to it; old session stays |
| `carhunt state takeover` | successor: becomes `active_agent`, closes the predecessor (this is the confirm) |
| `carhunt state cleanup` · `validate` | close sessions of completed agents (launchd every 30 min) · schema check |
| `carhunt msg --to ROLE\|ID [--interrupt] TEXT` | role → its current `active_agent`; agterm mailbox when a receiver listens, else typed + Return |
| `carhunt pause [--reason R] [--night]` · `unpause [--morning]` | PAUSE file; `--night` also asks agents for lessons; `--morning` tells them what learning changed. Agents can't unpause |
| `carhunt digest [--slot morning\|evening] [--dry-run]` | sessions, strong cars (cardb queue), Needs-you A/B/C + Rec, advice, FYI from `digest-input.md` → `notify kind=digest` |
| `carhunt learn start` · `collect [--date D]` | launch the learning session · list the day's lesson/log/input paths |
| `carhunt schedule install\|uninstall\|show [--no-load]` | launchd plists `carhunt.*` in `~/Library/LaunchAgents` |
| `carhunt hooks install\|uninstall\|show\|statusline [--settings P \| --user] [--dry-run] [--yes]` | merge guards + identity lease hooks into `$CARHUNT_HOME/claude/settings.json`; `--user` = `$CLAUDE_CONFIG_DIR/settings.json` (default `~/.claude`), guards then bind every session |

## Files in `$CARHUNT_HOME`
`claude/settings.json` (agent guards) · `agents/<role>/{brief.md, state.json, log.md, lessons/<D>.md, digest-input.md, digest-sent/, inbox.jsonl}` · `agents/learning/days/<D>.md` · `learned/{common,<role>}.md` (local rules the learning session writes; appended to briefs at launch) · `roles/<role>/brief.md` (your own roles; win over the repo's) · `ctx/<session>.json` · `mailbox/` · `hooks/guards.json` · `logs/schedule/` · `PAUSE`.

## Launch values
- Placeholders `{a.b}` come from the config (lists of mappings render as `k=v k=v; …`), plus `home`, `date`, `agent.*`, `learned.dir`. A missing one fails the launch, never a half-rendered brief.
- Config keys the shipped briefs render (sections in `config.example.yaml`): `owner.{name,tz,languages,home.country}` · `search.{countries,models}` · `sites.enabled` · `discover.windows.{morning,afternoon}` · `contact.{quiet_hours,opener_window}` · `notify.quiet_hours` · `orchestrate.{cycle_minutes,handover_ctx_pct}` · `orchestrate.schedule.{sweep,unpause,digest,pause,learning}`.
- `--var K=V` adds per-launch values: vet/buy need `car`, `vin`, `country`, `destination` (+ vet `tasks`, `options`; buy `stage`); a plain key also gets `K_lc` (lower case).
- Variants: role `BASE-VARIANT` without its own brief runs `agents/roles/BASE/brief.md` with `{variant}` set — `outreach-home` and `outreach-abroad` keep separate state, inbox and caps.

## The agent day (defaults)
| time | job | command |
|---|---|---|
| 07:00 | sweep | `carhunt agent launch sweep` |
| 08:10 | unpause + "re-read what changed" | `carhunt unpause --morning` |
| 09:30 / 20:00 | digest | `carhunt digest --slot morning\|evening` |
| 23:00 | pause + lessons | `carhunt pause --night` |
| 23:15 | learning | `carhunt learn start` |
| every 30 min | close completed sessions | `carhunt state cleanup` |

Overseer: checks every `orchestrate.cycle_minutes`, verifies these jobs ran, never performs agents' work. Briefs: `agents/roles/overseer/brief.md`, `agents/roles/learning/brief.md`.

## Guard hooks (`hooks/carhunt_hook.py`, stdlib only)
| hook | event / matcher | blocks | why |
|---|---|---|---|
| secret-guard | PreToolUse `Bash\|Monitor\|Read\|Edit\|Write\|MultiEdit\|NotebookEdit\|Grep\|Glob` | any read/list of `secret_globs` paths, `$CARHUNT_SECRET_*`, `security find-*-password -w/-g`, `op read`, `carhunt secret exec … -- env/echo/cat/sh -c echo/python -c` | a "masked" dump leaked ~12 passwords into a transcript (EV run 11-06) |
| send-guard | PreToolUse `Bash\|Monitor` | `wacli send/reply/react/delete/edit/forward/revoke`, mailers, raw Telegram Bot API sends, direct `carhunt.contact.channels` calls, `send_patterns` | every send goes through `carhunt say` (pause, quiet hours, caps, dedupe, ledger in one lock); raw Bot API pushes can't be answered (11-04) |
| identity lease (browsers module) | Pre/PostToolUse(+Failure) `mcp__ch-identity(-[a-h])?__.*` | `<repo>/browsers/bin/pw-identity hook pre\|post`, block from `carhunt browser mcp-config --hooks` (absolute path: a `pw-identity` on PATH may be another stack's) | one logged-in profile, one holder at a time |
| mailbox | SessionStart, UserPromptSubmit, Stop (asyncRewake) | — delivers agterm mailbox mail to an idle carhunt agent (only when `CARHUNT_AGENT` is set) | typing into an input box split long lines and swallowed Returns (11-01) |

Install rules: ours = entries naming `carhunt_hook.py` + the lease entries on carhunt's identity matcher; foreign entries are never changed (a personal `mcp__identity…` stack keeps its own hooks); our mailbox receiver is left out where an asyncRewake Stop receiver already runs (target or user settings: both load in an agent). Malformed settings → refuse. Only the `hooks` section is ever diffed or printed (settings can hold tokens in `env`). Guards deny (no "ask"): agents run unattended and a prompt stalls them (11-04).

## Config
Keys and defaults: [`config.example.yaml`](../config.example.yaml) `orchestrate:` (session backend, agent CLI + args, handover %, overseer cycle, mailbox mode, schedule times, hook globs/patterns). Briefs render from this view (`carhunt/orchestrate/settings.py`).

## Rules kept from the EV run (why in brackets)
- One session per role; role → `active_agent` at send time [12 briefs pointed at a closed overseer, 11-02].
- Handover: notes list unanswered inbound explicitly; the old session closes only after the successor's takeover [a reply sat 31 h, 11-06].
- Successor rebuilds from files, not the notes alone; re-arms waits/chains listed in `handover_notes.scheduled` [background sends inherited the old session id and were refused, 11-05].
- Every agterm call names `--target` [rename/type hit the user's selected session, 11-01].
- `--interrupt` (Esc + type) to stop an irreversible step [a signup ran while mail waited, 11-02].
- PAUSE never removed by agents [rejected proposal, 11-05].
- Learning edits only `$CARHUNT_HOME/learned/`; repo, money, scope → A/B/C proposals [briefs grew dated sections that contradicted each other, 11-05].

## Gaps
- Backends: agterm only (macOS). tmux would implement `session.Backend` (6 methods).
- Live-tested: launch → `state done` → `state cleanup`, `msg` typing path. Mailbox receiver hook: unit-tested only (the dev machine runs another receiver).
- Launch doesn't answer a folder-trust dialog: a `$CARHUNT_HOME` moved after bootstrap needs bootstrap re-run.
- Agent-scoped hooks bind launched claude agents only. An owner session that drives `ch-identity` directly takes no lease unless installed with `--user`.
- Site chat sends through a browser MCP can't be told apart from other clicks; the send guard covers CLI sends, the outreach brief covers browser sends.
- Digest has no per-agent push count yet (needs a notify ledger from core).
