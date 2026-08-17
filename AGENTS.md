# AGENTS.md — Repository Operating Contract for Coding Agents

This file is the canonical instruction set for any autonomous or interactive coding agent working on this repository. Its scope is the entire repository unless a more specific nested `AGENTS.md` is later added.

## 1. Mission

Build the product specified in `PRD.md` methodically and prove that it works. Do not optimize for producing a large diff. Optimize for validated progress through phase gates.

The core invariant is:

> The intrinsic Tier model estimates football value without market/expert ranking inputs. The Arbitrage model may consume intrinsic outputs plus market data. Information never flows in the opposite direction.

Breaking this invariant is a design bug.

## 2. Required reading order at the start of a fresh session

1. `AGENTS.md`
2. `PRD.md`
3. `TASKS.md`
4. `SESSION_STATE.md`
5. the documentation file(s) relevant to the current phase
6. existing implementation/tests for the touched subsystem

Do not assume the repository still matches the original spec; inspect current code and Git status before modifying anything.

## 3. Session protocol

Before editing:

1. State the current phase and exact exit gate being targeted.
2. Inspect relevant files and tests.
3. If the task touches a public API/data source, verify the source contract against current official documentation or a recorded Phase-0 source probe. Never invent an endpoint or schema.
4. Write a concise implementation plan for multi-file or architectural work.
5. Identify the tests that will prove completion.

During editing:

- Keep changes scoped to the current phase/gate.
- Prefer small composable modules and explicit data contracts.
- Run focused tests early, then the broader required test suite.
- Do not "fix" failing tests by weakening assertions unless the specification changed and an ADR/doc update justifies it.
- Do not silently substitute a source, model target, scoring formula, or metric.

Before declaring completion:

1. Run the phase-required commands.
2. Inspect generated artifacts, not only exit codes.
3. Report exact tests/metrics run and their results.
4. Update `TASKS.md` accurately.
5. Update `SESSION_STATE.md` with decisions, blockers, next gate, and any source/model caveats.
6. Update documentation/model cards when behavior changed.

## 4. Phase discipline

Do not implement Phase N+1 merely because it is interesting. A phase may be exited only when its explicit criteria in `docs/IMPLEMENTATION_PLAN.md` and `TASKS.md` are satisfied.

If blocked by a source or feasibility issue:

- record the evidence;
- implement a clean interface/fixture only if useful;
- choose a documented fallback allowed by `docs/DATA_SOURCES.md`;
- never fabricate data or mark the phase complete.

## 5. Data-source rules

- Publicly visible does not mean redistributable.
- Follow `config/source-registry.yaml` and `docs/DATA_SOURCES.md`.
- A source marked `verify_before_use` cannot become a production dependency until the check is completed and documented.
- Cache responsibly and use a descriptive User-Agent where supported.
- Respect source cadence; do not hammer APIs.
- Persist raw/source timestamps and retrieval timestamps separately.
- Do not execute downloaded code or untrusted serialized objects.
- Live-network tests must be opt-in; normal unit/CI tests use fixtures/mocks.

## 6. Identity rules

- `gsis_id` is the preferred canonical player key where available.
- Use verified crosswalk IDs for Sleeper/MFL/ESPN/etc.
- Production joins may not depend solely on normalized names.
- Fuzzy/name matching belongs only in an explicit resolver stage with confidence and unresolved output.
- Ambiguous identity fails closed for affected records.
- Add regression fixtures for every identity collision bug.

## 7. Temporal leakage rules

Every training feature must have a timestamp or a defensible season-relative availability rule.

For a training row representing preseason of season Y:

- no feature may use regular-season outcomes from Y;
- no roster/depth/injury snapshot may occur after the configured draft-time anchor;
- no future team assignment may leak backward;
- no target-derived aggregate may be computed across the validation season;
- arbitrage training may only consume out-of-fold intrinsic predictions for the same historical season.

Create automated leakage tests. Treat leakage as a release blocker.

## 8. Modeling rules

- Baseline first; candidate second.
- Use rolling-origin/time-aware evaluation only.
- Fix random seeds and record them in model metadata.
- Predeclare primary metrics before model comparison.
- Report year-by-year and position-by-position slices.
- Never select a model because its architecture sounds sophisticated.
- Never claim "better" without running the comparison.
- Never tune on the final holdout.
- Calibration is part of the model, not a cosmetic chart concern.
- A model card is required for every promoted production model.

### Intrinsic model forbidden features

The intrinsic model must never receive:

- ADP
- ECR/expert rank
- FantasyPros rank/consensus
- FantasyCalc value/rank
- sportsbook/fantasy market rank intended as a proxy for crowd expectation
- the output of the arbitrage model

If a feature is arguably a market expectation proxy, stop and document the decision before adding it.

## 9. Tiering rules

- Tier input is intrinsic simulated value/VORP only.
- Tiers are contiguous in fair-rank order.
- Tier count is discovered, not hard-coded per position.
- Boundary stability must be measured.
- Do not manually move a player because a tier "looks wrong." Fix the model/algorithm or document why it is behaving that way.

## 10. Arbitrage rules

- Market data is allowed here.
- Current market data must record source, timestamp, sample size/dispersion when available.
- Preserve a simple fair-rank-vs-ADP baseline forever as a challenger/reference.
- Do not label the system ML unless the historical market coverage and out-of-time promotion gate pass.
- The learned arbitrage target must represent realized value relative to market cost, not merely future raw fantasy points.

## 11. Frontend rules

- Utility first. Avoid hero sections, decorative KPI cards, marketing copy, gradients, glassmorphism, excessive rounded cards, and animation for its own sake.
- D3 owns bespoke chart geometry; React owns state/composition. Do not let D3 mutate arbitrary React-managed DOM.
- TanStack Table owns table state where practical.
- TypeScript strict mode stays enabled.
- URL query state must be deterministic and shareable.
- Tier/arbitrage meaning cannot depend on color alone.
- Respect reduced motion.
- All exported values shown in the UI must originate from versioned public artifact contracts.
- No runtime calls to data vendors for core page rendering.

## 12. Architecture rules

- Static runtime architecture is the default and should not be replaced without an ADR.
- No database/backend/serverless function for V1 unless an explicit requirement becomes impossible otherwise.
- Keep source adapters, canonical transforms, feature engineering, models, simulation, tiering, arbitrage, artifact serialization, and frontend separate.
- Public JSON/CSV schemas are versioned contracts.
- Avoid dataframe "stringly typed" coupling across modules; centralize column definitions/contracts.
- Production model artifacts must have an explicit version and compatible feature-schema hash/version.

## 13. Dependency rules

- Python dependencies managed by `uv`; commit lockfile.
- JavaScript dependencies managed consistently with one package manager; commit lockfile.
- Prefer mature, small dependencies with clear licenses.
- Do not add a framework when a small module suffices.
- Security-sensitive or binary serialization dependencies require justification.

## 14. Testing commands — target steady state

The exact scripts may be bootstrapped in early phases, but the final repository should support commands equivalent to:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run python -m ffdraft.cli validate-artifacts public/data

npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run e2e
```

A fixture-based mini end-to-end data build must run without network access.

## 15. Git and change discipline

- Never commit secrets, credentials, caches, raw vendor dumps, or large accidental artifacts.
- Keep generated production data out of ordinary source commits unless the storage strategy explicitly calls for it.
- Do not rewrite unrelated code while implementing a phase.
- Preserve a clean `git diff` that a human can review.
- If commits are requested/available, use logical phase/subphase commits.
- PR descriptions should state: problem, approach, validation, model/data implications, screenshots for UI changes, and remaining risks.

## 16. Multi-agent / subagent guidance

Use parallel agents only for genuinely independent workstreams, such as:

- source feasibility probes
- frontend visual prototype against fixed fixtures
- model baseline experiment
- test/QA review

Rules:

- Give each subagent explicit file ownership or read-only scope.
- Do not allow two agents to edit overlapping files concurrently.
- One lead agent integrates results and runs the final full validation.
- Subagent conclusions are hypotheses until reproduced in the main workspace.
- Store durable decisions/results in repository docs, not only chat context.

## 17. Frontier-model guidance

This repo is deliberately structured for long-context autonomous agents.

For models with adjustable reasoning/effort:

- use high/max effort for source legality/feasibility, architecture changes, leakage analysis, evaluation design, and difficult bugs;
- ordinary implementation can use lower effort if tests/contracts are already clear;
- do not spend frontier reasoning tokens repeatedly rediscovering repository facts that belong in `SESSION_STATE.md` or docs.

For multi-agent modes:

- parallelize research/verification, not architectural authority;
- require evidence and tests from each branch of work;
- synthesize into one coherent implementation.

Do not assume a model name implies a context length, toolset, or permission mode. Inspect the active harness when that matters.

## 18. Documentation drift

If code changes a documented contract, update the documentation in the same change.

The following are source-of-truth pairs:

- artifact serializers ↔ `schemas/*.schema.json`
- source adapters ↔ `config/source-registry.yaml` + `docs/DATA_SOURCES.md`
- league config code ↔ `config/league-defaults.yaml`
- model features/targets ↔ `docs/MODELING.md` + model card
- workflows ↔ `docs/OPERATIONS.md`

## 19. Definition of done for any task

A task is done only when:

- implementation exists;
- tests prove the intended behavior and important failure cases;
- required linters/type checks pass;
- generated output was inspected when relevant;
- documentation/contracts are current;
- no known critical data/model leakage issue remains;
- `TASKS.md` / `SESSION_STATE.md` accurately reflect reality.

"Code written" is not a completion state.
