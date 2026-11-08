// Playwright MCP --init-page for browsers/bin/serve: every tab of the headless browser sends what the same
// Chrome sends headed, i.e. its User-Agent without "HeadlessChrome" and its own client hints.
// Playwright's --user-agent derives wrong hints (arch "x86") and Chrome's switch blanks them (measured 10-14),
// so this sets them through CDP.
let identity;
const sessions = new WeakMap(); // the override lives as long as its CDP session

async function readIdentity(page, cdp) {
  const { userAgent } = await cdp.send("Browser.getVersion");
  // userAgentData needs a secure context: a fulfilled https page (no network), then back to about:blank.
  const url = "https://ua-probe.invalid/";
  const serve = (route) => route.fulfill({ contentType: "text/html", body: "" });
  await page.route(url, serve);
  await page.goto(url);
  const userAgentMetadata = await page.evaluate(async () => {
    const h = await navigator.userAgentData.getHighEntropyValues(["architecture", "bitness", "model", "platformVersion", "fullVersionList", "wow64", "formFactors"]);
    const { brands, fullVersionList, platform, platformVersion, architecture, model, mobile, bitness, wow64, formFactors } = h;
    return { brands, fullVersionList, platform, platformVersion, architecture, model, mobile, bitness, wow64, formFactors };
  });
  await page.goto("about:blank");
  await page.unroute(url, serve);
  return { userAgent: userAgent.replace("HeadlessChrome/", "Chrome/"), userAgentMetadata };
}

// Playwright MCP loads it as require(file).default.
exports.default = async function headedIdentity({ page }) {
  const cdp = await page.context().newCDPSession(page);
  sessions.set(page, cdp);
  identity ??= readIdentity(page, cdp);
  await cdp.send("Emulation.setUserAgentOverride", await identity);
};
