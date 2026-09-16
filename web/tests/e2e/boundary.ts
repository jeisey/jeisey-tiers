/**
 * The browser boundary, in one place (ADR-087).
 *
 * `docs/ARCHITECTURE.md` section 3.2 says the page may load only generated files, and until
 * the player card gained a portrait that was absolute: every spec asserted that no request
 * left `localhost`, and that assertion was the check behind the fonts being vendored rather
 * than linked. The portrait opens it by exactly one host, so the rule now has two halves and
 * both of them live here rather than in three hand-copied `beforeEach` blocks.
 *
 * **1. Nothing reaches a third party during a test.** `stubPortraits` intercepts the one
 * allowed host and fulfils it locally with a 1x1 PNG. A suite that really fetched a provider's
 * image would fail on a sandbox with no egress, flake when the provider was slow, and quietly
 * depend on somebody else's uptime for a green run — and it would make a hundred requests to
 * a third party every time CI ran, which is not a thing a test should do on a reader's behalf.
 *
 * **2. Every other host is still a failure.** `forbidExternalRequests` fails on any URL that
 * is not `localhost`, `data:`, `blob:` or the declared portrait host. The allowance is the
 * host, not "any image": a request to a different CDN, or to a vendor API, is the same failure
 * it was before.
 *
 * What the returned recorder is for: *when* the portrait is fetched is the property that
 * matters, not just whether. A board that fetched portraits on first paint would put a third
 * party on the critical render path while passing every assertion about hosts.
 */

import { expect, type Page } from "@playwright/test";

/** The one third-party origin this product may reach. Mirrors `ffdraft.headshots`. */
export const PORTRAIT_HOST = "a.espncdn.com";

/** A 1x1 transparent PNG. Small enough to inline, real enough for the browser to decode. */
const PIXEL = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

export interface PortraitRecorder {
  /** Every portrait URL the page has asked for, in order. */
  readonly requested: string[];
}

/**
 * Intercept the portrait host and serve a local pixel, recording what was asked for.
 *
 * Call it before the first navigation. The recorder is live: read `requested.length` after a
 * board load to prove first paint fetched nothing, and again after opening a card.
 */
export async function stubPortraits(page: Page): Promise<PortraitRecorder> {
  const requested: string[] = [];
  await page.route(`https://${PORTRAIT_HOST}/**`, async (route) => {
    requested.push(route.request().url());
    await route.fulfill({ status: 200, contentType: "image/png", body: PIXEL });
  });
  return { requested };
}

/**
 * Fail the test on any request that leaves the static server, bar the one declared host.
 *
 * `message` names what the spec is protecting, because the same guard is the fonts rule in one
 * spec and the no-vendor-chart rule in another.
 */
export function forbidExternalRequests(
  page: Page,
  message = "the browser must fetch only generated artifacts",
): void {
  const escaped: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (
      url.startsWith("http://localhost") ||
      url.startsWith("data:") ||
      url.startsWith("blob:") ||
      url.startsWith(`https://${PORTRAIT_HOST}/`)
    ) {
      return;
    }
    escaped.push(url);
  });
  page.on("close", () => {
    expect(escaped, message).toEqual([]);
  });
}

/** Both halves, which is what every spec wants. */
export async function guardBoundary(page: Page, message?: string): Promise<PortraitRecorder> {
  forbidExternalRequests(page, message);
  return stubPortraits(page);
}
