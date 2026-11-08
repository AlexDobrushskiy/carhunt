# orchestrate

Agent sessions on agterm: launch from role briefs, state + handover, messages, pause, digest, nightly learning, launchd schedule, Claude Code guard hooks. Code: `carhunt/orchestrate/`; briefs: `agents/`; hooks: `hooks/`.

## Setup (once)
| step | command | why |
|---|---|---|
| agterm | install [agterm](https://github.com/umputun/agterm), enable `agtermctl` | the only session backend in v1 (sessions, screens, mailboxes) |
| statusline | `carhunt hooks statusline` (no statusline yet) or add the two `carhunt ctx` lines from `hooks/statusline.sh` to yours | handover is measured, not felt: `carhunt agent ctx` reads `$CARHUNT_HOME/ctx/<session>.json`; scraping `ctx:N%` off the screen fails when the statusline is truncated (seen in the smoke test) |
| hooks | `carhunt hooks install` (shows the diff of the `hooks` section, asks, backs up) | guards in code, not prose (see below) |
| trust | run `claude` once in `$CARHUNT_HOME` and accept the folder-trust dialog | agent sessions start in `$CARHUNT_HOME/agents/<role>/`; an unanswered trust dialog blocks an unattended start |
| permissions | `orchestrate.agent_args.claude`, e.g. `["--allowedTools", "Bash(carhunt:*)", "Bash(cardb:*)"]`, or your own `permissions.allow` | no `--dangerously-*` flag by default; opt in via config if you accept that |
| schedule | `carhunt schedule install` | the day runs on launchd, not on the overseer's loop |
| check | `carhunt doctor` | agterm, agent CLI, statusline, hooks, schedule, state files |

## Commands
| command | what |
|---|---|
| `carhunt agent launch ROLE [--name N] [--force]` | render `agents/templates/common.md` + role brief + local learned rules → `$CARHUNT_HOME/agents/ROLE/brief.md`, init `state.json`, spawn `claude` (or `codex`) with "Read and execute <brief>". Env: `CARHUNT_HOME`, `CARHUNT_AGENT=ROLE`, `CARDB_AUTHOR=ROLE`. Refuses if the role already runs |
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
| `carhunt hooks install\|uninstall\|show\|statusline [--settings P] [--dry-run] [--yes]` | merge guards into `$CLAUDE_CONFIG_DIR/settings.json` (default `~/.claude`) |

## Files in `$CARHUNT_HOME`
`agents/<role>/{brief.md, state.json, log.md, lessons/<D>.md, digest-input.md, digest-sent/, inbox.jsonl}` · `agents/learning/days/<D>.md` · `learned/{common,<role>}.md` (local rules the learning session writes; appended to briefs at launch) · `roles/<role>/brief.md` (your own roles; win over the repo's) · `ctx/<session>.json` · `mailbox/` · `hooks/guards.json` · `logs/schedule/` · `PAUSE`.

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
| identity-pre/post | Pre/PostToolUse `mcp__identity(-[a-z])?__.*` | delegates to `pw-identity hook pre\|post` (browsers module); no-op without it | one logged-in profile, one holder at a time |
| mailbox | SessionStart, UserPromptSubmit, Stop (asyncRewake) | — delivers agterm mailbox mail to an idle carhunt agent (only when `CARHUNT_AGENT` is set) | typing into an input box split long lines and swallowed Returns (11-01) |

Install rules: only entries naming `carhunt_hook.py` are ours; foreign entries are never changed; ours is left out where a foreign hook covers the job (an asyncRewake Stop receiver, an existing `pw-identity hook pre`). Malformed settings → refuse. Only the `hooks` section is ever diffed or printed (settings can hold tokens in `env`). Guards deny (no "ask"): agents run unattended and a prompt stalls them (11-04).

## Config (`orchestrate` section — integrator: merge into config.example.yaml)
```yaml
orchestrate:
  session_backend: agterm
  agent_cli: claude            # claude | codex
  agent_args:                  # extra CLI args per agent CLI; no --dangerously-* unless you add it
    claude: ["--allowedTools", "Bash(carhunt:*)", "Bash(cardb:*)"]
    codex: []
  handover_ctx_pct: 50         # hand over at measured context >= this
  cycle_minutes: 20            # overseer check cycle
  mailbox: carhunt             # carhunt (our receiver hook) | external (your own receiver) | off (always type)
  workspace: ""                # agterm workspace name for new agent sessions ("" = current)
  digest_strong_cars: 8
  schedule: {sweep: "07:00", unpause: "08:10", digest: ["09:30", "20:00"], pause: "23:00", learning: "23:15"}
  schedule_commands: {}        # job -> carhunt argv override, e.g. {sweep: [sweep, --window, morning]}
  hooks:
    secret_globs: ["{home}/secrets/**", "**/.env", "**/*.secret"]
    send_patterns: []          # [{regex: '\bmy-sms-tool send\b', use: "Use carhunt say."}]
```

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
- Folder trust is a manual one-time step; launch doesn't answer the dialog.
- Site chat sends through a browser MCP can't be told apart from other clicks; the send guard covers CLI sends, the outreach brief covers browser sends.
- Digest has no per-agent push count yet (needs a notify ledger from core).
