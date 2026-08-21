/**
 * A static file server for end-to-end and visual QA runs.
 *
 * It serves the same `dist` tree twice: once at `/` and once at `/jeisey-tiers/`. Phase 7
 * deploys a project Pages site, whose base path is `/<repo>/`, and the point of testing both
 * here is that a routing or data-path bug is found now rather than after a deploy
 * (`docs/ARCHITECTURE.md` section 11).
 *
 * Deliberately dependency-free and deliberately offline: it maps a URL to a file under the
 * given roots and serves nothing else, so a test cannot accidentally reach a vendor.
 */

import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve } from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".csv": "text/csv; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

export function createStaticServer({ roots }) {
  return createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    let pathname = decodeURIComponent(url.pathname);

    const mount = roots.find(
      (entry) => pathname === entry.base.replace(/\/$/, "") || pathname.startsWith(entry.base),
    );
    if (mount === undefined) {
      response.writeHead(404, { "content-type": "text/plain" });
      response.end("no mount for this path");
      return;
    }

    pathname = pathname.slice(mount.base.length) || "index.html";
    // Contain the path inside the mount root; `..` must not escape it.
    const relative = normalize(pathname).replace(/^(\.\.[/\\])+/, "");
    let file = join(mount.dir, relative);
    if (!file.startsWith(resolve(mount.dir))) {
      response.writeHead(403, { "content-type": "text/plain" });
      response.end("forbidden");
      return;
    }
    if (existsSync(file) && statSync(file).isDirectory()) file = join(file, "index.html");
    if (!existsSync(file)) {
      // No SPA fallback for data: a missing artifact must 404 so the degraded path is exercised.
      if (relative.startsWith("data/")) {
        response.writeHead(404, { "content-type": "text/plain" });
        response.end("not found");
        return;
      }
      file = join(mount.dir, "index.html");
    }

    response.writeHead(200, {
      "content-type": TYPES[extname(file)] ?? "application/octet-stream",
      "cache-control": "no-store",
    });
    createReadStream(file).pipe(response);
  });
}

const port = Number(process.env.PORT ?? 4173);

/**
 * Mounts, most specific first.
 *
 * The degraded scenarios are separate builds served at separate prefixes rather than one build
 * whose files a test mutates: a run then has no shared state to reset, and two tests can never
 * see each other's outage.
 */
const MOUNTS = [
  { base: "/jeisey-tiers/", dir: "web/dist-base" },
  { base: "/scenario/no-market/", dir: "web/dist-no-market" },
  { base: "/scenario/no-status/", dir: "web/dist-no-status" },
  { base: "/scenario/bad-schema/", dir: "web/dist-bad-schema" },
  { base: "/", dir: "web/dist" },
];

createStaticServer({
  roots: MOUNTS.map((mount) => ({ base: mount.base, dir: resolve(mount.dir) })),
}).listen(port, () => {
  process.stdout.write(`static server on http://localhost:${String(port)}/\n`);
});
