/**
 * Build the sites the end-to-end run serves.
 *
 * Set `E2E_SKIP_BUILD=1` to reuse whatever is already on disk while iterating on a spec.
 */

import { prepare } from "./build-fixtures";

export default async function globalSetup(): Promise<void> {
  if (process.env.E2E_SKIP_BUILD === "1") return;
  await prepare();
}
