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
    restoreMocks: true,
  },
});
