# Docs index

Every doc in the repo, one line each. Start with the [README](../README.md), then [design.md](design.md).

## Overview
- [README](../README.md) — what carhunt is, requirements, quick start, module map
- [design.md](design.md) — principles, CLI groups, who calls whom, site.yaml keys, decisions
- [privacy.md](privacy.md) — what lives where, fixture rules, the privacy check
- [testing.md](testing.md) — test layout, isolation, how to run each suite and the e2e run

## Module docs
- [core.md](core.md) — config, clock, locks, paths, cardb client, CLI plugin contract, doctor, bootstrap
- [secrets.md](secrets.md) — secrets backends (Keychain / 1Password / file), `carhunt secret`
- [notify.md](notify.md) — owner pushes (Telegram, optional), digest/ask/urgent policy, reply routing to agent inboxes
- [db.md](db.md) — cardb: data model, ranking, `cardb init`, compose, remote access, backups
- [web.md](web.md) — phone UI over cardb: routes, users and tokens, tests
- [browsers.md](browsers.md) — agent Chrome, lanes, identity pool, plain-chrome, captcha, proxies, pace ledger, accounts
- [browsers/site-walls.md](browsers/site-walls.md) — measured bot walls per site, Oct–Nov 2026 (history; live data in site.yaml)
- [sites.md](sites.md) — site plugins, `carhunt site`, liveness, adding a site
- [discover.md](discover.md) — `carhunt sweep`: windows, cursors, scope, normalize, ingest
- [contact.md](contact.md) — `carhunt say` guards, channels, ledger, watcher, mail routing, asks
- [vetbuy.md](vetbuy.md) — VIN / RDW / PR-code tools, evidence pack, visit-ready gate
- [orchestrate.md](orchestrate.md) — agent launch, state + handover, pause, digest, learning, schedule, guard hooks

## Code-level READMEs
- [cardb/README.md](../cardb/README.md) — build, run, client settings, agent conventions for the `cardb` CLI
- [cardb/DESIGN.md](../cardb/DESIGN.md) — cardb storage, dedupe, merge/split, ranking, write rules
- [deploy/README.md](../deploy/README.md) — compose: start, stop, what the file guarantees
- [web/README.md](../web/README.md) — pointer to web.md + deploy
- [browsers/README.md](../browsers/README.md) — shell tools (`agent-chrome`, `serve`, `pw-identity`, `plain-chrome`, `browser-reaper`)
- [hooks/README.md](../hooks/README.md) — guard hooks + statusline files
- [carhunt/core/README.md](../carhunt/core/README.md) · [access](../carhunt/access/README.md) · [sites](../carhunt/sites/README.md) · [discover](../carhunt/discover/README.md) · [contact](../carhunt/contact/README.md) · [vet](../carhunt/vet/README.md) · [orchestrate](../carhunt/orchestrate/README.md) — file maps per package
- `carhunt/sites/<pkg>/README.md` — per-site notes: [autoscout24](../carhunt/sites/autoscout24/README.md), [carsbat.com](../carhunt/sites/carsbat_com/README.md), [coches.net](../carhunt/sites/coches_net/README.md), [custojusto.pt](../carhunt/sites/custojusto_pt/README.md), [kleinanzeigen.de](../carhunt/sites/kleinanzeigen_de/README.md), [lacentrale.fr](../carhunt/sites/lacentrale_fr/README.md), [leboncoin.fr](../carhunt/sites/leboncoin_fr/README.md), [leparking.fr](../carhunt/sites/leparking_fr/README.md), [marktplaats.nl](../carhunt/sites/marktplaats_nl/README.md), [milanuncios.com](../carhunt/sites/milanuncios_com/README.md), [mobile.de](../carhunt/sites/mobile_de/README.md), [olx.pt](../carhunt/sites/olx_pt/README.md), [standvirtual.com](../carhunt/sites/standvirtual_com/README.md), [subito.it](../carhunt/sites/subito_it/README.md), [wallapop.com](../carhunt/sites/wallapop_com/README.md)
- [tests/e2e/README.md](../tests/e2e/README.md) — cross-module end-to-end tests on a clean HOME

## Skills (agent rules)
- [skills/README.md](../skills/README.md) — what ships, how bootstrap links it
- [carhunt-browsers](../skills/carhunt-browsers/SKILL.md) — route choice, escalation ladder, pacing, account/proxy/SMS policy
  - [references/site-table.md](../skills/carhunt-browsers/references/site-table.md) (generated from site.yaml) · [logins-and-accounts.md](../skills/carhunt-browsers/references/logins-and-accounts.md) · [plain-chrome.md](../skills/carhunt-browsers/references/plain-chrome.md) · [proxies-and-sms.md](../skills/carhunt-browsers/references/proxies-and-sms.md)
- [carhunt-outreach](../skills/carhunt-outreach/SKILL.md) — seller messaging rules, scam patterns, negotiation · [phrases.md](../skills/carhunt-outreach/phrases.md) per language
- [carhunt-vet](../skills/carhunt-vet/SKILL.md) — vetting and buying one car

## Agents
- [agents/README.md](../agents/README.md) — roles, templates, state schema
- [roles/README.md](../agents/roles/README.md) — role table: [overseer](../agents/roles/overseer/brief.md), [sweep](../agents/roles/sweep/brief.md), [outreach](../agents/roles/outreach/brief.md) (home/abroad), [vet](../agents/roles/vet/brief.md), [buy](../agents/roles/buy/brief.md), [learning](../agents/roles/learning/brief.md)
- [templates/README.md](../agents/templates/README.md) — placeholders; [common.md](../agents/templates/common.md) (rules every agent gets), [side-task.md](../agents/templates/side-task.md), [lessons.md](../agents/templates/lessons.md), `digest.txt`

## Knowledge (vet / buy / import playbooks)
- [knowledge/README.md](../knowledge/README.md) — map + order of use
- Vet: [vin-sources](../knowledge/vin-sources.md) · [battery-soh](../knowledge/battery-soh.md) · [pr-codes-vag](../knowledge/pr-codes-vag.md) · [coverage-rules](../knowledge/coverage-rules.md) · [residual-risk](../knowledge/residual-risk.md)
- Buy: [doc-verify](../knowledge/buy/doc-verify.md) · [contract-checklist](../knowledge/buy/contract-checklist.md) · [deposit-payment](../knowledge/buy/deposit-payment.md) · [pickup-day](../knowledge/buy/pickup-day.md) · [shutdown](../knowledge/buy/shutdown.md)
- Import: [import/README](../knowledge/import/README.md) (how it works, adding a destination) · [pt-registration](../knowledge/import/pt-registration.md) · [de-to-pt](../knowledge/import/de-to-pt.md) · [fr-to-pt](../knowledge/import/fr-to-pt.md) · [es-to-pt](../knowledge/import/es-to-pt.md) · [be-to-pt](../knowledge/import/be-to-pt.md) · [other-to-pt](../knowledge/import/other-to-pt.md)
