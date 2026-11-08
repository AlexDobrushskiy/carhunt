# Regenerating the screenshots

Everything runs on synthetic data on loopback; nothing touches `~/.carhunt`, a real cardb or a real site.

| step | command |
|---|---|
| photos | download the Commons files in [`photos.json`](photos.json) (1200 px thumbnails) to `$SCREENS_DIR/photos/` + a `credits.json` (same list); keep plates/dealer text unreadable |
| cardb | `cd cardb && go build -tags nodynamic -o $SCREENS_DIR/cardb ./cmd/cardb` |
| web | `cd web && npm ci && npm run build` (Node 22) |
| stack | `python3 demo_stack.py <repo> $SCREENS_DIR/photos` → cardb `:18484` + web `:14321`, 27 cars, hero = car 13 |
| phones | `SHOTS='[{"name":"list","path":"/"}, …]' node shoot.mjs <repo>/web http://127.0.0.1:14321 <out> light\|dark` (iPhone 13, DPR 3) |
| composite | `python3 compose.py web-overview.png list-light.png car-light.png queue-light.png` → `pngquant --strip` |
| agents | `python3 setup_home.py <repo>` (demo `CARHUNT_HOME`, file secrets, demo role briefs) → `carhunt secret set cardb_token` (seed token from `stack/tokens.json`) → `carhunt hooks install --yes && carhunt hooks statusline --yes` → `carhunt agent launch overseer\|sweep\|vet\|outreach-home` in a fresh agterm window → `agtermctl dashboard <ids> --font-size 10` → `screencapture -l $(swift winid.swift …)` → blank the account plan name in each Claude Code banner (solid fill) |
| terminal | `agtermctl session new --command term_demo.sh`, `surface zoom`, capture |

Then: privacy gate in [docs/privacy.md](../../privacy.md) + a fresh-eyes visual check of every image + OCR (`tesseract`) against the denylist. Close the demo window and kill the stack after.
