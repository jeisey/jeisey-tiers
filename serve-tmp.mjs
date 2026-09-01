import { createStaticServer } from "./web/tests/e2e/static-server.mjs";
createStaticServer({ roots: [{ base: "/jeisey-tiers/", dir: "web/dist" }] }).listen(4190, () =>
  console.log("up"));
