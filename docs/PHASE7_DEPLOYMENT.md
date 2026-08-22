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

The run evidence is in section 6.

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

_Populated as the runs complete._

---

## 7. The one thing this phase could not do for itself

**Making `jeisey/jeisey-tiers` public is an owner-only action, and it was stopped at rather
than worked around.**

Why it could not be automated here: the build environment's egress policy answers **403** to
`api.github.com` (only the sanctioned GitHub tool surface can reach GitHub, and git traffic
goes through a separate proxy), and that tool surface exposes no repository-update method —
it can create a repository and fork one, but not change an existing one's visibility. There
is no supported path from this environment to that setting.

Everything that depends on it is already wired and waits on nothing else.

### What the owner needs to do

1. **Confirm the retained store is safe to leave behind.** It already is, and the evidence is
   in sections 1 and 2 of this document: the migration is byte-faithful, the private
   repository is private, and no retained payload object is reachable from `main`.

2. **Delete the old `market-data` branch from `jeisey/jeisey-tiers`** if it is still there.
   Check first:

   ```bash
   git ls-remote --heads https://github.com/jeisey/jeisey-tiers market-data
   ```

   Empty output means it is already gone. **Do not skip this check** — publishing while that
   branch exists is the one thing that must not happen.

3. **Flip visibility.** `github.com/jeisey/jeisey-tiers` → **Settings** → scroll to **Danger
   Zone** → **Change repository visibility** → *Change to public* → confirm by typing the
   repository name.

4. **Run the first production refresh.** Actions → **daily-refresh** → *Run workflow* on
   `main`, leaving the inputs at their defaults. The deploy job's `configure-pages` step runs
   with `enablement: true`, so it creates the Pages site with the Actions build type itself —
   there is no Settings → Pages step to remember. The site appears at
   **https://jeisey.github.io/jeisey-tiers/**.

5. **Smoke-test the deployed site** with the command in section 5, plus the by-eye checks
   beside it.

6. **Prove the deploy gate.** Actions → **daily-refresh** → *Run workflow*, with
   **`force_validation_failure` = true**. Expected: `capture` succeeds and its snapshot is
   committed to the private store; `build` fails at *Validate the public artifacts* with
   `artifact.non_monotonic_quantiles`; `deploy` is **skipped**; and the site from step 4 is
   still serving, unchanged. Record the run URL in section 6.

7. **Optionally shorten the daily schedule's first wait** by leaving it alone — it fires at
   07:17 America/New_York on its own.

### What is *not* needed

- No Settings → Pages configuration (step 4 does it).
- No new secret. `MARKET_DATA_REPO_TOKEN` and the MFL client-identity secrets already exist
  and are already proven working by run 32590470088.
- No branch protection change, no licence decision (see `docs/SECURITY_LICENSE.md` section 8),
  and no change to any workflow file.
