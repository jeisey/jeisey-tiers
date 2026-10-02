# Security review — 2026-10-02

Supersedes `docs/PHASE8_SECURITY_REVIEW.md` (kept as history). Three questions, asked of the
whole repository: can a credential reach somewhere it should not, can a private or
non-redistributable payload reach somewhere public, and is anything the build depends on known
to be vulnerable. No secret value, authenticated URL or private record appears below.

| | |
|---|---|
| Date | 2026-10-02 |
| Commit reviewed | `7e646c7` (branch `claude/nifty-cori-2ielym`), plus the uncommitted working tree at review time |
| Scope | tracked tree; full public Git history; `.github/workflows/*.yml` (12) and `.github/actions/market-data-store`; `uv.lock`, `package-lock.json`; `vite.config.ts` and the production frontend build; `tests/fixtures/**`, `docs/source-probes/**`, `docs/experiments/**`, `docs/visual-qa/**` (file inventory only); `src/ffdraft` writers of the shadow record, prospective verdict, store manifests and capture logs; `scripts/workflow_summary.py`, `scripts/prospective_report.py`, `scripts/probe_fantasypros.py` |

## Tools and commands

| tool | version | command (paths abbreviated) | result |
|---|---|---|---|
| gitleaks | 8.28.0 (release sha256 verified) | `gitleaks git --redact .` (local clone) | 1 finding, false positive (prose "`previous_day1`" in `src/ffdraft/weekly/frozen_v2.py:193`) |
| gitleaks | 8.28.0 | `gitleaks git --redact --log-opts=--all` on a fresh bare clone of the public repo **plus all 56 `refs/pull/*/head`** (247 commits, first 2026-08-17) | same single false positive |
| gitleaks | 8.28.0 | `gitleaks dir --redact .` and on both frontend builds | tree: the same false positive (and its `.pyc`); builds: none |
| detect-secrets | 1.5.0 (`uvx`) | `detect-secrets scan` excluding lockfiles/`.pyc`/served fixtures | 2,188 hex-entropy hits, all sha256 content hashes in metadata/evidence; 7 keyword hits, all environment-variable **names** or the test placeholder password in `tests/unit/test_config.py` |
| grep | — | `git log --all -p` for `ghp_`, `github_pat_`, `gho_`, `ghs_`, `x-access-token:` | 0 tokens; 2 hits are the documentation/test strings that forbid the construction |
| pip-audit | 2.9.0 (`uvx`, PyPI/OSV reachable) | `uv export --frozen --no-hashes --no-emit-project > req.txt; pip-audit -r req.txt --no-deps --disable-pip` | before: 3 advisories in `urllib3 2.7.0`; after SR-03: **no known vulnerabilities** (45 packages) |
| pip-audit | 2.9.0 | same, on `uv==0.8.17` (the workflow toolchain pin) | 4 advisories (SR-06) |
| npm audit | npm 10.9.4 (registry reachable) | `npm audit --omit=dev`; `npm audit` | production: **0**; full tree: 5 (3 high, 2 moderate), all dev-only (SR-07) |
| actionlint | 1.7.7 (release sha256 verified), `-shellcheck=` | on all workflows, before and after the fixes | identical 7 findings before/after, all the `timezone:` schedule key the linter predates; no new finding. shellcheck itself was not available |
| vite | from `package-lock.json` | `npx vite build --outDir <scratch>/dist-root`; `VITE_BASE_PATH=/jeisey-tiers/ npx vite build --outDir <scratch>/dist-pages` (`npm ci` not re-run; existing `node_modules`) | 16 files each, 0 source maps, asset URLs under `/jeisey-tiers/`; no `VITE_*` name, store name, token, local path or vendor API host other than the MFL attribution link |
| GitHub MCP (read-only, `jeisey/jeisey-tiers` only) | — | repository, branches, latest `daily-refresh` run and its artifacts | repo **public**; branches `main` and one feature branch, `main` reports `protected: false`; no `market-data` branch; run 37028336289 artifacts: `refresh-build-*` (10.1 MB, 14 d), `weekly-shadow-*` (177 KB, 1 d), `github-pages` |
| pytest / ruff | repo pins | see "Validation" | pass |

**Limitations.** The working clone is shallow (183 of 247 commits); the full public history and
PR refs were therefore scanned from a separate bare clone, so history coverage is complete for
what GitHub still serves. Deleted branches GitHub no longer serves, workflow **logs**, and
artifact **contents** were not downloaded. The private store repository was not accessed.

## Findings

| ID | Location | Severity | Evidence | Remediation | Status |
|---|---|---|---|---|---|
| SR-01 | repository-level secrets consumed by `daily-refresh.yml` (`capture`, `build`, `retain-shadow`), `market-capture.yml` (`capture`), `weekly-v2-prospective.yml` (`look`), `source-probe-phase10.yml` (`probe`) | **Medium** | Repository secrets are readable by a workflow run on **any** branch. `market-capture.yml`, `source-probe-phase10.yml` and `phase10-linkage.yml` also trigger on `push` to `claude/**`, and `workflow_dispatch` runs the workflow file of the chosen ref. Anyone (or any coding-agent session) able to push a branch can therefore run edited workflow code holding `MARKET_DATA_REPO_TOKEN`. Forks cannot (no `pull_request_target`/`workflow_run`; `ci.yml` names no secret). `main` reports `protected: false` (the API flag may not reflect rulesets). | Owner: create an environment (e.g. `market-data`) restricted to `main`, move `MARKET_DATA_REPO_TOKEN` (and the FantasyPros/MFL secrets) **into** it, delete the repository-level copies, then add `environment: market-data` to the five jobs above (a one-line change per job; the `claude/**` push captures would then need dispatch from `main`). Protect `main` (PR + review). Confirm the PAT is fine-grained, single-repo, Contents-only, with an expiry. | owner-action |
| SR-02 | 10 workflows, e.g. `daily-refresh.yml` "Plan the capture" (store token, persisted), `market-capture.yml` "Read the capture request", `phase10-linkage.yml` (`contents: write`), `release.yml`, `source-probe*.yml`, `retrain.yml`, `live-smoke.yml` | Low | `${{ inputs.* }}`, `${{ github.event.schedule }}` and `${{ github.ref_name }}` were pasted into `run:` scripts (script injection); `season`/`cohorts` then became step outputs expanded inline by later steps of credentialed jobs, and could inject extra `GITHUB_OUTPUT` lines via a newline. Reachable only with write access (dispatch or push), so defence in depth. | Every such value now reaches the shell through `env:`; `season` must match `^[0-9]{4}$` and `cohorts` `^[A-Za-z0-9_,. -]+$` before they become outputs (`daily-refresh`, `market-capture`, `phase10-linkage`); `git push` uses `$GITHUB_REF_NAME`. | **fixed** |
| SR-03 | `uv.lock`: `urllib3 2.7.0` | Low | PYSEC-2026-4175/4176/4177 (GHSA-8988-9cw3-xx77, -gh4c-6fx4-qh6g, -vxq7-64xx-v4gw). `requests` reads every body through urllib3's streaming decoder, so a malicious or compromised upstream (MFL, Sleeper, nflverse, NWS, Open-Meteo, FFC) could hang or exhaust a capture job; the proxy-TLS issue is not used. Effect is a failed job (fail-safe), not data exposure. | `uv lock --upgrade-package urllib3==2.8.0` — a 3-line lockfile change, nothing else moved. | **fixed** |
| SR-04 | `daily-refresh.yml` `build` → `retain-shadow` handoff (`weekly-shadow-<run_id>` artifact) | Low | On a public repository a workflow artifact is downloadable by any signed-in GitHub user. The "private" weekly shadow record is exposed this way for its 1-day retention (observed: 177,546 B in run 37028336289). Content verified in `src/ffdraft/weekly/shadow.py`: v1/v2 quantiles, ids, team/opponent, kickoff, inputs derived from nflverse/NWS/Open-Meteo — no vendor market payload, no credential. | Accepted as low (all inputs are redistributable public data; v2 is frozen, so early visibility cannot bias it). If "private" must mean private, the build job would need its own store write, which is worse. Wording, not data, is the gap. | accepted |
| SR-05 | `phase10-linkage.yml` top-level `permissions` | Low | Only workflow whose default was `contents: write`. | Top level is now `contents: read`; the `link` job keeps its own `contents: write`. | **fixed** |
| SR-06 | `UV_VERSION: "0.8.17"` in all workflows | Low | 4 uv advisories (archive/RECORD/entry-point handling of a **malicious package**: PYSEC-2026-2295, GHSA-w476-p2h3-79g9, -pjjw-68hj-v9mw, -4gg8-gxpx-9rph). Mitigated: every install is `uv sync --frozen` against a hash-pinned lock of PyPI packages. | Bump the toolchain pin (≥ 0.11.15) in a separate, tested change. | accepted (owner/lead follow-up) |
| SR-07 | `package-lock.json` dev tree | Low | `brace-expansion`, `js-yaml`, `undici` (high), `vitest`/`@vitest/mocker` (moderate). None in the production bundle (`npm audit --omit=dev` = 0); they process repository-controlled inputs in lint/test. | `npm audit fix` (non-major) for the three highs in a separate change; vitest needs a major bump. | accepted |
| SR-08 | `daily-refresh.yml` `build` | Low | `npm ci` runs dev-dependency lifecycle scripts in a workspace that holds the private store checkout (no credential: `persist-credentials: "false"`). A compromised npm package could read retained vendor payloads. | Consider `npm ci --ignore-scripts` (verify esbuild/Playwright still work) or build the frontend in a job without the store checkout. | accepted |
| SR-09 | all `uses:` | Info | Only `actions/*` (official) at major tags plus the local action; no SHA pins. Matches `docs/SECURITY_LICENSE.md` section 4. | Optional SHA pinning with Dependabot for Actions. Now asserted: no third-party action without a deliberate test edit. | accepted |
| SR-10 | `docs/source-probes/2026-09-02/phase10-report.md` §2; `source-probe-phase10.yml` summary of `scripts/probe_fantasypros.py` | Info | The committed report quotes the first four RB **names** per scoring from FantasyPros ECR (no rank values); the probe prints one row's `rank` object to a public job log. FantasyPros is `benchmark_only`, `redistribution_permitted: false`. Excerpt-sized evidence. | Owner judgment; redact the name lists if strict non-redistribution is wanted. | accepted |
| SR-11 | `.gitignore` | Info | `.env` was not ignored (none tracked now or in history). | `.env` and `.env.*` added to `.gitignore` by the lead in the same pass. | **fixed** |

## Controls observed in tracked files (and now asserted)

- `MARKET_DATA_REPO_TOKEN` enters a job only as `with: token:` of `.github/actions/market-data-store`; the action passes it to `actions/checkout` and tests it for emptiness only. No authenticated remote URL is built.
- The credential persists into the store checkout only in jobs that push (`capture`, `retain-shadow`, market-capture `capture`, prospective `look`); `build` reads with `persist-credentials: "false"`.
- No workflow uses `pull_request_target`, `workflow_run` or comment/issue triggers; `ci.yml` (the only `pull_request` workflow) names no secret and never checks out the store. Credentialed jobs run only on `workflow_dispatch`, `schedule` or `push` and declare job-level permissions.
- Write scopes: `deploy` (`pages`, `id-token`), prospective `look` (`issues`), `release`, `phase10-linkage`, `source-probe`, `source-probe-weather` (`contents`) — nothing else.
- No secret in any workflow/job `env`, any `VITE_*` value, or a frontend-build step; Vite inlines only `VITE_*` and the code reads only `BASE_URL`.
- The Pages artifact is `web/dist` only, behind a boundary assertion; no `upload-artifact` path includes `market-data`, `.git` or the workspace root; the build record copies store **manifests** only and fails on any `*.gz`. Manifests carry provenance, hashes and counts (MFL cohorts, Sleeper status/behaviour counts, game-day `details` aggregates, the prospective verdict) — no rows.
- Step summaries and the prospective issue carry counts, outcomes and aggregate metrics only (`scripts/workflow_summary.py`, `scripts/prospective_report.py`, CLI capture output); the prospective artifact holds `status.json`, the verdict and `run.log` (the same JSON), not the judged rows, which go to the store.
- Credentialed jobs restore caches by exact key only (no `restore-keys`); PR-scoped caches are not readable from `main`.

## Changes made

- `.github/workflows/{daily-refresh,market-capture,phase10-linkage,release,retrain,live-smoke,source-probe,source-probe-ffc,source-probe-phase10,source-probe-weather}.yml` — SR-02, SR-05. No trigger, job graph, permission elevation, artifact or credential path changed.
- `uv.lock` — SR-03.
- `tests/unit/test_workflow_security.py` (new, 50 cases over every file in `.github/`) — triggers, read-only defaults, secret-job reachability and permissions, exact write allow-list, store-token entry and persistence, no untrusted context in `run:`, season validation, no secret in the frontend build, Pages path, artifact paths, official actions only, no prefix cache restore in credentialed jobs. Against the pre-fix workflows the injection test fails in all 10 files.
- `docs/OPERATIONS.md` section 6 (permissions table completed), `docs/SECURITY_LICENSE.md` section 3 (note), `docs/PHASE8_SECURITY_REVIEW.md` (marked historical).

## Validation

`uv run pytest tests/integration` — 127 passed, 4 deselected (live). `uv run pytest tests/unit/test_workflow_security.py tests/unit/test_workflows.py` — 85 passed. Integration + workflow + registry + summary tests together — 243 passed. `ruff check` / `ruff format --check` clean on the files changed here.

## Owner actions

1. SR-01: environment-scoped store token restricted to `main`, repository-level copy deleted, `environment:` added to the five consuming jobs; protect `main`; confirm the PAT's scope and expiry.
2. Confirm in Settings that `jeisey/jeisey-tiers-market-data` is private and that secret scanning with push protection is on for the public repository.
3. Decide SR-04 (accept the 24-hour artifact or reword "private"), SR-10 (redact the FantasyPros name lists) and schedule SR-06/SR-07.

## Not checked

Actual token scope, expiry and last use; whether the store repository is private; environment
protection rules, rulesets and Pages settings; contents of past workflow logs and artifacts;
Dependabot/secret-scanning alerts; screenshots under `docs/visual-qa/` beyond file inventory;
shellcheck of `run:` blocks.
