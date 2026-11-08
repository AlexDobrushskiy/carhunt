# skills

Claude Code skills shipped as `carhunt-*`. `scripts/bootstrap` symlinks each into `~/.claude/skills/` (`$CLAUDE_CONFIG_DIR`); an existing non-link of the same name is left alone. Why the prefix: never clash with the user's own skills.

| skill | use it before |
|---|---|
| [carhunt-browsers](carhunt-browsers/SKILL.md) | any site access: route choice, escalation ladder, per-site table (`references/site-table.md`, rendered by `carhunt browser site-table`), pacing, proxy/SMS/account policy |
| [carhunt-outreach](carhunt-outreach/SKILL.md) | any message to a seller: guards, tone, scam patterns, negotiation lines; phrases per language in `phrases.md` |
| [carhunt-vet](carhunt-vet/SKILL.md) | vetting or buying one car: VIN/history checks, evidence pack, contract, deposit, pickup, import |
