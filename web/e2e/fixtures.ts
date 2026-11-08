import { test as base, expect, type Page } from "@playwright/test";
import { assertLocal, type Seeded } from "./stack";

export { expect };
export const seeded = (): Seeded => JSON.parse(process.env.E2E_SEEDED ?? "{}");

// baseURL comes from global setup (random free port), never from a hand-set prod URL.
export const test = base.extend({
  baseURL: async ({}, use) => {
    const url = process.env.E2E_BASE_URL ?? "";
    assertLocal(url);
    await use(url);
  },
});

/** Islands carry `ssr` until React hydrates them. */
export async function hydrated(page: Page) {
  await expect(page.locator("astro-island[ssr]")).toHaveCount(0);
}

/** Switch "Viewing as" in the header picker. */
export async function viewAs(page: Page, name: string) {
  await page.getByLabel("Viewing as").selectOption(name);
  await page.waitForLoadState("load");
  await expect(page.getByLabel("Viewing as")).toHaveValue(name);
}
