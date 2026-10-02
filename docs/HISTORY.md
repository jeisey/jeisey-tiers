# Development history

This is the development history of Jeisey Tiers, kept for context. It describes how the product
was built and is not a description of current behaviour: for that, read
[`README.md`](../README.md), [`PRD.md`](../PRD.md) and the documents under `docs/`. Exit-gate
detail for every phase is in [`TASKS.md`](../TASKS.md); the reasoning behind each decision is in
[`DECISIONS.md`](DECISIONS.md).

## The original specification

The repository began on 2026-08-17 as a specification bundle written for a coding agent: a
product requirements document, an operating contract (`AGENTS.md`), a phase-gated task board, a
session-state template, the architecture, data-source, data-contract, modelling, UX, test,
operations and security documents, the league and source-registry configuration, and the public
artifact schemas. `MASTER_SPEC.md` is a single-file concatenation of that bundle,
`BUNDLE_MANIFEST.txt` its checksums, `repo-tree.txt` its target tree and `PROMPT_START_HERE.md`
the prompt that started Phase 0. All four are kept as a marked archive, with competitor-positioning lines
removed; the living versions of their contents are `PRD.md`, `AGENTS.md` and `docs/`.

## Timeline

| Date | Milestone |
|---|---|
| 2026-08-17 | Phase 0 — source, legal and feasibility proof |
| 2026-08-18 | Phase 1 — scaffold, contracts, identity, source adapters |
| 2026-08-19 | Phase 2 — historical feature dataset; Phase 3 — intrinsic baselines and evaluation harness; Phase 4 — production DraftValue, simulation and tiers (two frozen gates measured as failing: ADR-034, ADR-035) |
| 2026-08-20 | Phase 5 — market snapshots and the arbitrage baseline |
| 2026-08-21 | Phase 6 — the frontend draft sheet |
| 2026-08-22 | Phase 7 — production Actions and GitHub Pages (live once the repository was made public) |
| 2026-08-31 | Phase 8 — hardening, audit and frontend redesign; Phase 9A — implementing the owner's Claude Design source |
| 2026-09-01 | Phase 9B — launch release, tagged [`v1.0.0`](releases/v1.0.0.md) |
| 2026-09-03 | Phase 10 — multi-market draft intelligence (one criterion short: FantasyPros' free API tier serves ten rows and no ADP, ADR-064) |
| 2026-09-04 | Phase 11 — the rest-of-season model, offline; Phase 12 — In-Season mode, the ROS Tier Board, the Opportunity Board, season-state orchestration, tagged [`v2.0.0`](releases/v2.0.0.md) |
| 2026-09-15 | In-season presentation pass (ADR-085); card meters (ADR-086) |
| 2026-09-16 | Player-card portraits (ADR-087) |
| 2026-09-18 | Pick of the Week (ADR-088) |
| 2026-09-19 | Add momentum (ADR-089) |
| 2026-09-22 | In-season signal layer (ADR-091) |
| 2026-09-23 | The Opportunity Board as the triage surface (ADR-092); folding control bands on phones (ADR-093) |
| 2026-09-24 | The draft market is read at the draft anchor (ADR-094) |
| 2026-09-30 | In-season MFL capture cannot freeze the refresh (ADR-095); Start/Sit and `weekly-startsit-v1` (ADR-096, ADR-097); serving under load on GitHub Pages (ADR-098) |
| 2026-10-01 | Game-day context, `weekly-startsit-v2` in shadow, and "why this week" (ADR-099) |
| 2026-10-02 | The Trade tab (ADR-100) |
| 2026-10-02 | Public-launch housekeeping: the logo links home, one availability policy for every decision surface (ADR-101), README/PRD rewritten around the shipped product, a current security review |

Every shortfall along the way was published as a limitation rather than repaired by moving a
threshold.

## How it got here

Phase 1 built the skeleton that makes bad joins and schema drift hard. Phase 2 built the
time-correct data asset — 11,604 leakage-audited player-seasons across 2014–2025 with
independently computed STD/HALF/PPR labels and market-independent realized VORP. Phase 3 built
the rolling-origin evaluation harness and the baselines worth beating. Phase 4 turned that into
a production intrinsic model, a deterministic Monte Carlo simulation of league-relative value,
and natural contiguous tiers. The model passed its single sealed-holdout evaluation on 2025; two
frozen gates did not pass — the Monte Carlo draw count is a predeclared fallback rather than a
converged count (ADR-034), and tier boundaries are not stable enough to meet the declared
threshold (ADR-035) — and both were published as limitations.

Phase 5 added the market half without letting it near the model. Point-in-time ADP snapshots are
retained append-only in a dedicated Git-backed store, because MyFantasyLeague's historical export
is a season aggregate recomputed at request time and a price not captured on the day can never be
reconstructed. The arbitrage board is a transparent fair-rank-versus-ADP baseline and says so; no
learned model is claimed and no surplus or probability is invented. Current injury and roster
status ships as a separate artifact that annotates a row and can never move one. The cohort study
found dynasty rookie drafts inside the ADP aggregate — rookies priced three to five times earlier
than in real redraft leagues, while veterans did not move — so a redraft board is priced only by
keeper-free cohorts.

Phase 6 put a product in front of it: a Tier board and a Draft Rail drawn with D3 geometry and
React DOM, two sortable tables, filtered and full CSV export, a methodology and freshness surface
read entirely from build metadata, degraded-artifact states, layouts down to 390px, and keyboard
and reduced-motion behaviour. The interface is built around the findings the modelling phases
published: a tier is drawn as a band because its boundaries were measured as unstable, an injury
badge says the projection never saw it, and the market-confidence label is explained as data
quality, with its reason pulled from the build.

Phase 7 deployed it, and had to move the data first. The retained capture store lived on a branch
of this repository, and GitHub visibility is a property of a repository rather than of a branch,
so making this repository public would have published thousands of retained vendor payloads that
are a private research cache under non-commercial terms. The store moved to a separate private
repository first, byte-faithfully and verified as such. The site is deployed by a three-job graph
— capture, build, deploy — in which the deploy job contains only the Pages actions, so a failed
gate anywhere upstream leaves the previous site serving. Making the repository public was an
owner-only action, after which the deploy job enabled Pages on its first successful run.

Phase 8 hardened the system and rebuilt the frontend around the owner's review of the live site:
a copy audit that put every methodology explanation in the Data view exactly once, a Tier board
that collapses so a 300-deep board fits on a screen without narrowing its uncertainty, a rail
whose geometry encodes the signed gap rather than an absolute pick axis, and an audit across
production runs, the model artifact, simulation convergence, security, accessibility and three
browsers. Its most useful finding was in the tests: every market-sensitive test had been written
against a uniformly low-confidence board with no trend history, a state production had already
left, so the suite was pinning a launch condition rather than checking a contract.

Phase 9A finished the one Phase-8 item that could not be done in that phase. The redesign was
meant to implement the owner's Claude Design project, which could not be reached from the
session, so the visual language was first inferred from his written brief and the gap recorded.
He then supplied the design files, and the frontend now implements them — the tier board, both
tables, the controls and three player-card variants chosen by viewport, in the source's
typography and hairline construction. Four of the source's text tones fail WCAG AA at the sizes
used, so those were corrected and the deviation written down. No projection, tier, price or score
changed, and `verify:board` compares the rendered board against the artifact bytes on every
production build.

Phase 9B released it. The visible changes were small — the owner's logo replaced the typeset
wordmark, with a favicon drawn from the same artwork — but the phase found that the repository
could not check most of what a release checklist asks for. `verify:board` covered one preset
block of nine; CSV coverage asserted that a download fired rather than that a file was right; and
nothing looked at the site after it deployed. Three verifiers close that: `verify:presets`
resolves all nine blocks in the artifact and in the browser, `verify:csv` downloads and parses all
four exports and checks the filtered ones hold the visible subset, and `verify:live` checks a
deployment — every asset under the deployed base path, the logo's decoded width, a shared link
across a reload, and that no request leaves the site's origin. It runs from `live-smoke.yml`,
which is dispatch-only and gates nothing.

## Release 2 and the in-season product

Release 2 opened with Phase 10, multi-market draft intelligence: Fantasy Football Calculator joined
MyFantasyLeague as a published ADP source, with a cross-market spread view. FantasyPros was
implemented and retained but not published, because the free API tier returns ten rows and no ADP
(ADR-064, ADR-080).

Phase 11 built the rest-of-season model, `intrinsic-ros-v1`, as an offline subsystem: point-in-time
weekly snapshots, four declared baselines, a frozen promotion rule, and rest-of-season value above
replacement with its own replacement interpretation. The model failed one clause of its original
promotion rule; a readiness pass established that the clause measured the target's atom at zero
rather than the model, and replaced it with a rule stated on quantities that survive an atom
(ADR-075). The model was promoted under the new rule (ADR-077), and the original failure is kept
on record.

Phase 12 published it: In-Season mode, the ROS Tier Board, the Sleeper-powered Opportunity Board
and season-state orchestration, released as `v2.0.0` on 2026-09-04. At release no live in-season
week had been built, because the season had not started; the first post-week refresh after week 1
was the open operational check. The first in-season refreshes found two operational defects: a
board check that did not know September's `INA` roster code (2026-09-12, ADR-082) and nflverse
downloads with no retry (2026-09-15, the first scheduled run after week 1, ADR-083).

After Release 2, in-season tools were added in their own passes, each with an ADR: Pick of the
Week, add momentum and the signal layer; the Start/Sit tab on `weekly-startsit-v1`, a quantile
model of next-game points frozen before evidence that beat all three of its baselines on
development folds and on the sealed 2025 season — including a baseline that already reads the
Vegas implied total (pairwise start/sit accuracy 0.666 against 0.645); content-addressed serving
so the site survives a traffic burst on GitHub Pages alone; game-day weather and injury context
with `weekly-startsit-v2` recorded in shadow for a prospective test; and the Trade tab.
