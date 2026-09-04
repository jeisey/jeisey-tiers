# Test Strategy

## 1. Testing principle

The most dangerous bugs in this project are not syntax errors. They are:

- silent identity mismatches;
- temporal leakage;
- market leakage into the intrinsic model;
- source schema drift;
- stochastic non-reproducibility;
- incorrect replacement/FLEX math;
- model artifact/schema incompatibility;
- charts displaying a value differently from the table;
- bad data overwriting a good public deployment.

The test strategy is designed around those failure modes.

## 2. Test layers

### 2.1 Unit tests

Fast, network-free tests for:

- fantasy scoring formulas
- age/anchor-date calculations
- source normalization functions
- canonical ID parsing/crosswalk logic
- quantile monotonicity handling
- interpolation/sampling
- roster/FLEX allocation
- VORP calculation
- tier label mapping
- arbitrage gap sign convention
- CSV serialization
- URL state parsing/serialization

### 2.2 Contract tests

For every adapter fixture:

- normalized schema
- required fields/types
- source metadata
- duplicate expectations
- identity fields

For public artifacts:

- JSON Schema validation
- cross-field semantic validation

### 2.3 Integration tests

Network-free fixture mini pipeline:

```text
source fixture
 -> normalize
 -> canonical identity
 -> current feature subset
 -> deterministic mock/model inference
 -> VORP
 -> tiers
 -> market join
 -> arbitrage
 -> artifact JSON/CSV
 -> schema validation
```

This is the key PR CI smoke path.

### 2.4 Live source smoke tests

Run manually and/or scheduled, not ordinary PR CI.

Checks:

- endpoint reachable
- HTTP success/content type
- minimum records
- required key fields still exist
- source timestamp plausible
- sampled IDs resolve

These detect upstream changes without making local development dependent on the internet.

### 2.5 Leakage tests

Required automated tests:

#### Temporal cutoff

For every model feature with source timestamp lineage:

`feature_available_at <= anchor_at`

For season aggregates without row timestamps, assert the aggregation season/week set is strictly prior to the target horizon.

#### Forbidden intrinsic features

Feature-list test rejects market/expert tokens and source lineage.

#### Arbitrage OOF test

For each historical arbitrage row:

- intrinsic model training max season < target/evaluation season or fold excludes target season according to fold design;
- market-cost curve fit excludes target fold outcomes.

#### Final holdout protection

Experiment configuration must prevent final holdout from being used in tuning commands unless an explicit `--final-eval` mode is set.

> **Phase-4 implementation.** Phase 4 adds three development commands, and each is a
> potential second door to the sealed season. `tests/model/test_phase4_studies.py` proves the
> door is locked from every side: the distribution study refuses an unsealed frame, both
> stage-C studies refuse predictions containing a sealed season, and **poisoning every 2025
> label leaves a development study byte-identical**. `tests/model/test_final_holdout_gate.py`
> additionally pins the predeclared ADR-025 slices against edits and asserts that the
> acceptance rule's signature has no parameter a diagnostic slice could enter through.

### 2.6 Model tests

Not unit tests for "accuracy > magic number". Use controlled assertions:

- training completes on fixture/small data;
- deterministic seed produces same predictions;
- prediction length/IDs preserved;
- quantiles finite/monotonic;
- probability range valid;
- production artifact feature schema matches inference schema;
- calibration function monotonic;
- model promotion comparator behaves correctly on synthetic metrics.

Full model metrics are evaluated in experiment/retrain jobs and stored as reports.

### 2.7 Simulation tests

Hand-work small league examples.

Example: 2-team league, 1 RB starter, no flex, player sampled points [100, 80, 60]. Replacement after starters is 60; VORP [40,20,0].

Add tests for:

- multiple RB/WR FLEX competition;
- ties;
- negative scores/edge values if possible;
- missing eligible positions;
- deterministic output across seeds/configs;
- simulation convergence tolerance for 1k vs 5k vs 10k draws in development benchmark.

> **Phase-4 implementation.** `tests/unit/test_sampler.py`, `tests/unit/test_simulated_vorp.py`
> and `tests/unit/test_tiers.py` cover the sampler's monotonicity, tails and per-player
> determinism; the draw loop's replacement variation, league-size sensitivity and tie-break
> order; and the segmentation's two-cluster, smooth, singleton and contiguity cases. The
> convergence *comparator* is tested against synthetic evidence in
> `tests/model/test_phase4_rules.py` rather than by running a real benchmark, so a threshold
> change breaks a test in milliseconds.
>
> The load-bearing assertions are the structural ones: adding a player to the pool does not
> change anybody else's draws; the same draws are reused across league presets so a preset
> difference is a scarcity difference; replacement moves between draws, so VORP is not a
> shifted copy of points; and a repeated build is byte-identical.

### 2.8 Tier tests

Synthetic distributions:

- clear two-cluster structure -> one boundary near known gap;
- smooth no-cliff structure -> algorithm should not create pathological many tiers;
- isolated elite player -> singleton top tier allowed;
- fair-rank order shuffled internally -> tier function sorts/validates correctly;
- tier members contiguous;
- bootstrap result deterministic for fixed seed.

### 2.9 Arbitrage tests

- positive `market_adp - fair_rank` means bargain;
- negative gap means market is more aggressive than model;
- missing ADP does not crash Tier output;
- market sample quality affects confidence/baseline only as documented;
- ML fields null/omitted in baseline mode;
- baseline preserved as comparator after ML promotion.

### 2.10 Frontend unit/component tests

- artifact schema/version loader
- scoring/teams/position control state
- URL serialization
- table sort/filter/search
- filtered CSV generation
- baseline-mode conditional columns
- stale/degraded banner
- tooltip/detail accessible text

### 2.11 E2E tests

Playwright fixture build tests:

1. open default Tiers view;
2. change scoring and team size;
3. filter RB;
4. search a player;
5. verify chart/table agree on tier/rank;
6. export filtered CSV and validate row count/header;
7. switch Arbitrage;
8. sort by ADP/value gap;
9. open methodology;
10. reload copied URL and verify state;
11. test mobile viewport;
12. test Pages base path.

## 3. Data-quality tests

Critical checks should have direct tests demonstrating they block deploy:

- empty core nflverse data
- > allowed unresolved identity threshold
- public top-150 unresolved player
- duplicate player ID/rank
- stale source
- schema drift
- NaN/inf in public metrics
- nonmonotonic quantiles
- arbitrage market snapshot from wrong scoring/season
- production model feature schema mismatch

## 4. Golden fixtures

Keep fixtures intentionally tiny, e.g. 12–30 players, but cover all positions and edge cases.

Golden outputs are appropriate for:

- scoring
- identity resolution
- VORP allocation
- artifact field order/CSV headers

Avoid huge snapshot tests that obscure meaningful changes.

## 5. CI stages

Suggested order for fast feedback:

```text
Python lint/format
Python unit + leakage + contracts
Fixture mini-pipeline + artifact validation
Frontend lint/type/unit
Frontend build
Playwright smoke
```

Parallelize Python/frontend checks when convenient.

## 6. Production pipeline validation

Daily workflow additionally runs:

- live source smoke/data quality
- current identity coverage
- current model inference checks
- simulation/tier semantic checks
- market freshness
- JSON Schema validation
- web build against actual artifacts

Only after these pass can Pages deploy.

## 7. Retrain validation

Retrain job must output:

- fold table
- metrics by fold/position/scoring
- aggregate comparison to incumbent/baselines
- calibration table
- feature list + forbidden-feature audit
- data coverage report
- model artifact hash
- promotion decision/reason

A test should simulate a candidate losing a promotion metric and prove incumbent remains selected.

## 8. Code coverage

Do not chase a vanity percentage. Prioritize high coverage on:

- scoring
- identity
- contracts
- leakage guard
- simulation/VORP
- tiering
- arbitrage target/baseline
- artifact serializers

Coverage reporting is useful, but missing a critical invariant is worse than 95% line coverage.

## 8.1 Phase-5 invariants (market, arbitrage, status)

The Phase-5 suites are network-free and driven by synthetic stores, retained fixtures and
committed source schemas. Five invariants are worth naming because each one fails
*silently* if it is not tested:

**The intrinsic/market firewall is checked by walking the import graph.**
`tests/contract/test_architecture_boundary.py` parses every module under the intrinsic
packages, follows first-party imports transitively — function-local ones included, since a
deferred import is still an import — and fails on any path reaching `ffdraft.market`,
`ffdraft.sources.market` or `ffdraft.arbitrage`. It also asserts the *allowed* direction
exists, so a market layer that touched nothing could not pass by being inert. It found a
real edge on its first run.

**The store is attacked, not described.** `tests/unit/test_market_snapshot_store.py`
rewrites a retained snapshot with different bytes, corrupts a payload behind its manifest,
edits a manifest to disagree with its own path, deletes a file the manifest names, and
re-runs an identical capture. Determinism is asserted directly, because idempotency is only
real if unchanged data produces unchanged bytes.

**The A0 sign convention is tested at every interesting value.** A flipped sign crashes
nothing and quietly tells a drafter to reach for players the model thinks are expensive.

**Confidence is tested for what it ignores.** Dispersion and trend availability must not
move the tier (ADR-041), so both have negative tests.

**"Annotation only" is proved by mutation.** `tests/integration/test_status_annotation_only.py`
rewrites every injury, practice and depth field on every fixture player, rebuilds, and
asserts the tier, projection and arbitrage artifacts are **byte-identical** — plus a
positive control asserting the status artifact itself did change, so the negative tests
cannot pass by reading nothing.

Trend tests use synthetic multi-day histories, because the production store cannot yet
contain one: the correct output at launch is `null`, and a test that only checked the null
path would prove nothing about the slope.

## 8.2 Phase-8 invariants (browser coverage, accessibility, failure drills)

### Which engine runs which suite (ADR-059)

Two suites, split by whether the property under test is engine-dependent.

| suite | project(s) | engines | what it covers |
|---|---|---|---|
| `board.spec.ts` | `chromium` | Chromium | behaviour, URL state, degraded modes, exports |
| `mobile.spec.ts` | `mobile` | Chromium (Pixel 7) | phone layout, the card-as-sheet, touch targets |
| `a11y.spec.ts` | `a11y` | Chromium | axe at WCAG 2.2 AA, plus what a scanner cannot judge |
| `smoke.spec.ts` | `smoke-chromium`, `smoke-firefox`, `smoke-webkit` | all three | primary flows, layout, focus, dialog semantics, downloads, base path, reduced motion |

The behavioural suite is deliberately **not** tripled. Sorting a table, parsing a query string
and joining two artifacts do not vary by rendering engine, and running forty such assertions
three times would triple the slowest gate to re-prove logic with no engine dependency. What
does vary is layout, focus, `<dialog>`, downloads and reflow, and that is what runs everywhere.

Chromium is in the smoke suite as well as the other two on purpose: a smoke failure can then be
told apart from an engine difference. Red everywhere is the product; red in one is the browser.

**`npm run e2e:browsers` is runner-only.** Playwright downloads Firefox and WebKit from
`cdn.playwright.dev`, which a sandboxed development environment behind an egress policy blocks;
Chromium is preinstalled there and the other two cannot be fetched at all. `ci.yml`'s
`browsers` job is where it runs — the same reasoning as ADR-009's source probes.

### Accessibility

`a11y.spec.ts` is two halves, and the file says in code that the second is the one that matters.

**Automated:** axe-core at `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` over the
tiers view in three tier states, the arbitrage view in two rail states, the data view, both
degraded scenarios, and the open player dialog. Zero violations required.

Every scanned surface is paired with a selector only that surface renders, asserted visible
before axe runs. This is load-bearing rather than defensive: **a page that failed to load has no
violations either**. An earlier draft of the file passed all eight scans against a stale server
holding a build with no `data/` directory, while forty-seven board and mobile tests failed on
the same server. A scan with nothing to scan must fail, not pass.

**Not automated, because a scanner cannot judge it:** landmark and heading structure, the
board being one tab stop with arrow-key movement inside it, every tier toggle carrying
`aria-expanded`/`aria-controls` and being keyboard-operable, direction and status surviving
without colour, 24px minimum target size, a visible focus indicator on every custom control,
and reflow at 320 CSS pixels.

Zero automated violations is a floor. Automated tooling is commonly reckoned to find a third
to a half of real barriers, and every genuinely hard case in this product is in the other half.

### Failure drills

`tests/integration/test_failure_drills.py`. Offline by construction; every vendor call is a
raising or malformed stub. The property under test is **the state of the world after the
failure**, not that a function raised:

| drill | property |
|---|---|
| MyFantasyLeague unreachable | the capture raises and writes **nothing** — an empty snapshot in an append-only store can never be corrected |
| a vendor error body | fails closed rather than normalizing into an empty board |
| a missing required column | schema drift is a refusal, not a best-effort parse |
| Sleeper unreachable | raises rather than publishing an empty status artifact; no intrinsic value can move, because no intrinsic module can import the package |
| the store cannot be written | fails before any partial state |
| a truncated payload | refused by re-validation; restoring the bytes restores the verdict |
| an equal-length edit | still detected — content hashing, not size |
| the job graph | `deploy` needs `build` needs `capture`, and the deploy job does no work |
| the Pages artifact boundary | asserted by the workflow, and the assertion is asserted here |
| least privilege | exactly one `pages: write` declaration, inside the deploy job |
| the credential | CI cannot reach the store, no workflow echoes a secret or builds an authenticated remote URL, read-only checkouts do not persist one |

### Performance

`web/tests/e2e/measure-performance.mjs` builds a synthetic board at **production dimensions**
— 2,700 tier rows with the real board's tier sizes, ~1,800 arbitrage rows, 3,438 projections —
and times the interactions a drafter performs, median of five. It is not a gate: it prints a
table and writes a JSON record, and a human decides whether a number in it is a problem.
An eighteen-player fixture proves layout and measures nothing.


## 8.3 Phase-9B invariants (release brand and export treatment)

Three release-polish changes, each asserted the way it can actually fail rather than the way it
is easiest to assert. The tests are in `web/tests/e2e/board.spec.ts` under
`release brand and export treatment`, and they run in the ordinary Chromium project.

### The masthead logo

A rendered `<img>` proves nothing: a stretched, clipped or hairline logo still renders. So the
checks are geometric and run at **1440, 900 and 390** CSS pixels:

- the rendered **aspect ratio** is compared against the file's own 434:145, which is what a
  future `height`/`width` pair that disagrees with the artwork would break;
- the rendered **height** must clear 32px, so a later "make it smaller" cannot quietly turn the
  brand into a footnote, and its width must stay under 60% of the viewport, so it cannot take
  the header over;
- the **freshness stamp and status chip** must both still have their boxes on screen, which is
  the failure a wide mark actually causes;
- `document.documentElement.scrollWidth` must not exceed `clientWidth`, because a masthead is a
  cheap way to give the whole document a horizontal scrollbar on a phone.

Two absence checks sit beside them, since removal is half the change: the header must not
contain `jeisey-tiers` or `Tiers & arbitrage` as text, and `.wordmark`, `.wordmark-sub` and
`.masthead-glyph` must have **zero** elements — hidden is not removed. `page.getByRole("heading",
{ level: 1 })` asserts the accessible name the image now carries.

### The favicon

The failure mode is specifically a **root-relative href**, which resolves perfectly in
development and 404s only once deployed under `/jeisey-tiers/`. Asserting the tag exists would
miss it entirely. So the test loads the page **at the project base path**, reads every
`rel="icon"` and `rel="apple-touch-icon"` href off the served document, requires each to start
with `/jeisey-tiers/`, and then **fetches it and asserts a 200 with a non-zero body**. The
document title is checked in the same test, because it is the other thing `index.html` carries.

`ci.yml`'s base-path build repeats the structural half offline: it greps the built `index.html`
for a root-relative icon href, requires each icon to be linked at the base path, and requires
each file to be non-empty in `web/dist/`. The generator itself is pinned by
`scripts/make_favicon.py --check`, which rebuilds the three assets and compares bytes — the same
discipline the golden artifacts and the feature dictionary already live under.

### The nine-preset matrix

`web/tests/e2e/verify-presets.mjs` (`npm run verify:presets`) is the other axis from
`verify:board`. `verify-real-build.mjs` compares the rendered page with the artifact bytes cell
by cell for **one** block, PPR/redraft-12; this one is shallower per block and covers all
**nine**. The failure it exists to catch is a preset that is healthy in the artifact and dead in
the product, or healthy for the default board and broken for the eight nobody looks at — which
is the same case `coverage_summary` takes a `min` across the nine blocks to catch, and the case
`redraft-14` joining the supported set in Phase 7 created.

Two passes, cheapest first, so a failure localises:

1. **Artifacts**, from disk: rows present in `tiers`, `projections` and `arbitrage`; fair ranks
   unique **and** a complete `1..N` run, since a hole means a player is missing from the board
   and a duplicate means two share a position; tiers present, zero-based per
   `tier_record.schema.json`, and **contiguous in fair-rank order** (AGENTS.md section 9); every
   arbitrage row naming a player that block actually ranks. Projections are matched on scoring
   alone, because a points forecast does not vary by league size and the schema carries no
   `league_preset_id` — matching them on the block key would report every projection missing,
   which would be a bug in the checker rather than a finding about the build.
2. **Browser**, all nine URLs: the board, the tier table and the arbitrage table populate; the
   rank-1 name on screen is the artifact's rank-1 name **for that block**; the scoring and teams
   controls report the requested state, because if the controls disagree with the URL then every
   number on the page belongs to a different league; and nothing logs a console error, throws,
   refuses a contract or reports a degraded artifact. Every block also asserts that no request
   leaves the site's own origin — per block rather than once, because a preset-specific code
   path is exactly where a stray fetch would hide.

`--url` runs pass 2 against a deployed site while still reading the artifacts from disk, which
is how the released build is checked against `https://jeisey.github.io/jeisey-tiers/`.

The fixture build publishes only two of the nine blocks, so this script is expected to report
seven absent blocks there; it is a check on a **production** build and the strict nine is the
point of it.

### The four CSV exports

`web/tests/e2e/verify-csv.mjs` (`npm run verify:csv`) downloads all four exports from a real
browser and parses every one. Section 9 asks for real CSV verification before release, and a
clicked button is not that.

The two kinds fail differently, which is why both are checked. A **full** export is the
versioned artifact the Python serializer wrote, and its failure mode is a broken href — most
plausibly one that ignores the Pages base path; it is asserted byte-identical to `tiers.csv` /
`arbitrage.csv` on disk. A **filtered** export is generated in the browser from the rows on
screen, and its failure mode is exporting the artifact instead of the view — so the filtered
pass activates **four filters at once** (scoring, league size, position and a search term) and
then asserts, from both directions, that the file holds exactly the visible rows in the visible
order and nothing outside them.

Also checked: the filename, whose date comes from build metadata and never from the clock; the
header, which is a published column order rather than whatever the table renders; the UTF-8 BOM
the filtered export writes so Excel reads accented names; CRLF terminators; and RFC 4180
quoting — proved on a real value if the board has one containing a comma, quote or newline, and
reported as **not exercised** if it does not, rather than passing silently. NFL names rarely
carry a comma, so the escaping rule itself is pinned directly in `web/tests/csv.test.ts`; this
script's job is to say whether a real export happened to exercise it.

The filter target is derived from the artifact rather than hard-coded, preferring
`HALF/redraft-14` — the least-travelled block in the launch matrix — and falling back to
whatever the build publishes. Hard-coding it was the first draft and it was wrong: a fixture
build publishes two blocks, so the filtered pass had nothing to export and timed out on its own
assumption. Two further checker bugs it found about itself are worth not repeating: the search
parameter is `search`, not `q`, and `matchesSearch` matches name, team **or** an exact position,
so asserting it against the name alone reports a correct export as wrong.

### The export labels

The defect the owner reported was invisible to any assertion on the string, so the test measures
**geometry**: a `Range` over the control's own text gives the painted label box, which is
compared with the control's `getBoundingClientRect()` on both axes, at desktop and mobile, for
both export controls. Tolerance is 1.5px. Measured before the fix, the `Download full CSV`
anchor's label centre sat **14.5px above** its frame centre while the `<button>` beside it sat at
0.78px; both now measure 0.78px, which is the trailing letter-space every tracked control in the
app carries. The control frame is also required to be at least 36px tall, because a blockified
anchor that ignored `height` is exactly what produced the bug. A separate test asserts a non-zero
`outlineWidth` on both controls when focused, so centring cannot be bought with a focus regression.


## 8.4 Phase-11 invariants (the rest-of-season cutoff)

The rest-of-season model's whole safety argument is a **window**, so the tests are about
windows rather than about numbers.

**The cutoff proof is constructive, not declarative.** `ffdraft.ros.leakage` rebuilds a
snapshot from a panel whose post-cutoff weeks have been deleted and asserts every in-season
feature is identical. A feature that reached forward - a mis-signed shift, a rolling window
that included its own endpoint plus one, a forward fill running the wrong way - produces a
different number and fails. It runs over a sample of weeks in a production build
(`--skip-independence-check` disables it, for iteration only) and exhaustively over every
cutoff of a fixture season in the test suite.

**Its complement is checked too.** The same truncated panel must produce a label of exactly
zero remaining games and zero remaining points, because the label is defined over precisely
the weeks that were deleted. One test proves features do not read the future; the other proves
the label reads nothing else.

**The comparison is proved discriminating.** A test compares week 8 against a panel truncated
at week 9 and asserts the two *differ*. An audit that passes on everything is an audit that
checks nothing, and this is the test that would catch a comparison accidentally reduced to a
tautology.

**The label is checked against an independent recomputation.** The builder sums the weeks after
the cutoff with a reverse cumulative sum over a dense panel; the test filters to those weeks and
adds them up. Same answer by two routes, plus a reconciliation against the existing scoring
engine's season total as a *critical* build check.

**The fixture contains the awkward cases by construction**: a bye, a season-ending absence, a
mid-season team change, a mid-season arrival outside the preseason universe, a player who never
appears at all, and a postseason row in the excluded final week. Every assertion about those
players is exact arithmetic rather than a plausibility check.

**Both holdout tokens are tested against each other.** Release 1's confirmation token must not
open the rest-of-season holdout, and the rest-of-season token must not open Release 1's.

**The multi-thread claim is asserted, not assumed.** `RC1` differs from `Q1` in exactly one
parameter - the thread count - and the justification is that LightGBM's `deterministic` and
`force_row_wise` make the fit thread-count independent. A test fits the same group at one thread
and at four and requires bit-identical quantiles.

**The attribution's summation identity is a test.** Exact TreeSHAP contributions plus the base
value must equal the booster's own prediction. An attribution that stops describing the model is
worse than none, and this is the assertion that notices.

## 9. Manual review requirements

Before V1 release, a human/agent visual review should inspect:

- 5–10 known players across ranks/positions for plausible inputs/outputs;
- rookie cases;
- injured/current-status cases;
- tier cliffs;
- top arbitrage candidates and source ADP values;
- CSV export;
- source attribution.

This is a sanity layer, not a reason to manually override model outputs.
