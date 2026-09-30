/**
 * Opening the site: the manifest, then only what the open view needs (ADR-098).
 *
 * Not every artifact is equally load-bearing, and that has not changed: `build_metadata` and
 * the tier board *are* the product, so a manifest that does not carry a version of either this
 * build understands is a refusal, never a best-effort render. Arbitrage, player status and
 * projections are additive: their absence degrades a feature rather than the page.
 *
 * What changed is how much is fetched to find that out. The whole-artifact loader downloaded
 * all fourteen artifacts, in a chain of sequential requests, before drawing anything; the
 * manifest now names every served file and carries both metadata objects inline, so one small
 * request decides the mode, the refusals and the degradations, and `DataStore` fetches the rest
 * in parallel as views and cards open.
 *
 * The browser fetches generated static files and nothing else — no MyFantasyLeague, no
 * Sleeper, no nflverse, no FantasyPros (`docs/ARCHITECTURE.md` section 3.2).
 */

import { CriticalArtifactError } from "./errors";
import { fetchManifest, pruneCache } from "./serving";
import { DataStore } from "./store";

export { CriticalArtifactError, type Degradation } from "./errors";

/**
 * Read the manifest and open the store, or refuse.
 *
 * Throws `CriticalArtifactError` for a missing or unreadable manifest, and for build metadata
 * or a tier board this build cannot read.
 */
export async function openSite(options: { readonly base?: string } = {}): Promise<DataStore> {
  let store: DataStore;
  try {
    store = new DataStore(await fetchManifest(options.base), options.base);
  } catch (error) {
    if (error instanceof CriticalArtifactError) throw error;
    throw new CriticalArtifactError("manifest.json", error);
  }
  // Housekeeping, off the critical path: the cache keeps one deploy's files, not every one's.
  setTimeout(() => {
    void pruneCache(store.manifest, options.base);
  }, 5_000);
  return store;
}
