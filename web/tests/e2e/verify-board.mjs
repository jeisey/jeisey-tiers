/**
 * Serve a built site and cross-check what it renders against the artifact bytes it serves.
 *
 * `verify-real-build.mjs` does the comparing and needs a URL plus a directory of artifacts.
 * Phase 6 supplied both by hand. Phase 7 deploys this on a schedule, so the harness that
 * puts a server in front of a build has to be a command rather than a habit — the daily
 * refresh runs it against the build it is about to publish, and again against the site it
 * just published.
 *
 *   node web/tests/e2e/verify-board.mjs                       # serve web/dist, check it
 *   node web/tests/e2e/verify-board.mjs --base-path /jeisey-tiers/
 *   node web/tests/e2e/verify-board.mjs --url https://user.github.io/repo/ --data web/dist/data
 *
 * With `--url` no server is started: the check runs against a site someone else is serving,
 * which is how the deployed production smoke test works. The artifacts still come from disk,
 * because the point of the check is to compare the rendered page with the bytes the build
 * produced.
 */

import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createStaticServer } from "./static-server.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");

function parseArgs(argv) {
  const args = { dist: "web/dist", data: null, basePath: "/", port: 4180, url: null };
  for (let i = 0; i < argv.length; i += 1) {
    const [flag, inline] = argv[i].split("=");
    const value = inline ?? argv[++i];
    switch (flag) {
      case "--dist":
        args.dist = value;
        break;
      case "--data":
        args.data = value;
        break;
      case "--base-path":
        args.basePath = value.endsWith("/") ? value : `${value}/`;
        break;
      case "--port":
        args.port = Number(value);
        break;
      case "--url":
        args.url = value.replace(/\/$/, "");
        break;
      default:
        throw new Error(`unknown option ${flag}`);
    }
  }
  args.data ??= `${args.dist}/data`;
  return args;
}

const args = parseArgs(process.argv.slice(2));
const dataDir = resolve(repo, args.data);
if (!existsSync(dataDir)) {
  console.error(`no artifacts at ${dataDir}. Build the site with web/public/data/ populated.`);
  process.exit(2);
}

/** Run the comparer as a child so its own exit code is the verdict, unmodified. */
function verify(base) {
  return new Promise((done) => {
    const child = spawn(
      process.execPath,
      [resolve(here, "verify-real-build.mjs"), base, dataDir],
      { cwd: repo, stdio: "inherit", env: process.env },
    );
    child.on("close", (code) => done(code ?? 1));
  });
}

if (args.url !== null) {
  console.log(`verifying the deployed site at ${args.url} against ${args.data}`);
  process.exitCode = await verify(args.url);
} else {
  const distRoot = resolve(repo, args.dist);
  if (!existsSync(distRoot)) {
    console.error(`no build at ${distRoot}. Run \`npm run build\` first.`);
    process.exit(2);
  }
  // Mounted at the base path the build was made for, so a site built for `/jeisey-tiers/`
  // is checked at `/jeisey-tiers/` rather than at a root it would never be served from.
  const server = createStaticServer({ roots: [{ base: args.basePath, dir: distRoot }] });
  await new Promise((ready) => server.listen(args.port, ready));
  const base = `http://localhost:${args.port}${args.basePath.replace(/\/$/, "")}`;
  console.log(`verifying ${args.dist} served at ${base} against ${args.data}`);
  try {
    process.exitCode = await verify(base);
  } finally {
    server.close();
  }
}
