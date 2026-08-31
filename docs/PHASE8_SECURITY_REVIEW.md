# Phase-8 security and dependency review

Three questions, asked of the whole repository rather than of the diff: can a credential reach
somewhere it should not, can a private payload reach somewhere public, and is anything the
build depends on known to be vulnerable.

Where a finding is "none", the check that produced it is named — a review whose conclusions
cannot be re-run is an opinion.

---

## 1. The private-store credential

`MARKET_DATA_REPO_TOKEN` is a fine-grained token whose only scope is Contents on
`jeisey/jeisey-tiers-market-data`. Everything below is asserted by
`tests/integration/test_failure_drills.py`, so it is a gate rather than a paragraph.

| property | how it is enforced | check |
|---|---|---|
| referenced only where required | three call sites, all `with: token:` on the composite action | `grep`, and the assertions below |
| unreachable from pull-request CI | `ci.yml` never names the secret and never uses the store action | `test_continuous_integration_cannot_reach_the_private_store` |
| unreachable from a fork | repository secrets are not exposed to `pull_request` runs from forks; `ci.yml` additionally has nothing to hand one to | same |
| never in a shell | passed to `actions/checkout` through `with:`, never interpolated into `run:` | `test_no_workflow_echoes_a_secret` |
| never printed | the only shell that touches it tests emptiness with `[ -z ]` | same |
| no authenticated remote URL | the `https://x-access-token:…@github.com/…` construction is gone and cannot return | `test_no_workflow_builds_an_authenticated_remote_url` |
| not persisted into read-only checkouts | `persist-credentials: "false"` on the build job's store checkout | `test_read_only_store_checkouts_do_not_persist_a_credential` |
| never in the frontend environment | the frontend build reads `VITE_BASE_PATH` and nothing else; Vite only inlines `VITE_*` | `vite.config.ts`, and the boundary assertion below |

**Why `persist-credentials: false` is load-bearing rather than tidy.** The build job checks out
the store *and then* builds the frontend and packages the Pages artifact in the same workspace.
A token left in `.git/config` would be a credential inside the directory being packaged. The
capture job is the only one that pushes and is therefore the only one that keeps it.

**Scope of the blast radius if it leaked.** Contents on one private repository holding retained
vendor payloads. Not the application repository, not Pages, not Actions. Rotation is
`docs/OPERATIONS.md` section 5.3, and expiry is loud and non-destructive: the capture job fails
at its first step naming the secret, the deploy job is never reached, and the deployed site
stays live and stale.

### 1.1 The MFL client secrets

`MFL_API_USER_AGENT` and `MFL_API_CLIENT_NAME` identify this project to MyFantasyLeague on an
endpoint that needs no authentication. Absence degrades request *identity*, not access, and
`ffdraft config-check` reports presence without ever printing a value (ADR-017). No username,
password, `APIKEY` or `Authorization` header is attached on the public ADP path.

---

## 2. What reaches a public artifact

Two publication surfaces, both world-readable because the repository is public.

**The Pages artifact.** Only `web/dist` is uploaded, and the workflow asserts the boundary
itself rather than claiming it: a `find` for `.git`, `.env`, `__pycache__`, `*.parquet`, `*.py`,
`*.gz`, `market-data` and `node_modules` must return nothing. Pinned by
`test_the_pages_artifact_boundary_is_asserted_by_the_workflow_itself`.

**The build-record workflow artifact.** This is the one worth being careful about: a workflow
artifact on a public repository is world-readable, and the build record exists to explain a
refresh. It stages the retained store's `manifest.json` files **by whitelist** —
`find . -name manifest.json` — rather than by copying the store and filtering, and then asserts
that no `.gz` reached it. A whitelist cannot leak a file type nobody thought of; a blocklist
can.

**What a manifest contains, and why it is safe.** Provenance and integrity: source id, season,
snapshot key, retrieval timestamp, adapter and policy versions, content hashes, and per-cohort
counts (drafts, rows, resolved, ambiguous). No player rows, no prices, no vendor bytes. The
counts are the same aggregates the public job summary already prints.

**Capture logs.** `snapshot-market` and `capture-status` print snapshot keys, cohort ids and
counts. Neither prints a player row, a price or a raw payload. The job summary embeds those
logs, so this was checked directly rather than assumed.

**The published artifacts themselves** carry Sleeper-derived status fields to every visitor,
which is exactly why the repository and the site are non-commercial and free — a licence
condition, recorded in ADR-016 as amended and attributed on the Data view.

---

## 3. Workflow permissions

| workflow | top-level | elevations |
|---|---|---|
| `ci.yml` | `contents: read` | none |
| `daily-refresh.yml` | `contents: read` | `deploy` only: `pages: write`, `id-token: write` |
| `market-capture.yml` | `contents: read` | none |
| `retrain.yml` | `contents: read` | none |
| `source-probe.yml`, `source-probe-ffc.yml` | `contents: read` | none |

Exactly one job in the repository holds a `pages:` scope, and
`test_no_workflow_but_the_deploy_job_may_touch_pages` fails if a second appears or if the first
moves out of the deploy job. Both capture jobs write to *another* repository through a scoped
token, so neither needs `contents: write` here.

**The deploy job does no work.** It contains `configure-pages` and `deploy-pages` and nothing
else — asserted, because a build step inside the one job holding `pages: write` would be a step
that can fail after something irreversible has happened.

---

## 4. Supply chain

### 4.1 Actions

Every action is first-party `actions/*` plus the repository's own composite action. **No
community action, no unpinned third-party code.**

| action | version | used |
|---|---|---:|
| `actions/checkout` | v4 | 13 |
| `actions/cache` | v4 | 12 |
| `actions/setup-python` | v5 | 9 |
| `actions/upload-artifact` | v4 | 7 |
| `actions/setup-node` | v4 | 4 |
| `./.github/actions/market-data-store` | local | 3 |
| `actions/upload-pages-artifact` | v3 | 1 |
| `actions/download-artifact` | v4 | 1 |
| `actions/deploy-pages` | v4 | 1 |
| `actions/configure-pages` | v5 | 1 |

Major tags rather than commit SHAs. That is a deliberate trade for first-party actions from
the platform vendor: SHA-pinning them would mean hand-tracking security patches for ten
actions, and the threat it defends against — a compromised tag — is one where the same actor
already controls the runner. A **third-party** action would be pinned to a SHA, and there are
none.

One upstream notice, not actionable here: GitHub is deprecating Node 20 and forcing Node 24 for
actions that target it. Every action above is first-party and will move on its own.

### 4.2 Python

`uv.lock`, 46 packages, `uv sync --frozen` in every workflow.

```
uv run --python 3.12 --with pip-audit pip-audit --skip-editable
No known vulnerabilities found
```

Production dependencies are ten, each with a recorded reason: `jsonschema`, `lightgbm`,
`nflreadpy`, `numpy`, `polars`, `pydantic`, `pyyaml`, `requests`, `rfc3339-validator`,
`ruptures`. Development adds `mypy`, `pytest`, `ruff`, `scipy` and three `types-*` stubs.

**No binary serialization anywhere.** The production model is 120 gzipped LightGBM *text*
boosters plus a JSON metadata file with a SHA-256 per booster; loading reads JSON and
LightGBM's documented text format and verifies each digest, so a tampered booster fails closed.
Nothing in the repository calls `pickle`, `joblib` or `torch.load`, and
`docs/PHASE8_MODEL_AUDIT` (below) re-hashed all 120 with zero mismatches.

### 4.3 Node

`package-lock.json`, `npm ci` in every workflow.

```
npm audit
0 vulnerabilities (info 0, low 0, moderate 0, high 0, critical 0)
```

Production dependencies after this phase: **`react`, `react-dom`, `@tanstack/react-table`.**
`d3-scale`, `d3-array` and their `@types` were removed — the Phase-8 encodings are CSS geometry
rather than SVG, so nothing imported them, and an unused runtime dependency in a published
bundle is exactly the thing this review is for (ADR-059).

`@axe-core/playwright` was added, dev-only and exact-pinned.

**Deliberately not upgraded.** Fourteen packages have newer majors: `eslint` 10, `typescript`
7, `vite` 8, `vitest` 4, `jsdom` 30, `@tanstack/react-table` 9 and others. None is a security
fix — the audit is clean at the pinned versions — and the brief for this phase is explicit that
a major-version bump needs a security, browser-support, correctness or maintenance reason.
TanStack v9 is additionally pinned by ADR-048 as the v8-not-v9 decision. Upgrading the
toolchain during final hardening would trade a known-good gate for an unknown one.

---

## 5. Secrets in the tree

`git log --all` and the working tree were scanned in Phase 7 across 517 paths and 56 commits;
the one credential-*shaped* match was the authenticated-remote construction, now removed and
now pinned against by a test. Re-checked for this phase over the Phase-8 diff: no `.env`, no key
material, no token literal, no raw vendor payload, no `data/historical/`, no `web/public/data/`.

`.gitignore` covers `data/historical/`, `web/public/data/`, `web/dist*`, `.env*`, caches and
`predictions.parquet`.

---

## 6. Findings

**No critical or high finding.** Two observations, neither actionable now:

1. **Actions are tagged, not SHA-pinned.** Accepted as reasoned above; revisit if a
   non-first-party action is ever introduced, which should itself require an ADR.
2. **Fourteen dev dependencies are a major version behind.** Not a vulnerability. Worth a
   deliberate toolchain upgrade *after* a release tag, when a red gate costs a day rather than
   a launch.
