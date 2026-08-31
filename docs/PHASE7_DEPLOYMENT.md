# Phase-7 deployment record

The evidence behind Phase 7's exit gate, in the order the work had to happen. Decisions are
in `docs/DECISIONS.md` (ADR-049, ADR-050, ADR-051); how to operate any of it is in
`docs/OPERATIONS.md`. This file is the record of *what was actually done and observed*.

---

## 1. The retained-data migration (ADR-049)

### Why it had to happen first

ADR-038 put the append-only capture store on a `market-data` branch **of this repository**,
and said in its own consequences that this was safe *because the repository is private*. It
also named the revisit condition: "the repository becomes public and the retained vendor
payloads need a redistribution review first."

That condition fired, and workflow care could not satisfy it. **GitHub visibility is a
property of a repository, not of a branch.** Excluding `market-data` from the Pages artifact
and from release packaging — which the workflows do — would not have mattered at all,
because `git clone` hands any visitor every branch.

### What moved

| | before | after |
|---|---|---|
| repository | `jeisey/jeisey-tiers` (public as of Phase 7) | `jeisey/jeisey-tiers-market-data` (**private**) |
| branch | `market-data` | `market-data` (unchanged) |
| layout, manifests, hashes, append-only rules | ADR-038 | **unchanged** |

Keeping the branch name means no command, path, manifest or document that names it had to
change.

### Migration integrity

Verified before the old branch was deleted and before visibility changed.

```
file lists                40 files each, identical
byte-for-byte diff        diff -r --exclude=.git  →  no differences
tree content hash         1e60a55283e69c763a9dbc0bbb5fe4eb2e10cd476716fa2fbd5653c4822434f2
                          (identical on both sides)
```

```
$ uv run ffdraft validate-market-history <private checkout> --season 2026
market         : 2 snapshot(s), 35 file(s)
status         : 2 capture(s), 4 file(s)
retained history: pass
```

Contents: the two 2026 MFL snapshots (`2026-08-20T14-11-48Z`, `2026-08-20T14-38-44Z`) and the
two Sleeper status captures (`2026-08-20T14-12-17Z`, `2026-08-20T14-39-19Z`), with their
manifests, raw cohort payloads, the player directory and the normalized rows. `README.md` is
identical to `docs/market-data-branch-README.md`, which is where the workflow copied it from.

The private repository's own history contains **nothing but** `market/`, `status/` and that
README — checked across every commit, not just the tip.

### Credential design

`MARKET_DATA_REPO_TOKEN`: a fine-grained token scoped to `jeisey/jeisey-tiers-market-data`
alone, Contents: Read and write, nothing else. Provisioning and rotation steps are in
`docs/OPERATIONS.md` section 5.3.

Three bounds, each enforced by a test rather than by care
(`tests/unit/test_workflows.py`):

1. **It never reaches a shell.** Passed to `actions/checkout` through `token:`. The old
   workflow built `https://x-access-token:${GH_TOKEN}@github.com/...` in a shell block; that
   construction no longer exists anywhere in the repository.
2. **It does not survive into replaceable work.** Read-only jobs use
   `persist-credentials: false`, so nothing is in the workspace when the frontend builds or
   the Pages artifact is packaged.
3. **Untrusted code cannot ask for it.** `ci.yml` never references it and never checks the
   store out.

The address itself lives in exactly one place, `config/source-registry.yaml`
(`market_history_repository`), read by `.github/actions/market-data-store`. A test fails if
any workflow grows the literal.

**The capture job's privilege went down.** It used to need `contents: write` on this
repository. It now needs `contents: read` here plus a token scoped to one other repository.

---

## 2. Public-release audit

Run on the full tree and the full history reachable from `main`, **before** visibility
changed.

| check | scope | result |
|---|---|---|
| `.env`, `*.pem`, `*.key`, `*.p12`, `.netrc`, `id_rsa` | tracked tree | none (`src/ffdraft/secret.py` is the redaction module) |
| every path ever added on `main` | 517 paths, 56 commits | no `.env`, no key material, no raw payload, no `data/historical/`, no `web/public/data/` |
| credential-shaped literals — `ghp_`/`gho_`/`github_pat_`, `xox[baprs]-`, `AKIA…`, PEM private-key headers, `Authorization: Bearer/Basic …`, credentials in URLs | content of all 56 commits | **one match, not a secret** (see below) |
| local filesystem paths identifying a person | tracked tree | none |
| MFL secret *names* | tracked tree | present as names only, per the ADR-017 convention: `docs/DATA_SOURCES.md` records which variables exist, and `tests/unit/test_config.py` uses the obviously-synthetic `hunter2` to test redaction |
| retained payload objects reachable from `main` | `git rev-list origin/main --objects` | **0** |

**The one match.** Every historical copy of `.github/workflows/market-capture.yml` line 88
contained:

```
url="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
```

`${GH_TOKEN}` is a shell variable expanded by the runner at execution time. The file contains
no credential value, and no run logged the expanded URL. The Phase-7 rewrite removes the
construction entirely — the token now goes through `actions/checkout`'s `token:` input — so
the pattern is gone from the current tree as well as harmless in history.

**Verdict: pass.** No secret is present in the Git history that became public.

**On the deleted branch's objects.** The `market-data` branch shared no history with `main`;
zero of its objects are reachable from `main`, which was verified rather than assumed.
Deleting the branch while the repository was still private made those objects unreachable
before any unauthorised party could ever have had their SHAs, and an unreachable object is
not served to a clone. The order — migrate, verify, delete, *then* publish — is what makes
that true, and it is why the order is mandatory rather than tidy.

**No software licence was added.** Publicity is a visibility decision; a licence is a rights
decision belonging to the owner. See `docs/SECURITY_LICENSE.md` section 8.

---

## 3. The workflows

| workflow | trigger | what it may do |
|---|---|---|
| `ci.yml` | PR, push to `main`, dispatch | fixtures only. No vendor, no store, no `pages:` scope. |
| `daily-refresh.yml` | 07:17 America/New_York, dispatch | the whole production path: capture → build → deploy |
| `retrain.yml` | Sunday 06:43 America/New_York, dispatch | an evidence gate, and at most a candidate report |
| `market-capture.yml` | dispatch, or a bump to `.github/market-capture.request` | an out-of-band capture |
| `source-probe.yml` | dispatch | Phase-0 source verification; never gates a deploy |

The properties that matter are asserted by `tests/unit/test_workflows.py` rather than
reviewed: job dependencies, per-job permission maps, the `github-pages` environment, both
`cancel-in-progress: false` settings, the off-the-hour New York schedule, the dispatch-only
guard on the proof flag, the absence of any training command from the refresh, the absence
of Pages actions and pushes from the retrain, and the single-address rule for the store.

### Last-known-good, as a graph

```text
capture ──▶ build ──▶ deploy          report (needs all three, if: always())
```

`deploy` contains `actions/configure-pages` and `actions/deploy-pages` and nothing else, and
`actions/upload-pages-artifact` is the **last** step of `build`, after artifact validation,
the frontend build, `verify:board` and the artifact-boundary assertion. So there is no window
in which a build that failed a gate exists as a deployable artifact, and nothing anywhere
clears or replaces the live site before a new one is validated — which makes "a gate failed"
and "the previous site is still serving" the same event rather than two facts that have to
agree.

---

## 4. Forced-failure proof

The design: `workflow_dispatch` carries `force_validation_failure`, default false and
unreachable from the schedule. When true the run does **not** call `exit 1` — it corrupts a
generated artifact so VORP quantiles are no longer non-decreasing, then runs the ordinary
`validate-artifacts` gate. What rejects the build is `artifact.non_monotonic_quantiles`, a
production critical check from `docs/ARCHITECTURE.md` section 12.

A proof that only shows `exit 1` works would prove nothing about the gate. This one proves
the gate.

### The run: [32594602638](https://github.com/jeisey/jeisey-tiers/actions/runs/32594602638)

Dispatched with `force_validation_failure=true` and `skip_capture=true` — the latter so the
proof did not spend a fourth MyFantasyLeague player-database request in one day, which
ADR-017 asks us not to do.

```
Corrupt an artifact on purpose (forced-failure proof) ..... success
    ##[warning]Forced-failure proof run: deliberately violating quantile monotonicity.
    corrupted Bijan Robinson: p25_vorp -> 197.2161

Validate the public artifacts ............................ FAILURE
    validating web/public/data
      [critical] artifact.non_monotonic_quantiles (artifacts.tiers):
      vorp quantiles must be non-decreasing p10 -> p90 — observed:
      gsis:00-0038542 ([-27.4307, 197.2161, 117.6581, 172.2161, 218.1891]);
      expected: p10 <= p25 <= p50 <= p75 <= p90
    quality gate: fail (1 critical, 0 warning)
    ##[error]Process completed with exit code 1.

Read the build facts ..................................... skipped
Install locked frontend dependencies ..................... skipped
Build the site at the project Pages base path ............ skipped
Install Chromium ......................................... skipped
Verify the rendered board against the artifact bytes ..... skipped
Assert the Pages artifact boundary ....................... skipped
actions/upload-pages-artifact ............................ skipped
Deploy to GitHub Pages ................................... SKIPPED  (whole job)

Stage / upload the build record .......................... success  (if: always())
Refresh summary .......................................... success
```

**What this establishes.**

1. The build was rejected by `artifact.non_monotonic_quantiles` — a production critical check
   from `docs/ARCHITECTURE.md` section 12 — reading the real corrupted values back out. Not
   an `exit 1`.
2. **No Pages artifact was produced.** `upload-pages-artifact` never ran, so there was
   nothing deployable at any point, not merely nothing deployed.
3. **The deploy job was skipped entirely**, not failed. `needs: build` is what did that.
4. The diagnostic path still worked: the build record uploaded under `if: always()`, and the
   summary rendered with the deployment outcome restated in words.

**On the "previous production stayed live" half.** There is no deployed site yet — the
visibility gate in section 7 has not been passed — so this run left production exactly as it
found it: absent. The mechanism is proven; the observation on a live site is the owner's step
6 in section 7, and it is the same run with the same flag.

> **Since observed (2026-08-31).** The paragraph above is a Phase-7 statement and was true when
> written. The site went live on 2026-08-22 and has refreshed daily since. The half this run
> could not show was shown by run
> [33413279053](https://github.com/jeisey/jeisey-tiers/actions/runs/33413279053): a Phase-8
> branch build passed every gate, its deploy was refused by the Pages environment's branch
> policy, and the live site was left exactly as it was — a surviving site and a failed deploy
> in the same event, against real production rather than against an absence. See
> `docs/PHASE8_OPERATIONS_AUDIT.md` section 1.1.

### 4b. The retrain gate declined, in 23 seconds

Run [32594603959](https://github.com/jeisey/jeisey-tiers/actions/runs/32594603959), exit 0:

```json
{ "model_version": "intrinsic-cb-hurdle-v1",
  "training_seasons": "2014-2025",
  "artifact_feature_schema_hash": "c495ba3177dcb989",
  "code_feature_schema_hash":     "c495ba3177dcb989",
  "candidate_seasons": [
    { "season": 2026, "complete": false,
      "detail": "weekly statistics unavailable for 2026 (ConnectionError)" } ],
  "new_evidence": false,
  "should_retrain": false,
  "reasons": ["no completed season exists beyond the training corpus, so retraining could
               only reproduce the same artifact or consume unplayed/in-season outcomes"] }
```

The **candidate job was skipped**, no model was trained, nothing was promoted, and the run is
green — because "nothing to retrain" is a correct outcome, not a failure. Note the two
feature-schema hashes agreeing: the contract in code still matches the production artifact,
so there is no drift excuse for a retrain either.

---

## 5. Live production smoke verification

_Waits on section 7._ The command is already written and is the same one the build job runs,
pointed at a remote host instead of a local one:

```bash
npm run verify:board -- --url https://jeisey.github.io/jeisey-tiers --data web/public/data
```

It compares the **deployed page** against the artifact bytes the build produced: tier table
rows, chart-mark labels, arbitrage rows and injury badges. Beside it, the checks that need
eyes rather than a script: the Tier / Arbitrage / Data views render, CSV download works,
query links and reload survive under `/jeisey-tiers/`, the console is clean, and the network
panel shows requests to the Pages origin only — no vendor, no `api.github.com`, no
`jeisey-tiers-market-data`. The end-to-end suite already fails any request that leaves
localhost, so a vendor call in the browser would have been caught before deployment; the live
check is confirmation on the real origin rather than the first look.

---

## 6. Run evidence

### Runs so far

| run | workflow | trigger | outcome |
|---|---|---|---|
| [32590470088](https://github.com/jeisey/jeisey-tiers/actions/runs/32590470088) | `market-capture` | dispatch | **success** — first capture into the private repository; store head `ccd3ce1` → `fd661ae` |
| [32590972677](https://github.com/jeisey/jeisey-tiers/actions/runs/32590972677) | `ci` | pull request #8 | **success** — all three jobs green |
| [32591545618](https://github.com/jeisey/jeisey-tiers/actions/runs/32591545618) | `daily-refresh` | dispatch | **capture success, build failure, deploy skipped** — found a real defect, see below |
| [32593621903](https://github.com/jeisey/jeisey-tiers/actions/runs/32593621903) | `ci` | pull request #9 | **success** — the cohort fix |
| [32594084631](https://github.com/jeisey/jeisey-tiers/actions/runs/32594084631) | `daily-refresh` | dispatch | **capture success, build success, deploy failure at `configure-pages`** — the visibility gate, see section 7 |
| [32594602638](https://github.com/jeisey/jeisey-tiers/actions/runs/32594602638) | `daily-refresh` | dispatch, `force_validation_failure=true` | **the forced-failure proof** — section 4 |
| [32594603959](https://github.com/jeisey/jeisey-tiers/actions/runs/32594603959) | `retrain` | dispatch | **success, and it declined to retrain** — section 4b |

### What the first production refresh found

This run is the reason the phase is worth more than its diff. `capture` succeeded — a real
MFL and Sleeper capture, validated and pushed to the private store. `Build the current board`
succeeded in 3.5 minutes against that store, loading the committed production model. Then
`Select the market cohort` failed in one second:

```
ValueError: no cohort qualifies for HALF/10-team; a board cannot be priced by a cohort
that contradicts it (ADR-039/ADR-045)
```

**That is a genuine latent Phase-5 defect, and the production path had never been run before
today.** `PRODUCTION_COHORT_IDS` — the small cohort set a routine daily capture retains — was
frozen under `phase5_cohort_v1` as `("unfiltered", "ppr", "std")`. ADR-045 then made
keeper-free a *qualifying* condition, and none of those three excludes keepers. So a
production capture retained nothing the frozen rule could legally select. Phase 5 never met
this because every board it built came from a `study` capture, which retains all sixteen
candidates.

The rule was right and did its job: it refused to price a redraft board with dynasty rookie
drafts in it. The capture was wrong. The fix retains what the rule needs — see the ADR-045
amendment (2026-08-22) — and two new tests in `tests/unit/test_market_cohorts.py` assert that
every launch preset can be priced from `PRODUCTION_COHORT_IDS` alone, which is the check
whose absence let an un-priceable set ship.

### What the failure also demonstrated, for free

Nobody designed this run as a last-known-good test, and it is the better for that. An
**unanticipated** failure, three steps into a build:

| step | outcome |
|---|---|
| Build the current board | success |
| **Select the market cohort** | **failure** |
| Build the arbitrage board … Verify the rendered board … Assert the Pages artifact boundary | **skipped** |
| `actions/upload-pages-artifact` | **skipped** |
| **Deploy to GitHub Pages** | **skipped** |
| Stage / upload the build record | success (`if: always()`) |
| Refresh summary | success |

No Pages artifact was produced, the deploy job was never entered, and the retained capture
from the same run stayed committed in the private store — exactly the semantics
`docs/OPERATIONS.md` sections 1 and 8 ask for, arrived at by a real fault rather than a
rehearsed one.

It also confirmed two smaller things: `persist-credentials: false` left no git credential in
the build workspace (the post-job cleanup found an extraheader for the application checkout
and none for the store), and the build record staged 8 manifests with **zero** `.gz` files,
so no retained payload reached a world-readable artifact.

### The production build, green end to end

Run [32594084631](https://github.com/jeisey/jeisey-tiers/actions/runs/32594084631), on `main`
at `36b4e48`, after the cohort fix. `capture` and `build` both succeeded; only `deploy`
failed, and only at the visibility gate.

```
Capture and retain today's sources ......... success   (38s)
Build, validate and package the site ....... success   (4m43s)
  Build the current board .................. success   (3m44s)
  Select the market cohort ................. success
  Build the arbitrage board ................ success
  Corrupt an artifact on purpose ........... skipped   (flag false)
  Validate the public artifacts ............ success
  Build the site at /jeisey-tiers/ ......... success
  Verify the rendered board ................ success
  Assert the Pages artifact boundary ....... success
  upload-pages-artifact .................... success   (1,356,568 bytes)
Deploy to GitHub Pages ..................... FAILURE   at configure-pages
  deploy-pages ............................. skipped
Refresh summary ............................ success
```

**What the build produced**, from the run's own summary:

| | |
|---|---|
| Build id | `2026-intrinsic-cb-hurdle-v1-20260822T193501Z` |
| Model / methodology | `intrinsic-cb-hurdle-v1` / `phase4_intrinsic_v1` — **loaded, not retrained** |
| Snapshot | `2026-08-22T19-34-24Z`, cohort rule `phase5_cohort_v2` |
| Cohort selected, all nine preset blocks | `no-mock-no-keeper` — approximate, **insufficient** (`total_drafts 143 < 300`) |
| `tiers.json` / `projections.json` / `arbitrage.json` / `player_status.json` | 2,700 / 3,510 / 2,021 / 315 |
| Player status matched | 309 of 315 via Sleeper |
| Confidence | 2,021 rows `low`, one recorded reason; median per-player sample 93 drafts |
| Trend | null — ADR-042 needs three observation days spanning three days |
| Identity coverage | `no-keeper` 0.917, `ppr-no-keeper` 0.953, `unfiltered` 0.868 |
| Quality gate | **PASS** — 0 critical, 3 warnings |

The three warnings are the ones this project publishes rather than hides: tiers ship having
failed their stability gate (ADR-035), Sleeper `gsis_id` conflicts fail closed, and top-150
players with no market price are excluded rather than filled in.

Two things worth noticing in those numbers. The keeper-free cohort is now **143 drafts**
against Phase 5's 125 — the market is maturing exactly as ADR-039 said it would, and the
board is priced by real redraft drafts as ADR-045 requires. And the board is a preset wider
than Phase 5's: `redraft-14` is in the supported set, so nine preset blocks are priced rather
than six.

**`verify:board` on the real 2026 build, served at the project Pages base path:**

```
verifying web/dist served at http://localhost:4180/jeisey-tiers against web/dist/data
{ "tierRowsChecked": 40, "tierMarksChecked": 25,
  "arbRowsChecked": 30, "badgesRendered": 63, "failures": [] }
```

**Zero disagreements** between what the browser rendered and the artifact bytes it was
served — on production data, at the production base path, in the same job that packaged the
site. (63 injury badges against Phase 6's 56: a fresher Sleeper capture, not a regression.)

**The Pages artifact contains exactly this and nothing else:**

```
index.html
assets/index-D5_pUE1R.css   assets/index-cotNIuEY.js   assets/index-cotNIuEY.js.map
data/{tiers,projections,arbitrage,player_status,build_metadata}.json
data/{tiers,projections,arbitrage,player_status}.csv
```

No `.git`, no `market-data`, no `.py`, no `.gz`, no `node_modules`, no Playwright report —
asserted by the step, not claimed by a comment.

**Caching behaved as designed.** uv, npm and Playwright all hit their primary keys; the
nflverse cache was saved under
`nflverse-Linux-<uv.lock>-s2026-<source-registry>-2026-08-22`, with the UTC date in the key
and no restore-keys, so tomorrow's run re-downloads rather than serving today's rosters.

**Least privilege, from the deploy job's own log:** `Contents: read`, `Metadata: read`,
`Pages: write`. Nothing else was granted.

---

## 7. The owner actions — completed 2026-08-22

**All three were done, in order, and the site is live at
<https://jeisey.github.io/jeisey-tiers/>.**

| | |
|---|---|
| `market-data` branch deleted from `jeisey/jeisey-tiers` | done, before the flip |
| Repository made public | done |
| Settings → Pages → Source → **GitHub Actions** | done, after the first deploy failed without it |
| First deploy | [32597324898](https://github.com/jeisey/jeisey-tiers/actions/runs/32597324898), 2026-08-22, dispatch |
| First **scheduled** deploy | [32636603290](https://github.com/jeisey/jeisey-tiers/actions/runs/32636603290), 2026-08-23 |

The scheduled run fired at 11:27 UTC against a configured 07:17 America/New_York (11:17 UTC)
— about ten minutes of GitHub scheduling delay, which is the documented behaviour the
off-the-hour minute was chosen to reduce rather than eliminate.

The checklist below is kept as the record of what had to be done, and because it is the
procedure to repeat if the site is ever torn down.

### The one thing this phase could not do for itself

**Making `jeisey/jeisey-tiers` public is an owner-only action, and it was stopped at rather
than worked around.**

Two actions, in this order, and neither is reachable from here.

Why not: the build environment's egress policy answers **403** to `api.github.com` — only the
sanctioned GitHub tool surface can reach GitHub, and git traffic goes through a separate
proxy — and neither route offers what is needed. The tool surface can create a repository and
fork one, but has no repository-update method and no ref-deletion method. The git proxy
accepts pushes that create or update a ref and **rejects a push that deletes one** (`HTTP
403`), which is a sensible thing for a proxy to refuse and exactly what deleting a branch
requires.

So the old `market-data` branch is still on `jeisey/jeisey-tiers` and the repository is still
private, which is the correct and safe state to leave it in: **both**, or **neither**. What
must never happen is the flip without the deletion.

Everything that depends on it is already wired and waits on nothing else.

### What the owner needs to do

1. **Confirm the retained store is safe to leave behind.** It already is, and the evidence is
   in sections 1 and 2 of this document: the migration is byte-faithful, the private
   repository is private, and no retained payload object is reachable from `main`.

2. **Delete the old `market-data` branch from `jeisey/jeisey-tiers`.** It still exists at
   `57ee0c1`, and every one of its 40 files was verified byte-identical to the private
   repository immediately before this was written, so nothing is lost by deleting it.

   ```bash
   git push https://github.com/jeisey/jeisey-tiers --delete market-data
   # or: github.com/jeisey/jeisey-tiers → Branches → the bin icon beside market-data
   ```

   Then confirm it is gone — this is the check that gates everything after it:

   ```bash
   git ls-remote --heads https://github.com/jeisey/jeisey-tiers market-data   # must print nothing
   ```

   **Do not skip this.** Publishing while that branch exists is the one thing that must not
   happen, and it is not recoverable by deleting the branch afterwards.

3. **Flip visibility.** `github.com/jeisey/jeisey-tiers` → **Settings** → scroll to **Danger
   Zone** → **Change repository visibility** → *Change to public* → confirm by typing the
   repository name.

4. **Turn Pages on.** Settings → **Pages** → Build and deployment → Source → **GitHub
   Actions**. That exact value: "Deploy from a branch" is the legacy build type, is mutually
   exclusive with Actions deployment, and would make `actions/deploy-pages` fail.

   This step is required, and an earlier version of this document wrongly said it was not.
   `actions/configure-pages` was carrying `enablement: true`, which is supposed to create the
   site from the workflow — but creating a Pages site is an **admin-level** API call and a
   `GITHUB_TOKEN` is an app installation token that can never hold admin, so the first real
   deploy failed with `Create Pages site failed: Resource not accessible by integration`.
   `enablement: true` only works when handed a personal access token with admin rights, so it
   has been removed rather than left as a false promise.

5. **Run the first production refresh.** Actions → **daily-refresh** → *Run workflow* on
   `main`, leaving the inputs at their defaults. The site appears at
   **https://jeisey.github.io/jeisey-tiers/**.

6. **Smoke-test the deployed site** with the command in section 5, plus the by-eye checks
   beside it.

7. **Prove the deploy gate.** Actions → **daily-refresh** → *Run workflow*, with
   **`force_validation_failure` = true**. Expected: `capture` succeeds and its snapshot is
   committed to the private store; `build` fails at *Validate the public artifacts* with
   `artifact.non_monotonic_quantiles`; `deploy` is **skipped**; and the site from step 5 is
   still serving, unchanged. Record the run URL in section 6.

8. **Optionally shorten the daily schedule's first wait** by leaving it alone — it fires at
   07:17 America/New_York on its own.

### What is *not* needed

- No `gh-pages` branch, and no "Deploy from a branch" source. The site is deployed from the
  validated workflow artifact; a branch source would break that and would put the built site
  back into the repository.
- No new secret. `MARKET_DATA_REPO_TOKEN` and the MFL client-identity secrets already exist
  and are already proven working by run 32590470088.
- No branch protection change, no licence decision (see `docs/SECURITY_LICENSE.md` section 8),
  and no change to any workflow file.
