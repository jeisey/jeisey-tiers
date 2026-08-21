/**
 * End-to-end configuration.
 *
 * The suite runs against a real static build served from disk — not a dev server — because the
 * thing Phase 7 will deploy is a static build, and a dev server hides base-path and asset-URL
 * problems that only appear in one. `globalSetup` produces five builds: the root site, the
 * project-Pages site at `/jeisey-tiers/`, and three degraded-artifact scenarios.
 *
 * Every run is offline. The server maps a URL to a file under `web/dist*` and serves nothing
 * else, and `tests/e2e/board.spec.ts` additionally fails any request that leaves localhost.
 */

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 4173);

export default defineConfig({
  testDir: "web/tests/e2e",
  globalSetup: "./web/tests/e2e/global-setup.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI === undefined ? 0 : 1,
  reporter: process.env.CI === undefined ? [["list"]] : [["list"], ["html", { open: "never" }]],
  outputDir: "web/test-results",
  use: {
    baseURL: `http://localhost:${String(PORT)}`,
    trace: "retain-on-failure",
    // The sandboxed CI image ships a Chromium whose build number does not always match the
    // pinned Playwright release; `PLAYWRIGHT_CHROMIUM_EXECUTABLE` points at the one on disk.
    launchOptions:
      process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined
        ? {}
        : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
  },
  projects: [
    { name: "chromium", testIgnore: /mobile\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
    {
      name: "mobile",
      testMatch: /mobile\.spec\.ts/,
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: {
    command: `node web/tests/e2e/static-server.mjs`,
    port: PORT,
    reuseExistingServer: process.env.CI === undefined,
    env: { PORT: String(PORT) },
    stdout: "ignore",
  },
});
