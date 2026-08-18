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

### 2.2 `daily-refresh.yml`

Triggers:

- `workflow_dispatch`
- daily schedule

Preferred initial schedule: **07:17 America/New_York**, subject to Phase-0 source timing. The non-round minute is deliberate: GitHub documents that scheduled workflows can be delayed during high load at the start of an hour.

GitHub now supports timezone-aware schedule syntax; use the current documented syntax rather than manually encoding DST offsets.

Jobs/steps:

1. checkout source SHA/default branch;
2. install locked Python dependencies;
3. fetch current source data with cache;
4. normalize/validate;
5. identity resolution;
6. current feature build;
7. load production intrinsic model artifacts;
8. inference + simulation + VORP + tiers;
9. fetch/validate market data;
10. compute arbitrage;
11. persist market snapshot only after market validation;
12. serialize JSON/CSV/metadata;
13. validate JSON Schema + semantic checks;
14. build frontend using generated artifacts;
15. upload Pages artifact;
16. deploy Pages;
17. write rich GitHub Actions step summary.

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

> **Phase-0 observation (2026-08-17):** `jeisey/jeisey-tiers` is currently a **private** repository, so the free-runner and Pages assumptions above do not yet hold. This does not block Phase 0, but it must be resolved before Phase 7: either make the repository public, or accept the plan requirements for Actions minutes and Pages on a private repository. Recorded as an open question in `SESSION_STATE.md`.

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

## 7. Concurrency

Daily production workflow should use a concurrency group so two refreshes cannot race and deploy out of order.

Recommended semantics:

- group: production refresh
- cancel older in-progress run when a newer manual/scheduled run supersedes it **only if** cancellation cannot interrupt an irreversible snapshot write; order steps accordingly.

Pages deploy should never publish an older build after a newer one.

## 8. Last-known-good behavior

GitHub Pages deployment occurs only after validation and frontend build success. A failed workflow simply performs no Pages deployment, leaving previous deployment live.

Do not have an early step delete/replace production branch contents before validation.

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
