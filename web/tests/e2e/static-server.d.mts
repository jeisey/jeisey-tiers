/**
 * Types for `static-server.mjs`, so a TypeScript spec can mount a build of its own (ADR-116's
 * Insights share-link test serves the in-season Pages build at `/jeisey-tiers/`).
 */

import type { Server } from "node:http";

export declare const PAGES_GZIP_LEVEL: number;

export interface StaticRoot {
  readonly base: string;
  readonly dir: string;
}

export interface ServedEntry {
  readonly path: string;
  readonly status: number;
  readonly bytes: number;
}

export declare function createStaticServer(options: {
  readonly roots: readonly StaticRoot[];
  readonly pages?: { readonly maxAge?: number; readonly onServe?: (entry: ServedEntry) => void } | null;
}): Server;
