import { defineConfig, devices } from "@playwright/test";

// Self-contained: global setup starts a throwaway cardb + this web on 127.0.0.1 with synthetic data.
export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    ...devices["iPhone 13"],
    browserName: "chromium",
    colorScheme: "dark",
    screenshot: "only-on-failure",
  },
  outputDir: process.env.E2E_OUT ?? "test-results",
});
