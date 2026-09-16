/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The app source lives under `web/` while the toolchain config sits at the repository root,
// matching the layout in docs/ARCHITECTURE.md section 4.
//
// `base` is derived from the environment rather than hard-coded, because GitHub Pages serves
// a project site from `/<repo>/` while a custom domain serves from `/`. Section 11 of the
// architecture requires the build to work for both, and Phase 7 sets VITE_BASE_PATH in the
// deploy workflow.
export default defineConfig({
  root: "web",
  base: process.env.VITE_BASE_PATH ?? "/",
  plugins: [react()],
  build: {
    // Relative to `root`, so artifacts land in web/dist (gitignored).
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: "jsdom",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    setupFiles: ["tests/setup.ts"],
    restoreMocks: true,
    /*
     * Above Vitest's 5s default, because a good many of these tests render the whole App into
     * jsdom and wait for an artifact load to settle. One of those takes about a second on an
     * idle machine and several times that when four workers are competing for the CPU, so the
     * default budget was already marginal and ADR-086's three new files tipped it: the same
     * tests passed file-by-file and timed out in the full run.
     *
     * Nothing here is a test whose failure mode is a hang — a wrong assertion throws from
     * `getBy*` immediately — so the cost of the larger budget is paid only by a `waitFor` that
     * was going to fail anyway, and the benefit is that a green suite means what it says on a
     * loaded CI runner as well as on an idle laptop.
     */
    testTimeout: 15_000,
    hookTimeout: 15_000,
  },
});
