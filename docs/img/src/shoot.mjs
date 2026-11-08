// Phone screenshots of the demo web. Usage: node shoot.mjs <web-dir> <base-url> <out-dir> [scheme]
import { createRequire } from "node:module";
const [webDir, base, out, scheme = "light"] = process.argv.slice(2);
const require = createRequire(`${webDir}/package.json`);
const { chromium, devices } = require("@playwright/test");

const url = new URL(base);
if (!["127.0.0.1", "localhost"].includes(url.hostname)) throw new Error("local only");

const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices["iPhone 13"], deviceScaleFactor: 3, colorScheme: scheme, locale: "en-GB", timezoneId: "Europe/Lisbon" });
const page = await ctx.newPage();
const shots = JSON.parse(process.env.SHOTS || "[]");
try {
  for (const s of shots) {
    await page.goto(base + s.path, { waitUntil: "networkidle" });
    if (s.css) await page.addStyleTag({ content: s.css });
    if (s.click) await page.locator(s.click).first().click();
    if (s.scrollTo) await page.locator(s.scrollTo).first().evaluate((el, off) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - off), s.offset ?? 60);
    if (s.scrollY) await page.evaluate((y) => window.scrollTo(0, y), s.scrollY);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/${s.name}-${scheme}.png`, fullPage: !!s.full });
    console.log("shot", s.name);
  }
} finally {
  await browser.close();
}
