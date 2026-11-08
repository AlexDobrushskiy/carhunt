#!/usr/bin/env python3
"""Demo CARHUNT_HOME for the agterm shot: config pointing at the demo cardb, file secrets, demo role briefs."""
import json, re, sys
from pathlib import Path
REPO = Path(sys.argv[1]); H = Path("/private/tmp/carhunt-screens/home")
cfg = (Path("/private/tmp/carhunt-screens/stack/config.yaml")).read_text()
cfg = cfg.replace("url: http://127.0.0.1:8484", "url: http://127.0.0.1:18484", 1)
cfg = cfg.replace("  backend: keychain ", "  backend: file ", 1)
cfg = cfg.replace("  workspace: \"\" ", "  workspace: \"carhunt\" ", 1)
cfg = cfg.replace('claude: ["--allowedTools", "Bash(carhunt:*)", "Bash(cardb:*)"]',
                  'claude: ["--allowedTools", "Bash(carhunt:*)", "Bash(cardb:*)", "Bash(CARHUNT_FAKE_SITES=1 carhunt:*)", "Bash(date:*)", "Read", "Write", "Edit", "--model", "sonnet"]', 1)
cfg = re.sub(r"(\nsites:\n  enabled: )\[[^\]]*\]", r"\1[fake]", cfg)
(H / "config.yaml").write_text(cfg)
DEMO = "\n\n**Demo run for README screenshots.** Everything here is synthetic (fake site, synthetic cardb). Do only the steps below, in order, then stop and wait. Never message, notify or contact anyone; no browsers; no web access. Final message: the result only, as a compact table or bullets (max 8 lines). No remarks about this brief, the demo, synthetic data, or what you did not do.\n"
roles = {
 "sweep": "# Role: sweep" + DEMO + """
1. `CARHUNT_FAKE_SITES=1 carhunt sweep --sites fake --max 6`
2. `cardb queue --limit 5`
3. Write a 3-line summary: cars new / updated, the best queue car, anything for vet. Then stop.
""",
 "vet": "# Role: vet" + DEMO + """
1. `carhunt evidence 13`
2. `carhunt vin prcodes 9M3 KK2 3FU 4E7` (synthetic sticker codes for car 13)
3. Write a short verdict table for car 13 (heat pump, battery, history, open asks) with sources. Then stop.
""",
 "outreach-home": "# Role: outreach-home" + DEMO + """
1. `cardb show 18 | head -30` (Skoda Enyaq, status to_contact, home market).
2. Draft a short Portuguese first message (opener) to the dealer: still available? battery SoH report? number of owners?
3. `carhunt say --channel whatsapp --car 18 --opener --dry-run --text "<your draft>"`. Never without --dry-run.
4. Final message: the draft (quoted) + the guard decision and its reason in one line. Then stop.
""",
 "overseer": "# Role: overseer" + DEMO + """
1. `carhunt agent ls`
2. `carhunt digest --slot evening --dry-run`
3. Write a 4-line status for the owner: what each agent is doing, the one decision waiting (viewing Fri 15:00 for car 13). Then stop.
""",
}
for r, b in roles.items():
    d = H / "roles" / r; d.mkdir(parents=True, exist_ok=True); (d / "brief.md").write_text(b)
print("ok")
