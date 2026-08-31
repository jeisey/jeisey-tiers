# Operations, GitHub Actions, and Deployment

## 1. Operational objective

The public site should refresh daily without a server and should fail **safe**, not fail **fresh**. A stale correct site is preferable to a newly deployed corrupt one.

## 2. Workflows

### 2.1 `ci.yml`

Triggers:

- pull requests
- pushes to default branch where source/config/code paths matter
- manual dispatch optional

Permissions: read-only contents unless a specific test requires more (it should not).

Jobs:

1. Python setup via `uv` + frozen lock.
2. Python lint/format/type/tests.
3. Fixture mini pipeline + schema validation.
4. Node setup + `npm ci`.
5. frontend lint/type/unit.
6. build with fixture/public sample data.
7. optional Playwright smoke.

No live data vendor access in normal PR CI.

> **Phase-7 status: complete, three jobs.**
>
> - `python` — uv sync --frozen, `ruff check`, `ruff format --check`, `mypy`, `pytest` (with a JUnit report so the summary can count), `ffdraft config-check`, the fixture mini-pipeline, `validate-artifacts`, and a staleness check on the committed golden artifacts.
> - `web` — npm ci, lint, typecheck, vitest, a root build, and a project-Pages base-path build that asserts both that assets resolve under `/jeisey-tiers/` **and** that no absolute `/assets/` or `/data/` path survived.
> - `e2e` — Playwright over five built sites (root, `/jeisey-tiers/`, three degraded-artifact scenarios).
>
> Caching: `~/.cache/uv` keyed on the lockfile, npm through `setup-node`, and the Playwright browser keyed on `package-lock.json` so a client upgrade can never pair with an old browser build. Each job writes a step summary.
>
> Permissions are `contents: read` with no per-job elevation, and three properties are pinned by `tests/unit/test_workflows.py` rather than left to review: CI never references `MARKET_DATA_REPO_TOKEN` or checks out the retained store, never runs a command that needs a vendor, and never requests a `pages:` scope. A pull request from a fork therefore cannot reach private data, and a MyFantasyLeague outage cannot turn a pull request red.

### 2.2 `daily-refresh.yml`

Triggers:

- `workflow_dispatch`
- daily schedule

Schedule: **07:17 America/New_York**. The non-round minute is deliberate — GitHub documents that scheduled workflows can be delayed during high load at the start of an hour — and the hour comes from Phase-0 evidence: 2026 depth-chart snapshots land at roughly 07:25-08:25 UTC, so this run reads a same-day snapshot (section 2.4).

**Current syntax, verified 2026-08-22.** GitHub Actions added an optional `timezone` field on `on.schedule` entries in March 2026, taking an IANA timezone name. The workflow therefore declares the wall-clock time and the zone, and daylight saving is handled upstream instead of being encoded as a UTC offset that would need editing twice a year:

```yaml
on:
  schedule:
    - cron: "17 7 * * *"
      timezone: America/New_York
```

`tests/unit/test_workflows.py` asserts the minute, the hour and the zone, so a future edit that silently reverts to a UTC offset fails a test.

**The implementation is three jobs plus a report, and the shape is the point (ADR-050).**

```text
capture ──▶ build ──▶ deploy          report (needs all three, if: always())
```

`capture` — the only job that contacts a vendor, and the only irreversible one:

1. check out the application source and the **private** retained store (`.github/actions/market-data-store`, with `persist-credentials: true` because this job pushes);
2. `ffdraft snapshot-market` — MFL cohorts plus the player directory, normalized and identity-resolved into the store;
3. `ffdraft capture-status` — the Sleeper current-status capture;
4. `ffdraft validate-market-history` — re-hash the whole store **before** anything is pushed, so a corrupt write is caught in the workspace rather than committed;
5. commit and push to the private store.

`build` — entirely offline; it reads retained bytes and the committed production model:

6. check out the store **at the exact commit `capture` pushed**, read-only (`persist-credentials: false`);
7. `ffdraft build-current` — loads the production model, does **not** retrain, and refuses to run if the feature-set or feature-schema hash disagrees (ADR-037);
8. `ffdraft measure-market-cohorts` — re-runs the frozen selection rule against the newest snapshot (ADR-039), writing outside the checkout;
9. `ffdraft build-arbitrage` — the deterministic A0 board against that selection;
10. `validate-artifacts` — the pre-deploy gate;
11. `npm ci`, then `npm run build` at `VITE_BASE_PATH=/jeisey-tiers/`, asserting the asset URLs and that every artifact reached `web/dist/data/`;
12. `npm run verify:board` — the rendered board cross-checked against the artifact bytes, on the real board rather than fixtures;
13. assert the Pages artifact boundary, then `actions/upload-pages-artifact` as the **last** step.

`deploy` — `actions/configure-pages` and `actions/deploy-pages`, nothing else.

`report` — renders `scripts/workflow_summary.py` into the step summary whatever happened, so a failed refresh explains itself in the same place a successful one does.

**Manual dispatch inputs.** `season` and `cohorts` override the defaults. `skip_capture` rebuilds and redeploys from retained history without calling a vendor — the intended way to re-run a deploy after a code fix, because MFL asks that the player database be requested at most once a day (ADR-017). `force_validation_failure` is the proof run described in section 8.

### 2.3 `retrain.yml`

Triggers:

- weekly schedule during active draft season, e.g. Sunday off-the-hour;
- manual dispatch always;

Offseason cadence can be reduced or schedule disabled/documented.

Steps:

1. build/reuse historical feature dataset;
2. run baseline and candidate folds;
3. calibrate candidate;
4. run leakage/feature audits;
5. generate metrics/model card;
6. compare candidate vs incumbent;
7. save candidate artifacts;
8. promote only if automated gate is fully deterministic and approved by spec, otherwise emit artifact/PR for review.

Retraining does not directly deploy the website unless followed by a normal validated inference/build path.

> **Phase-7 status: implemented, and it mostly declines to run (ADR-051).**
>
> The weekly schedule is kept — Sunday 06:43 America/New_York — but the first job is an **evidence gate**, not a build. `scripts/retrain_gate.py` asks whether there is a season after the model's last training season whose *fantasy horizon* is complete in the upstream weekly statistics. An unplayed season (nflverse answers 404) is "no"; an in-progress season whose weekly file stops short of the horizon is "no". Only a finished season is "yes". "Nothing to retrain" exits **0** and says which season it checked and why it did not qualify.
>
> That matters in August 2026 specifically: `intrinsic-cb-hurdle-v1` is trained through 2025, **2025 is the spent final holdout** (ADR-036) and cannot be re-sealed, and 2026 has not been played. A literal weekly retrain would either rebuild the same artifact or quietly consume partial in-season 2026 outcomes.
>
> When the gate does pass, the candidate job builds the historical dataset **with the independence proof on**, validates it, and runs `evaluate-intrinsic` on development folds. Its output is a workflow artifact and nothing else: the job asserts `models/` is unchanged before it finishes.
>
> `retrain.yml` holds `contents: read` everywhere, has no `pages:` scope, contains no Pages action and never pushes — all asserted by `tests/unit/test_workflows.py`. `ffdraft train-production` is deliberately absent: it needs a confirmation token and a written reason, and that token must never become a repository secret, because a token in a secret is a token a scheduled job can use.
>
> **Promotion path, in order:** a new evaluation/holdout protocol (2025 is spent) → `ffdraft train-production`, run deliberately → `ffdraft model-card` regenerated → an ordinary `daily-refresh`, which is the only path to Pages.

### 2.4 `source-probe.yml` (Phase-0 infrastructure)

Triggers: `workflow_dispatch`, plus pushes to `claude/phase-0-**` that touch the probe, its lockfile or the workflow itself.

Permissions: `contents: read` at workflow level, elevated to `contents: write` only in the probe job, which commits its report to the working branch.

Purpose: run `scripts/source_probe.py` in an environment with unrestricted egress and record what each source actually returns. It exists because source verification cannot be trusted to a development sandbox behind an egress policy (ADR-009). It is **not** part of the production refresh path and must never gate a deploy.

Re-run it before a launch, before promoting a model that depends on a source contract, or whenever an adapter starts failing in a way that smells like upstream drift.

Cadence facts confirmed by the probe and worth designing to:

- 2026 depth-chart snapshots land daily at roughly 07:25–08:25 UTC, so the recommended 07:17 America/New_York refresh (11:17/12:17 UTC) reads a same-day snapshot.
- MFL asks that the player database be requested no more than once per day and throttles over-limit clients with HTTP 429; the adapter needs backoff, and the player export needs a daily cache.
- Sleeper's player map is ~14.6 MB; fetch at most daily and stay well under the documented 1000 calls/minute.

## 3. Public repository cost

The architecture assumes a public repository using standard GitHub-hosted runners and GitHub Pages. GitHub's current documentation states standard hosted runners are free for public repositories and Pages is available for public repositories on GitHub Free. Avoid larger runners or paid services unless a future benchmark proves necessary.

> **Resolved in Phase 7 (2026-08-22).** `jeisey/jeisey-tiers` is now **public**, so the free-runner and Pages assumptions above hold. The Phase-0 observation and the ADR-016 deferral that replaced it are closed.
>
> The visibility change forced a storage change rather than following from one. The retained capture store used to be a branch of this repository, and GitHub visibility is a property of a repository, not of a branch — there is no private branch inside a public repository. The store therefore moved to a **separate private repository** first, and only then was visibility changed (**ADR-049**). Section 5.3 records the topology and the credential.
>
> Two obligations travel with publicity rather than with the deploy. The retained MFL and Sleeper payloads stay a private research cache, not a redistribution; and Sleeper's non-commercial terms bind what the site *publishes*, so the free, ad-free, non-commercial character of the deployment is a licence condition (`docs/SECURITY_LICENSE.md` section 10).

## 4. Caching

Cache:

- `uv`/Python package downloads
- npm cache
- nflreadpy download/cache where license and cache keys allow
- historical feature intermediates keyed by source/schema/config hashes

Do not cache:

- secrets
- mutable production model under an ambiguous key
- outputs in a way that can mix scoring/season/configs

Cache misses must be correct, only slower.

> **Phase-7 implementation.** Four caches, and the key of each is chosen so a hit and a miss cannot differ.
>
> | cache | path | key context | why the key is enough |
> |---|---|---|---|
> | uv | `~/.cache/uv` | runner OS, Python minor, `uv.lock` hash | a different lockfile is a different key, so a hit restores the same resolved set |
> | npm | handled by `setup-node` | `package-lock.json` | same argument, upstream |
> | Playwright browser | `~/.cache/ms-playwright` | runner OS, `package-lock.json` hash | the lockfile pins `@playwright/test`, so a client upgrade cannot pair with an old browser build |
> | nflverse downloads | `$RUNNER_TEMP/nflreadpy-cache` | runner OS, `uv.lock`, season, `config/source-registry.yaml` hash, **UTC date** | see below |
>
> The nflverse cache is the one that needed thought, and it has **no `restore-keys`** on purpose. The obvious pattern — a unique key plus a prefix fallback — would restore *yesterday's* release on a fresh key, which means a cache hit would serve staler rosters than a cache miss. That is precisely the failure this section forbids. With the UTC date in the key and no fallback, a hit can only ever be the same day's release; a miss re-downloads and is merely slower. `NFLREADPY_CACHE=filesystem` and `NFLREADPY_CACHE_DIR` point the client at it.
>
> Nothing caches a credential, a model artifact, or the private store. The store is a git checkout made fresh in each job that needs it, at a named commit.

## 5. Market snapshot persistence

Recommended separate `data` branch job has narrowly scoped `contents: write` permission and only runs after market validation.

Snapshot manifest includes:

- date/time
- source
- scoring/league cohort
- record count
- hash
- schema version
- retrieval source metadata

If snapshot persistence fails after current public output was otherwise computed, decide whether this is critical. Recommended: during draft season, treat failure as **critical for arbitrage deployment** because losing history undermines future modelability; Tier deployment may proceed independently if workflow architecture supports separate artifacts safely.

### 5.1 Phase-5 implementation

`.github/workflows/market-capture.yml` is the live mechanism, and it is deliberately the *minimum* Phase 5 needed: a manual `workflow_dispatch` plus a push trigger on a single request file, `.github/market-capture.request`. Editing market code never spends a runner or appends a snapshot; bumping `revision:` in the request file (and saying why) does. Scheduling remains a Phase-7 deliverable.

It runs on a GitHub runner for the reason ADR-009 recorded — the development sandbox answers 403 to `CONNECT` for `api.myfantasyleague.com` and `api.sleeper.app`, so verification there is impossible by construction — and it writes to the dedicated long-lived `market-data` branch, never to a code branch.

> **Phase-7 change (ADR-049).** That branch now lives in a separate private repository; see section 5.3. The commands, the order of operations and the idempotency argument below are unchanged. `market-capture.yml` is no longer the only capture mechanism either: `daily-refresh.yml` takes a capture every morning, and this workflow is now the deliberate out-of-band one — an extra snapshot before a rules change, a wide `study` capture for a cohort re-measurement, or a re-run of a failed capture.

Order of operations, and why:

1. `ffdraft snapshot-market` retrieves the requested cohorts plus the player directory, normalizes, resolves identity and writes the snapshot into a checkout of `market-data`;
2. `ffdraft capture-status` retrieves and retains the Sleeper current-status capture;
3. `ffdraft validate-market-history` re-hashes the whole store **before** anything is pushed, so a corrupt write is caught locally rather than committed;
4. only then does the job commit and push.

The job is serialized against itself with a `concurrency` group: two concurrent captures could race on the same push, and an append-only store would rather not find out.

**Idempotency is the retry story.** A re-run that produces identical bytes is a no-op, so a failed push can simply be re-run. A re-run that produces *different* bytes for an existing timestamp fails closed — take a new snapshot instead.

### 5.2 Phase-5 commands

```bash
# network, runner only
uv run ffdraft snapshot-market --season 2026 --cohorts study --store ../market-data
uv run ffdraft capture-status  --season 2026 --store ../market-data

# offline, reproducible from retained bytes
uv run ffdraft validate-market-history ../market-data --season 2026   # market and status
uv run ffdraft measure-market-cohorts --store ../market-data     # writes docs/market-cohorts/
uv run ffdraft build-current --store ../market-data              # tiers + player_status
uv run ffdraft build-arbitrage --store ../market-data            # A0 board, merges metadata
uv run ffdraft arbitrage-card
```

`--cohorts` takes `production` (the three cohorts a routine capture retains), `study` (every candidate, for a cohort measurement) or an explicit id list. `build-current --store` reads the retained Sleeper capture instead of calling Sleeper live, which is what makes the status artifact reproducible offline; without it the artifact degrades to nflverse-only and the Tier board is unaffected.

**"Offline" here means network-independent replay from the Git-backed store, not local-only state.** `../market-data` is a clone of this repository's `market-data` branch, sitting beside the working tree; see `docs/ARCHITECTURE.md` section 6.3 for the topology and the exact clone command. Everything in the second block above reads retained bytes and calls no vendor.

### 5.3 The private retained-data repository (Phase 7, ADR-049)

The store lives in **`jeisey/jeisey-tiers-market-data`**, a private repository whose default and only branch is `market-data`. The application repository is public; a public repository has no private branch, so the store could not stay where ADR-038 put it.

The address is written down **once**, in `config/source-registry.yaml`:

```yaml
decisions:
  market_history_repository: jeisey/jeisey-tiers-market-data
  market_history_repository_visibility: private
  market_history_repository_secret_name: MARKET_DATA_REPO_TOKEN
  market_history_branch: market-data
```

`.github/actions/market-data-store` reads those keys and checks the store out. No workflow contains the literal, and `tests/unit/test_workflows.py` fails if one grows it — so moving the store again is one edit to one file.

**The credential.** A workflow in the public repository cannot use its ordinary `GITHUB_TOKEN` to write another repository's contents. `MARKET_DATA_REPO_TOKEN` is a fine-grained personal access token scoped to `jeisey/jeisey-tiers-market-data` **alone**, with Contents: Read and write, held as a repository secret on `jeisey/jeisey-tiers`.

To provision or rotate it:

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. Resource owner `jeisey`; **Only select repositories** → `jeisey/jeisey-tiers-market-data` and nothing else.
3. Repository permissions → **Contents: Read and write**. Nothing else — not Actions, not Metadata beyond the mandatory read, not Workflows.
4. Set an expiry and put the renewal in the calendar; see the failure mode below.
5. `jeisey/jeisey-tiers` → Settings → Secrets and variables → Actions → New repository secret, named `MARKET_DATA_REPO_TOKEN`.

Three rules bound its use, and all three are enforced rather than remembered:

- it is passed to `actions/checkout` through its `token:` input and **never** interpolated into a URL, a log line or a shell variable — the pre-Phase-7 workflow built `https://x-access-token:${GH_TOKEN}@github.com/...` in a shell block, and that construction is gone;
- read-only jobs check out with `persist-credentials: false`, so no credential survives into a frontend build or a Pages artifact;
- `ci.yml` never references it, so a pull request from a fork cannot reach the store.

**When the token expires**, the daily refresh fails at its first job with a message naming the secret, the deploy job is never reached, and the previously deployed site stays live and stale. That is the intended failure: loud, early, and non-destructive.

**What a contributor without access can still do:** everything except rebuild the production board. The whole Python suite, the whole frontend suite, the end-to-end run and the fixture pipeline are network-free and store-free by construction.

### 5.4 Phase-6 commands

```bash
# the whole frontend gate, all offline
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build                                    # root path
VITE_BASE_PATH=/jeisey-tiers/ npm run build      # project Pages path
npm run e2e                                      # builds five sites, then 61 Playwright tests
npm run e2e:browsers                             # the three-engine smoke — RUNNER ONLY, see below

# review aids
npm run e2e:build                                # just the sites + fixture artifacts
npm run e2e:screens -- docs/visual-qa/<date>     # the eighteen visual-QA screens
npm run verify:board                             # rendered board vs artifact bytes, live build
node web/tests/e2e/measure-performance.mjs       # timings on a production-scale synthetic board
```

**`npm run e2e:browsers` cannot run in a development sandbox behind an egress policy.** It
needs Firefox and WebKit, and Playwright downloads those from `cdn.playwright.dev`, which the
sandbox blocks — Chromium is preinstalled there, the other two are not and cannot be fetched.
`ci.yml`'s `browsers` job is where the three-engine smoke actually runs, the same shape as the
source probes under ADR-009. `npm run e2e` deliberately excludes it so the local gate is
green-or-red on things the local machine can actually decide (ADR-059).

`npm run e2e` produces its own builds through `globalSetup`, so it needs no prior `npm run build`; `E2E_SKIP_BUILD=1` reuses what is on disk while iterating on a spec. The end-to-end server is `web/tests/e2e/static-server.mjs`, which maps URLs to files under `web/dist*` and serves nothing else — every spec additionally fails on a request that leaves localhost.

`npm run verify:board` is the one command that needs the **real** generated artifacts rather than fixtures: build the site with `web/public/data/` populated and it serves the build itself, then cross-checks rendered tier rows, chart-mark labels, arbitrage rows and injury badges against the artifact bytes. That is the check behind the Phase-6 exit gate's "chart values agree with the table" clause, and `daily-refresh.yml` runs it on every production build before uploading the Pages artifact.

Phase 7 made it self-contained — Phase 6 needed a server started by hand — and gave it three options:

```bash
npm run verify:board                                    # serve web/dist at /, check it
npm run verify:board -- --base-path /jeisey-tiers/      # what the production build runs
npm run verify:board -- --url https://jeisey.github.io/jeisey-tiers --data web/public/data
```

With `--url` no server is started and the check runs against a site somebody else is serving. That is the **deployed** production smoke test: the page comes from GitHub Pages, the numbers it is compared against come from the artifacts the build produced.

Two environment variables matter in a sandbox: `PLAYWRIGHT_CHROMIUM_EXECUTABLE` points at a preinstalled Chromium when the image's build number does not match the pinned Playwright release, and `E2E_PORT` moves the static server.

## 6. Least-privilege permissions

Suggested separation:

### CI

`contents: read`

### Pages build/deploy

Use official documented permissions, typically:

- `contents: read`
- `pages: write`
- `id-token: write`

plus Pages environment.

### Data snapshot writer

`contents: write` only in the job that actually commits to data branch; avoid giving the whole workflow broad write access if job separation can prevent it.

> **Phase-7 implementation.** Every workflow declares `permissions: contents: read` at the top. What each job actually holds:
>
> | workflow | job | permissions |
> |---|---|---|
> | `ci.yml` | all three | `contents: read` |
> | `daily-refresh.yml` | `capture` | `contents: read` |
> | `daily-refresh.yml` | `build` | `contents: read` |
> | `daily-refresh.yml` | `deploy` | `contents: read`, `pages: write`, `id-token: write`, environment `github-pages` |
> | `daily-refresh.yml` | `report` | `contents: read` |
> | `retrain.yml` | both | `contents: read` |
> | `market-capture.yml` | `capture` | `contents: read` |
>
> **The capture jobs got narrower, not wider.** They used to need `contents: write` on this repository to push to a branch here; they now need `contents: read` here plus a token scoped to one other repository. Separating the data from the code made this repository's own permissions strictly smaller.
>
> `actions/configure-pages` lives in the deploy job rather than the build job for the same reason: it is the only step that needs a `pages:` scope for its own sake, and putting it upstream would have meant widening the build job for an output nothing consumes.
>
> The whole table is asserted by `tests/unit/test_workflows.py`, including the environment name and the absence of any `pages:` scope from `ci.yml` and `retrain.yml`.

## 7. Concurrency

Daily production workflow should use a concurrency group so two refreshes cannot race and deploy out of order.

Recommended semantics:

- group: production refresh
- cancel older in-progress run when a newer manual/scheduled run supersedes it **only if** cancellation cannot interrupt an irreversible snapshot write; order steps accordingly.

Pages deploy should never publish an older build after a newer one.

> **Phase-7 implementation (ADR-050).** Two groups, neither of which cancels.
>
> - Workflow level: `group: production-refresh`, `cancel-in-progress: false`. Cancelling is the dangerous option, because a cancellation between `git commit` and `git push` in the capture job drops a validated snapshot on the floor. Queueing also *supplies* the ordering this section asks for: a superseding run waits for the run it supersedes, so it deploys after it rather than racing it, and an older build can never land on top of a newer one.
> - Deploy job: `group: pages`, `cancel-in-progress: false`, so the publish serializes against any other Pages publisher.
>
> The two groups cannot deadlock. The workflow-level group is held before any job starts, so a queued run has not begun and therefore cannot be holding `pages`.
>
> `market-capture.yml` keeps its own `market-capture` group, also without cancellation, so an out-of-band capture cannot race a scheduled one on the same append.
>
> One consequence worth stating plainly: if a refresh is queued behind a long one, it starts late. That is the trade this project wants — a late deploy is recoverable, a lost capture is not.

## 8. Last-known-good behavior

GitHub Pages deployment occurs only after validation and frontend build success. A failed workflow simply performs no Pages deployment, leaving previous deployment live.

Do not have an early step delete/replace production branch contents before validation.

> **Phase-7 implementation (ADR-050).** Last-known-good is the job graph, not a set of `if:` guards. `deploy` `needs: build`, `build` `needs: capture`, and the deploy job's only content is `actions/configure-pages` and `actions/deploy-pages`. A failed gate anywhere leaves the deploy job unreached, and nothing anywhere clears, empties or replaces the live site — so "no deploy" and "the previous site is still serving" are the same event rather than two things that have to agree.
>
> `actions/upload-pages-artifact` is the **last** step of the build job, after artifact validation, the frontend build, `verify:board` and the artifact-boundary assertion. There is no window in which a build that failed a gate exists as a deployable artifact.
>
> **The forced-failure proof.** `workflow_dispatch` carries `force_validation_failure`, default false. It is unreachable from the schedule — `inputs` is empty on a scheduled run, and the step also asserts `github.event_name == 'workflow_dispatch'` — and `tests/unit/test_workflows.py` asserts that guard.
>
> When set, the run does **not** call `exit 1`. It corrupts a generated artifact so that VORP quantiles are no longer non-decreasing, then runs the ordinary `validate-artifacts` gate. What rejects the build is `artifact.non_monotonic_quantiles`, a production critical check from `docs/ARCHITECTURE.md` section 12 — not a switch added for the test. A proof that only shows `exit 1` works would prove nothing about the gate.
>
> Note what the proof run deliberately does *not* undo: the capture job runs first and its snapshot is committed to the private store. That is correct. A retained snapshot records what was observed; a failed build downstream of it is a reason not to publish a page, not a reason to forget the day's prices.
>
> The recorded proof and its run evidence are in `docs/PHASE7_DEPLOYMENT.md`.

## 9. Freshness thresholds

Configurable per source.

Initial approach:

- current roster/depth/source expected daily: warn after expected interval, critical after materially stale threshold (e.g. > 48h during draft season, to be tuned in Phase 0);
- market ADP: warning/critical thresholds aligned to source cadence;
- historical sources: freshness less important; validate version/completeness.

Thresholds belong in config, not code.

## 10. Workflow summary

Every daily run publishes a summary like:

```text
Build ID / Git SHA
Season / presets generated
Intrinsic model version
Arbitrage mode/version
Source status:
  nflverse players  PASS  as-of ... records ...
  depth charts      PASS  as-of ...
  Sleeper           WARN  ...
  MFL ADP           PASS  ...
Identity coverage
Tier record counts
Arbitrage record counts
Quality warnings
Pages deployment URL/status
```

Never put secrets/raw tokens in summaries/logs.

> **Phase-7 implementation.** `scripts/workflow_summary.py` renders it, so the numbers come from JSON that already exists and a mistake is a red test rather than a malformed summary. The script reads only generated artifacts and the retained store's own manifests; the workflow passes the handful of run-scoped facts it knows (trigger, run URL, code SHA, store commit before and after, whether the store was appended, deploy result, Pages URL) through `--fact`. It never reads an environment variable holding a secret.
>
> A daily refresh summary carries: build id, generated-at, season, intrinsic model version, methodology version, arbitrage mode and method version; a per-source table with status, retrieval time, source-as-of and record count; the market snapshot key, cohort rule version and trend availability; **the cohort selected per preset with its failed clauses**; the confidence distribution and median per-player draft sample; per-cohort identity coverage read from the capture's own manifest; record counts for all four artifacts and the player-status match count; and the quality gate with its warnings in a collapsed block.
>
> When a gate before the artifact build failed, the summary says so in the shape that matters — *nothing was generated, so nothing could be deployed, and the previously deployed site is still live* — rather than rendering an empty table.

## 11. Failure triage

### Source HTTP/schema failure

- mark source failure;
- save diagnostic metadata/log excerpt;
- no production deploy if critical;
- do not auto-edit adapter blindly in the workflow.

### Model artifact mismatch

Critical. Stop.

### Model/current feature drift

If required feature absent or incompatible, stop. Do not silently fill with zero unless that behavior is explicitly trained/tested.

### Optional source failure

Continue only through documented fallback path.

### Frontend build failure

No deploy; previous site remains.

## 12. Scheduled workflow inactivity caveat

GitHub documents that scheduled workflows in public repositories can be automatically disabled after long repository inactivity. Market snapshot commits may naturally keep activity present, but do not rely on that as a guarantee. Document how to re-enable schedules and include a release/offseason checklist.

> **Phase-7 note.** The hazard got slightly worse when the store moved (ADR-049): the daily capture now commits to the *private data* repository, so it no longer creates activity in the public application repository at all. Nothing about a run of `daily-refresh.yml` pushes a commit here.
>
> **How to re-enable a disabled schedule:** Actions → the workflow → the banner GitHub shows on a disabled scheduled workflow → *Enable workflow*. Then run it once with `workflow_dispatch` to confirm it still works before trusting the next scheduled fire.
>
> **Offseason checklist**, once the draft season ends:
>
> 1. decide whether a daily capture is still worth it — ADR-010 wants three draft seasons of snapshots, and the off-season aggregate barely moves;
> 2. if reducing cadence, edit the `cron` rather than disabling the workflow, so the run history stays continuous;
> 3. check `MARKET_DATA_REPO_TOKEN`'s expiry before the next preseason (section 5.3);
> 4. re-run `scripts/source_probe.py` before the next launch — source-schema drift is detected, not prevented.

## 13. Branch protection recommendation

Default branch:

- require CI status checks before manual merges where practical;
- no direct workflow bot writes except explicitly designed data/model promotion process;
- protect production model changes from accidental automatic overwrite.

## 14. Dependency maintenance

Enable Dependabot or equivalent for Python/GitHub Actions/npm if it does not create excessive noise. Pin official GitHub Actions by major version or commit according to current security best practice; use trusted official actions for Pages.

## 15. Observability without external services

Use:

- GitHub Actions run history
- step summaries
- uploaded small diagnostic artifacts/model reports
- public `build_metadata.json`
- optional automatically opened GitHub issue after repeated scheduled failures only if implemented carefully to avoid issue spam

Do not add paid observability for V1.


---

## Phase-2 commands

The historical modelling dataset is built and checked with three commands. Only the first touches the network.

```bash
# Build the dataset for target seasons 2014 through the last completed season, and write
# data/historical/ (tables, quality report, manifest, feature dictionary). Takes a few
# minutes of nflverse downloads plus the leakage proof, which rebuilds each season with its
# own statistics deleted.
uv run ffdraft build-historical --last-season 2025 --git-sha "$(git rev-parse --short HEAD)"

# Re-run the table-level leakage and semantic audits over a dataset already on disk, and
# check it still matches the content hashes in its manifest. No network.
uv run ffdraft validate-historical data/historical

# Print the feature dictionary. docs/FEATURE_DICTIONARY.md is this output; a test asserts
# the committed copy matches the code.
uv run ffdraft feature-dictionary
```

Useful flags:

- `--first-season` defaults to 2014, the first season whose *previous* season has snap counts.
- `--league-preset` is repeatable and defaults to the launch presets; each extra preset multiplies the VORP label count.
- `--no-write` builds and validates without writing anything, for checking a change.
- `--skip-independence-check` skips the rebuild-with-target-season-deleted leakage proof. It roughly triples build time, so the flag exists for iteration — never for a dataset anything downstream will use.

**Nothing is written when the gate fails.** As with the public artifacts (section 8), a failed critical check leaves whatever was there before intact, so a bad run cannot replace a good dataset with a broken one.

`scripts/capture_source_schemas.py` re-records the upstream schemas the Phase-2 adapters are written against. Run it from an environment with egress to the nflverse release hosts (ADR-009) and review the diff before committing: a changed fixture is a changed upstream contract.

CI does not build the historical dataset — it needs live vendor access, which `ci.yml` deliberately avoids. What CI does run is the full network-free suite, including the fixture-driven historical mini-pipeline and every leakage audit.

---

## Phase-3 commands

The evaluation harness runs entirely offline against the dataset `build-historical` wrote.

```bash
# Rolling-origin development experiment over both training windows, writing
# docs/experiments/phase3-intrinsic-baselines/{experiment.json,experiment.md}.
uv run ffdraft evaluate-intrinsic --git-sha "$(git rev-parse --short HEAD)"
```

Useful flags:

- `--window` is repeatable and defaults to both policies (`W1_all_history`, `W2_modern_era`).
- `--model` is repeatable and defaults to `B0 B1 Q1`.
- `--validation-season` is repeatable and defaults to 2020-2024. Passing a sealed season is refused, not filtered.
- `--no-diagnostic-folds` skips the W1-only 2017-2019 folds.
- `--bootstrap-replicates` defaults to 1000; `--seed` defaults to 20260819. Both are recorded in the report.
- `--write-predictions` additionally writes row-level predictions as Parquet for offline inspection. They are gitignored.

**The final holdout is sealed.** Season 2025 is dropped from the modelling frame at load time, so an ordinary run does not have the rows. Evaluating it requires all three of `--final-eval`, `--confirm-final-eval RELEASE-FINAL-HOLDOUT-2025` and `--final-eval-reason "<why>"`, plus a single `--window`; anything less exits 2 with a refusal. Running it consumes the holdout, and the command says so. Phase 3 never ran it.

Exit status is the usual contract: 0 when the gate passes, 1 when a critical check fails — including "no candidate passed the frozen promotion gate", which is a red build rather than a quiet note.

CI does not run the experiment: it needs the historical dataset, which needs live vendor access. What CI runs is `tests/model/`, which drives the same folds, models, metrics, bootstrap and gate over a synthetic table.

---

## Phase-4 commands

Phase 4 runs in four stages, in this order. Each writes a committed experiment report, and
each stage's decision is made by a rule frozen in `ffdraft.modeling.rules` before its
evidence existed (ADR-030). Every development command runs offline against the dataset
`build-historical` wrote; none of them can reach the sealed season.

```bash
# Stage B — the predictive distribution: calibration, horizon sensitivity, Candidate A vs B.
# Writes docs/experiments/phase4-intrinsic-distribution/ and the promoted architecture's
# out-of-fold predictions to data/phase4/ for stage C. ~25 minutes.
uv run ffdraft evaluate-distribution --git-sha "$(git rev-parse --short HEAD)"

# Stage C — the Monte Carlo draw count and the fair-ranking statistic.
uv run ffdraft evaluate-simulation --git-sha "$(git rev-parse --short HEAD)"

# Stage C — the tier penalty and the bootstrap stability gate. Reads the draw count and
# ranking statistic from the simulation report unless --draws/--statistic override them.
uv run ffdraft evaluate-tiers --git-sha "$(git rev-parse --short HEAD)"
```

Then the freeze checkpoint (`ffdraft.modeling.frozen`) is committed, and **only then**:

```bash
# Stage E — the sealed final holdout, run exactly once against the frozen architecture.
uv run ffdraft evaluate-intrinsic \
  --final-eval \
  --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025 \
  --final-eval-reason "<why>" \
  --window W1_all_history \
  --model B0 --model CB \
  --out docs/experiments/phase4-final-holdout
```

After the holdout passes:

```bash
# Train the frozen architecture on 2014-2025 and write models/production/<version>/.
# The seal still has to be opened deliberately, with the same token.
uv run ffdraft train-production \
  --allow-unsealed \
  --confirm-final-eval RELEASE-FINAL-HOLDOUT-2025 \
  --final-eval-reason "<why>" \
  --git-sha "$(git rev-parse --short HEAD)"

# Build the current season's board and write the public artifacts.
uv run ffdraft build-current --git-sha "$(git rev-parse --short HEAD)"
uv run ffdraft validate-artifacts web/public/data

# Regenerate the model card and the tier-method report from the committed reports.
uv run ffdraft model-card --git-sha "$(git rev-parse --short HEAD)"
```

Three operational notes.

**`build-current`'s information cutoff is the build timestamp**, not the target season's
draft anchor, and the two are recorded separately in the quality report. A build running in
August 2026 stands before the 2026 anchor, so pretending that anchor had occurred would be
claiming knowledge of roster moves that have not happened. The cutoff is
`min(as_of, anchor)`, which also means a current row can never see more than a training row
would have. The rule version travels on the row: `current_build_as_of_v1` when the build
timestamp binds, the ADR-021 rule when the anchor does.

**Current roster status is metadata, never a model input.** A player the current roster
records as retired is excluded from the board; every other status - reserve, cut, exempt, or
absent from the roster entirely - annotates the row and leaves it in place, because absence
from a roster in August is not evidence of absence from the league in September.

**Model/feature compatibility fails closed.** `build-current` refuses to run when the model
artifact's feature-set hash or feature-schema hash disagrees with the build's, rather than
serving a model on a contract it was never validated against.

CI runs none of these: they need the historical dataset and live vendor access. What CI runs
is `tests/model/`, `tests/unit/` and `tests/integration/`, which drive the same rules,
sampler, allocation, segmentation, artifact writers and seal over synthetic and fixture data.

---

## Phase-7 commands

Deployment has no new *data* commands. What Phase 7 added is a way to run the deployed
product's own checks from a terminal, and two gate scripts the workflows call.

```bash
# The retained store, now a separate private repository (ADR-049).
git clone https://github.com/jeisey/jeisey-tiers-market-data ../market-data
uv run ffdraft validate-market-history ../market-data --season 2026

# The production build, exactly as daily-refresh.yml runs it.
uv run ffdraft build-current          --store ../market-data --git-sha "$(git rev-parse --short HEAD)"
uv run ffdraft measure-market-cohorts --store ../market-data --out /tmp/market-cohorts
uv run ffdraft build-arbitrage        --store ../market-data --selection /tmp/market-cohorts/cohorts.json
uv run python -m ffdraft.cli validate-artifacts web/public/data

VITE_BASE_PATH=/jeisey-tiers/ npm run build
npm run verify:board -- --base-path /jeisey-tiers/

# The deployed site, against the artifacts the build produced.
npm run verify:board -- --url https://jeisey.github.io/jeisey-tiers --data web/public/data

# Would a retrain be legitimate right now? Exits 0 either way.
uv run python scripts/retrain_gate.py

# Render a refresh summary locally, from artifacts already on disk.
uv run python scripts/workflow_summary.py --artifacts web/public/data --store ../market-data
```

`build-current`, `measure-market-cohorts` and `build-arbitrage` need retained bytes and, for
the first, live nflverse access. Everything else in the list is offline.
