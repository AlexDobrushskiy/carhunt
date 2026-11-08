# agents/roles

One dir per role with a `brief.md` template (placeholders: [templates/README.md](../templates/README.md)). Start one: `carhunt agent launch ROLE [--var k=v]…`. Your own `$CARHUNT_HOME/roles/<role>/brief.md` wins over the repo's.

| role | owner | job | launch |
|---|---|---|---|
| [overseer](overseer/brief.md) | orchestrate | runs the team, owner's single contact, decides operational questions | `carhunt agent launch overseer` |
| [sweep](sweep/brief.md) | discover | daily sweep of the enabled sites into cardb | schedule, 07:00 |
| [outreach](outreach/brief.md) | contact | seller chats; variants `outreach-home`, `outreach-abroad` (own state, inbox, caps) | `carhunt agent launch outreach-home` |
| [vet](vet/brief.md) | vetbuy | one car's evidence pack → visit-ready or drop; asks go to outreach | `--var car=… --var vin=… --var country=… --var destination=…` |
| [buy](buy/brief.md) | vetbuy | one car from contract to registration at home | same vars + `--var stage=…` |
| [learning](learning/brief.md) | orchestrate | nightly: the day's lessons → proposed rule edits | `carhunt learn start` (schedule, 23:15) |
