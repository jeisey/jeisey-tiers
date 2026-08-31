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
 *
 * **Three engines, two suites.** `board.spec.ts` is the behavioural suite and runs on Chromium
 * only: sorting a table, parsing a query string and joining two artifacts do not vary by
 * engine, and running twenty-odd such specs three times would triple the slowest gate in the
 * repository to re-prove logic that has no engine dependency. `smoke.spec.ts` is the part that
 * does vary — layout, focus, `<dialog>` semantics, downloads, reduced motion — and runs on
 * Chromium, Firefox and WebKit. WebKit matters most: it shipped `<dialog>` and `::backdrop`
 * last of the three, and the Phase-8 player card is a dialog presented two different ways.
 */

import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 4173);

/**
 * Chromium's executable override, for the sandbox whose browser build does not match the
 * pinned Playwright release. Firefox and WebKit must never receive it.
 */
const chromiumLaunch =
  process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE === undefined
    ? {}
    : { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE };

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
    // It is applied per project below rather than globally, because pointing Firefox or
    // WebKit at a Chromium binary is worse than not running them.
    launchOptions: {},
  },
  projects: [
    {
      name: "chromium",
      testIgnore: [/mobile\.spec\.ts/, /smoke\.spec\.ts/, /a11y\.spec\.ts/],
      use: { ...devices["Desktop Chrome"], launchOptions: chromiumLaunch },
    },
    {
      name: "mobile",
      testMatch: /mobile\.spec\.ts/,
      use: { ...devices["Pixel 7"], launchOptions: chromiumLaunch },
    },
    // The accessibility audit: axe-core plus the keyboard and semantic checks a scanner
    // cannot make. One engine is enough — WCAG conformance is a property of the markup.
    {
      name: "a11y",
      testMatch: /a11y\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], launchOptions: chromiumLaunch },
    },
    // The cross-browser smoke. Chromium is included so a smoke failure can be told apart
    // from an engine difference: if it fails everywhere it is the product, not the browser.
    {
      name: "smoke-chromium",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], launchOptions: chromiumLaunch },
    },
    {
      name: "smoke-firefox",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "smoke-webkit",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Safari"] },
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
