# Session State

This file is durable cross-session state for coding agents. Keep it concise and factual.

## Current phase

Phase 0 — **complete** (2026-08-17). Phase 1 (scaffold, contracts, identity, adapters) is next and has not been started.

## Current target gate

Phase 1 exit gate: from a clean clone with no network, dependencies install, fixtures flow through normalize → identity → artifact serialization, generated fixture artifacts validate against `schemas/`, an ambiguous identity fixture fails closed, and CI passes.

## Last validated commit

The Phase-0 branch `claude/phase-0-implementation-bq5aj4`. Validation run locally and on a GitHub runner: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest` (42 passed, 4 live tests deselected).

## Production status

No production pipeline, model, artifact or site exists. What exists is the Phase-0 evidence base plus a minimal Python toolchain:

- `scripts/source_probe.py` — reproducible source/legal/feasibility probe.
- `.github/workflows/source-probe.yml` — runs it where egress is unrestricted and commits the report.
- `docs/source-probes/2026-08-17/{report.json,summary.md}` — the evidence.
- `tests/fixtures/source_schemas/*.schema.json` — 12 recorded upstream schemas for Phase-1 adapter tests.
- `pyproject.toml` / `uv.lock` — Python 3.12, deliberately minimal dependency set.

## Confirmed decisions

- Static GitHub Pages runtime.
- Python modeling/data + React/TypeScript/Vite frontend.
- Intrinsic model cannot use market/expert rank features.
- Arbitrage may use market data; historical intrinsic inputs must be OOF.
- Phase-gated implementation.
- **Arbitrage V1 ships in deterministic baseline mode** — historical ADP is dense but not point-in-time (ADR-010).
- **Current player status comes from nflverse rosters/depth charts plus Sleeper**, never `load_injuries` (ADR-011).
- **Market cohorts are approximate and must be labelled** — MFL cohort intersections collapse (ADR-012).
- **FantasyCalc disabled** (ADR-013); **FantasyPros-derived ECR disabled pending human terms review** (ADR-014).
- **Depth charts have two upstream schemas**; pre-2025 seasons have no draft-time depth observation (ADR-015).
- Source verification runs on a GitHub runner, not in an egress-restricted sandbox (ADR-009).

## Verified source facts a later phase should not re-derive

Full detail in `docs/DATA_SOURCES.md` section 13. The load-bearing ones:

- Market ADP: `https://api.myfantasyleague.com/{season}/export?TYPE=adp&JSON=1`, no auth. Fields `id, rank, averagePick, minPick, maxPick, draftsSelectedIn, draftSelPct`. **No standard deviation** — `adp_sd` stays null, dispersion comes from min/max pick. Response `timestamp` is generation time, not data-as-of.
- MFL honours `IS_PPR`, `FCOUNT`, `IS_MOCK`, `IS_KEEPER`; **ignores `DAYS`**; `CUTOFF` had no effect at 5.
- Market → canonical identity works by id alone: 100% of priced QB/RB/WR/TE (287/287), 95.4% of all priced rows; the 17 unresolved are MFL team-defence units. Two independent bridges (`espn_id` via nflverse rosters, `mfl_id` via `ff_playerids`) agreed on all 331 rows where both resolved, with zero disagreements. Prefer the nflverse-native `espn_id` bridge as primary: `mfl_id` only exists in the dynastyprocess mirror, which publishes no licence.
- Sleeper `gsis_id` coverage is only 31.9%, so join **nflverse → Sleeper on `sleeper_id`**, never the reverse. Sleeper ids can carry whitespace (`" 00-0035057"`); trim and fail closed on malformed ids.
- `nflreadpy.get_current_season()` returned 2025 on 2026-08-17 while `get_current_season(roster=True)` returned 2026. Take the draft-target season from config, cross-checked against `load_rosters` and Sleeper `/v1/state/nfl`.
- 2026 current-state inputs are healthy: 2,930 roster rows (2,852 ACT), 915 skill rows with 100% `gsis_id` and 100% `depth_chart_position`; depth-chart snapshots refresh daily at ~07:25–08:25 UTC.
- Season-level `load_player_stats` carries every component the scoring engine needs, so STD/HALF/PPR are computed in-house rather than trusting upstream `fantasy_points`.

## Open questions requiring evidence

- **MFL developer client registration.** MFL asks clients to send the User-Agent from a registered developer client. Registration needs an MFL account, so a human must do it; until then the probe/adapter sends a descriptive UA with a contact URL. Not blocking, but it is the one published obligation we cannot currently satisfy.
- **Repository visibility.** `jeisey/jeisey-tiers` is private, while `docs/OPERATIONS.md` section 3 assumes a public repository for free runners and Pages. Must be resolved before Phase 7.
- **Historical anchor depth strategy** (Phase 2). Pre-2025 seasons have no preseason depth chart. Choose between a prior-season-usage proxy and a documented week-1 proxy, and encode the choice in the feature dictionary plus a leakage test (ADR-015).
- **Market cohort mix closer to peak draft season.** Cohort counts were measured on 2026-08-17 with only 410 drafts aggregated; thin cohorts may fill in later, which would allow tighter preset matching than ADR-012 assumes.
- **FantasyPros terms** — needs a human read before any consensus benchmark claim (ADR-014).

## Repository notes

- `BUNDLE_MANIFEST.txt` matches every bundled file except `docs/AGENT_MODEL_NOTES.md`, whose recorded hash already differed from the file as first committed (`3691141`). Pre-existing, not a Phase-0 change; the manifest is otherwise a usable integrity check and was used to verify that no specification file was modified during Phase 0.
- `ruff` 0.16 formats Python code blocks inside Markdown, which silently rewrote `MASTER_SPEC.md` and `docs/ARCHITECTURE.md` the first time it ran. Markdown is now excluded from ruff in `pyproject.toml`; do not remove that exclusion.

## Known blockers

None. Phase 1 can start immediately.

## Next action

Begin Phase 1 (`docs/IMPLEMENTATION_PLAN.md`): config loading/validation, internal contract types, the source adapter protocol, then the nflverse/Sleeper/market adapters and the canonical identity resolver. Build the adapters against `tests/fixtures/source_schemas/` so the fixture pipeline stays network-free, and encode the two-bridge identity cross-check with fail-closed behaviour on disagreement.

Re-run `uv run python scripts/source_probe.py` (or dispatch `source-probe.yml`) if more than a few weeks have passed, since source contracts drift.
