import { expect, hydrated, seeded, test, viewAs } from "./fixtures";
import { HOME_CITY, OWNER, VIEWER } from "./stack";

test.describe.configure({ mode: "serial" });

test("list → filter → car page → verdict → note (owner)", async ({ page }) => {
  const { bev, ice } = seeded();
  await page.goto("/?view=all");
  await expect(page.getByTestId("car-card")).toHaveCount(4);
  await expect(page.getByTestId("viewer-name").or(page.getByLabel("Viewing as"))).toBeVisible();

  // Filter: electric only, via the filter sheet.
  await page.getByText("⚙ Filters").click();
  await page.getByText("Electric", { exact: true }).click();
  await page.getByRole("button", { name: "Apply" }).click();
  await expect(page).toHaveURL(/fuel=bev/);
  await expect(page.getByTestId("car-card")).toHaveCount(3);
  await expect(page.locator(`[data-car-id="${ice}"]`)).toHaveCount(0);

  // Card: powertrain token, distance, needs-owner flag in the owner's name.
  const card = page.locator(`[data-car-id="${bev}"]`);
  await expect(card).toContainText("77 kWh");
  await expect(card).toContainText("120 km");
  await expect(card.getByTestId("needs-owner")).toContainText("Seller asks for a call slot");

  await card.locator("a").first().click();
  await expect(page).toHaveURL(new RegExp(`/cars/${bev}$`));
  await expect(page.getByTestId("car-title")).toContainText("Examplo Voltara");
  await hydrated(page);

  // Powertrain block + distance label from the profile's home city.
  const pt = page.getByTestId("powertrain");
  await expect(pt).toContainText("Electric");
  await expect(pt).toContainText("77 net / 82 gross kWh");
  await expect(pt).toContainText("Battery health");
  await expect(pt).toContainText("95 % (certificate)");
  await expect(page.getByText(`120 km to ${HOME_CITY}`)).toBeVisible();

  // Verdict with a note.
  await page.getByRole("button", { name: "Maybe", exact: true }).first().click();
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "maybe");
  await expect(page.getByText("saving…")).toHaveCount(0);
  const vnote = page.getByLabel("Verdict note").first();
  await vnote.fill("e2e verdict note");
  await vnote.press("Enter");
  await expect(page.getByText("saving…")).toHaveCount(0);

  // Note.
  await page.getByLabel("New note").fill("e2e note from the owner");
  await page.getByRole("button", { name: "Add note" }).click();
  const note = page.getByTestId("notes").locator("li", { hasText: "e2e note from the owner" });
  await expect(note).toBeVisible();
  await expect(note).toContainText("You");

  // Persisted across a reload and on the list card.
  await page.reload();
  await hydrated(page);
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "maybe");
  await expect(page.getByLabel("Verdict note").first()).toHaveValue("e2e verdict note");
  await expect(page.getByTestId("notes").getByText("e2e note from the owner")).toBeVisible();
  await page.goto("/?view=all");
  await expect(page.locator(`[data-car-id="${bev}"] .qv`)).toHaveAttribute("data-verdict", "maybe");
});

test("combustion car shows engine, gearbox and engine health, no battery", async ({ page }) => {
  const { ice } = seeded();
  await page.goto(`/cars/${ice}`);
  const pt = page.getByTestId("powertrain");
  await expect(pt).toContainText("Diesel");
  await expect(pt).toContainText("2.0 l");
  await expect(pt).toContainText("automatic");
  await expect(pt).toContainText("5.2 l/100 km");
  await expect(pt).toContainText("Timing belt");
  await expect(pt).not.toContainText("Battery");
  await expect(page.getByTestId("car-specs")).toContainText("2.0 l diesel auto");
});

test("viewer rates separately and cannot edit", async ({ page }) => {
  const { bev } = seeded();
  await page.goto(`/cars/${bev}`);
  await viewAs(page, VIEWER);
  await hydrated(page);
  await expect(page.getByTestId("status-readonly")).toBeVisible();
  await expect(page.getByLabel("Status")).toHaveCount(0);
  await expect(page.getByLabel("New note")).toHaveCount(0);
  await expect(page.getByTestId("good-deal-toggle")).toHaveCount(0);
  // Kim sees Sam's verdict as someone else's, and has none yet.
  await expect(page.getByTestId("other-verdicts").locator(`[data-user="${OWNER}"]`)).toHaveAttribute("data-verdict", "maybe");
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "none");

  await page.getByRole("button", { name: "Like", exact: true }).first().click();
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "up");
  await expect(page.getByText("saving…")).toHaveCount(0);
  await page.reload();
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "up");

  // The proxy refuses a viewer's note even when sent by hand.
  const res = await page.request.post(`/ui/cars/${bev}/notes`, { data: { text: "sneaky" }, headers: { Origin: new URL(page.url()).origin } });
  expect(res.status()).toBe(403);

  // Back to the owner: own verdict untouched, Kim's shown beside it.
  await viewAs(page, OWNER);
  await hydrated(page);
  await expect(page.getByTestId("verdict-control")).toHaveAttribute("data-verdict", "maybe");
  await expect(page.getByTestId("other-verdicts").locator(`[data-user="${VIEWER}"]`)).toHaveAttribute("data-verdict", "up");
});

test("needs-owner tab carries the owner's name", async ({ page }) => {
  const { bev } = seeded();
  await page.goto("/");
  const tab = page.getByTestId("view-needs");
  await expect(tab).toContainText(`Needs ${OWNER}`);
  await tab.click();
  await expect(page.getByTestId("car-card")).toHaveCount(1);
  await expect(page.locator(`[data-car-id="${bev}"]`)).toBeVisible();
});

test("to-rate queue: rate collapses the row, undo brings it back", async ({ page }) => {
  const { queueA, queueB, ice } = seeded();
  await page.goto("/queue");
  const rows = page.getByTestId("queue-row");
  // bev is rated by the owner already; ice is tier 3 (hidden by default).
  await expect(rows).toHaveCount(2);
  await expect(page.locator(`[data-testid="queue-row"][data-car-id="${ice}"]`)).toHaveCount(0);
  await expect(page.locator(`[data-testid="queue-row"][data-car-id="${queueA}"] [data-testid="tier-chip"]`)).toHaveText("T1");
  await expect(page.locator(`[data-testid="queue-row"][data-car-id="${queueB}"] [data-testid="tier-chip"]`)).toHaveText("T2");
  await expect(page.getByTestId("spec-filters")).toContainText("Electric seats ✓");
  const count = page.getByTestId("queue-count");
  await expect(count).toHaveText("2");

  await page.locator(`[data-testid="queue-row"][data-car-id="${queueA}"]`).getByTestId("queue-rate-down").click();
  await expect(rows).toHaveCount(1);
  await expect(count).toHaveText("1");
  await expect(page.getByTestId("queue-undo")).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(rows).toHaveCount(2);
  await expect(count).toHaveText("2");

  // Tier 3 behind the toggle.
  await page.getByTestId("tiers-toggle").click();
  await expect(page).toHaveURL(/all=1/);
  await expect(page.locator(`[data-testid="queue-row"][data-car-id="${ice}"] [data-testid="tier-chip"]`)).toHaveText("T3");
});

test("photo lightbox opens, pages and closes", async ({ page }) => {
  const { bev } = seeded();
  await page.goto(`/cars/${bev}`);
  const photos = page.getByTestId("gallery-photo");
  await expect(photos).toHaveCount(2);
  await photos.first().click();
  const dlg = page.locator("dialog[data-lightbox-dialog]");
  await expect(dlg).toBeVisible();
  await expect(dlg.locator("[data-lb-counter]")).toHaveText(/1\s*\/\s*2/);
  await dlg.getByRole("button", { name: "Next photo" }).click();
  await expect(dlg.locator("[data-lb-counter]")).toHaveText(/2\s*\/\s*2/);
  await expect(dlg.locator("[data-lb-img]")).toHaveJSProperty("complete", true);
  await dlg.getByRole("button", { name: "Close" }).click();
  await expect(dlg).toBeHidden();
});

test("the browser never sees a token; cross-site writes are refused", async ({ page }) => {
  const { bev } = seeded();
  const html = await (await page.request.get(`/cars/${bev}`)).text();
  const tokens = (process.env.E2E_TOKENS ?? "").split(",").filter(Boolean);
  expect(tokens.length).toBe(3);
  for (const t of tokens) expect(html).not.toContain(t);
  expect(html).not.toMatch(/Bearer/);
  const res = await page.request.put(`/ui/cars/${bev}/verdict`, { data: { value: "down" }, headers: { Origin: "https://evil.example" } });
  expect(res.status()).toBe(403);
  const off = await page.request.post(`/ui/listings/upsert`, { data: { url: "https://example.invalid/x" } });
  expect(off.status()).toBe(405);
});
