"""The network-free fixture mini-pipeline.

This is the Phase-1 exit gate made executable (`docs/IMPLEMENTATION_PLAN.md` Phase 1,
`docs/TEST_STRATEGY.md` 2.3). It drives synthetic fixtures through every contract boundary
the production build will use::

    source fixture -> adapter normalization -> canonical identity -> internal contracts
      -> deterministic stub valuation -> artifact serialization -> schema validation

**The valuation in this module is not a model.** It is a serialization exerciser, and it is
deliberately parked here rather than in ``ffdraft/modeling``, ``ffdraft/simulation`` or
``ffdraft/tiers`` so that nothing can mistake it for the real thing:

* projections are *read from a fixture file*, not estimated;
* replacement value is "the last startable player at the position", clamped to the fixture
  pool - not the Monte Carlo starter/FLEX allocation Phase 4 owes;
* tiers come from a fixed VORP-gap threshold, not the change-point segmentation Phase 4
  owes;
* the arbitrage score is the **real** Phase-5 A0 baseline (ADR-040): the stub transform is
  gone, and the fixture now exercises production arbitrage code against fixture inputs.

Every artifact it writes records ``intrinsic_model_version="fixture-stub-0"`` so a stub
build can never be mistaken for production output. Phases 4 and 5 replace the stub sections;
the identity, contract, quality and serialization code they feed is production code.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft.arbitrage.build import build_arbitrage_records
from ffdraft.arbitrage.frozen import ARBITRAGE_CONFIDENCE_VERSION, ARBITRAGE_METHOD_VERSION
from ffdraft.artifacts import (
    ARTIFACT_SCHEMA_VERSION,
    validate_artifact_directory,
    write_artifact,
    write_build_metadata,
)
from ffdraft.config import AppConfig, LeaguePreset, ScoringPreset, load_app_config
from ffdraft.contracts import (
    CORE_POSITIONS,
    CanonicalPlayer,
    EntityKind,
    Position,
    QualityCheck,
    ResolutionOutcome,
    Severity,
    SourceBatch,
    SurfaceReason,
)
from ffdraft.contracts.enums import MarketSignalType
from ffdraft.identity import (
    CanonicalRegistry,
    build_registry,
    coverage_checks,
    outcomes_to_frame,
    resolve_market_quotes,
    resolve_sleeper_status,
    summarize,
)
from ffdraft.identity.aliases import AliasMap
from ffdraft.identity.resolver import FLAG_SECONDARY_ONLY
from ffdraft.market.cohorts import COHORT_RULE_VERSION, CohortAssignment, widest_cohort
from ffdraft.market.comparison import SourceQuote
from ffdraft.market.current import (
    LOW_MARKET_SAMPLE,
    LOW_SAMPLE_THRESHOLD,
    SECONDARY_IDENTITY_BRIDGE_ONLY,
    WIDE_MARKET_RANGE,
    CurrentMarket,
    MarketPrice,
)
from ffdraft.market.surface import (
    SURFACE_RULE_VERSION,
    SurfaceEntry,
    SurfaceUniverse,
)
from ffdraft.market.trend import INSUFFICIENT_TREND_HISTORY, TREND_RULE
from ffdraft.quality import QualityGate, check_source_freshness
from ffdraft.quality.forbidden import (
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
)
from ffdraft.quality.thresholds import MARKET_SOURCE_MAX_AGE
from ffdraft.retention import snapshot_key
from ffdraft.sources import (
    NflverseDepthChartAdapter,
    NflversePlayerIdsAdapter,
    NflverseRosterAdapter,
    SleeperPlayerAdapter,
)
from ffdraft.sources.ffc import FFC_SOURCE_ID
from ffdraft.sources.market import (
    MFL_SOURCE_ID,
    MflAdpAdapter,
    MflPlayerDirectory,
    MflPlayerDirectoryAdapter,
)
from ffdraft.status.build import PlayerStatusResult, build_player_status_records
from ffdraft.status.capture import StatusCapture
from ffdraft.timeutil import isoformat_utc, parse_utc

__all__ = [
    "FIXTURE_IDENTITY_COVERAGE_MINIMUM",
    "FIXTURE_MODEL_VERSION",
    "FIXTURE_SEASON",
    "FixtureInputs",
    "FixturePipelineResult",
    "build_fixture_artifacts",
    "load_fixture_inputs",
    "run_fixture_pipeline",
]

#: Stamped into every artifact this module produces. Never promote it.
FIXTURE_MODEL_VERSION = "fixture-stub-0"
FIXTURE_METHODOLOGY_VERSION = "phase1-fixture-0"
FIXTURE_SEASON = 2026
#: Deterministic default so two runs of the fixture pipeline are byte-identical.
FIXTURE_GENERATED_AT = "2026-08-18T12:00:00Z"
FIXTURE_BUILD_ID = "fixture-20260818T120000Z"

#: New tier whenever expected VORP drops by more than this between adjacent fair ranks.
TIER_GAP_THRESHOLD = 15.0
#: The fixture set is *deliberately adversarial*: 16 canonical players carrying two planned
#: identity failures (one bridge disagreement, one priced-but-unrostered prospect), which is
#: a 12.5% miss rate by construction. It therefore cannot - and must not be made to - meet
#: the production launch threshold in :mod:`ffdraft.quality.thresholds`. That constant stays
#: at 95% for the real pipeline; this one exists so the exerciser can run its failure cases
#: without either weakening the production gate or hiding the failures.
FIXTURE_IDENTITY_COVERAGE_MINIMUM = 0.80
FIXTURE_SLEEPER_COVERAGE_MINIMUM = 0.80

_LAUNCH_PRESETS = ("redraft-10", "redraft-12")
_SCORING_PRESET = ScoringPreset.PPR


@dataclass(frozen=True, slots=True)
class FixtureInputs:
    """Raw fixture payloads, exactly as an adapter would receive them upstream."""

    roster: list[dict[str, Any]]
    player_ids: list[dict[str, Any]]
    sleeper_players: dict[str, dict[str, Any]]
    mfl_directory: list[dict[str, Any]]
    mfl_adp: dict[str, Any]
    depth_snapshot: list[dict[str, Any]]
    depth_weekly: list[dict[str, Any]]
    projection_inputs: dict[str, Any]


@dataclass
class FixturePipelineResult:
    """Everything the pipeline produced, for tests and the CLI to inspect."""

    registry: CanonicalRegistry
    batches: dict[str, SourceBatch] = field(default_factory=dict)
    market_outcomes: list[ResolutionOutcome] = field(default_factory=list)
    sleeper_outcomes: list[ResolutionOutcome] = field(default_factory=list)
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    build_metadata: dict[str, Any] = field(default_factory=dict)
    gate: QualityGate = field(default_factory=QualityGate)
    written: list[Path] = field(default_factory=list)

    @property
    def resolution_frame(self) -> pl.DataFrame:
        return outcomes_to_frame([*self.market_outcomes, *self.sleeper_outcomes])


def load_fixture_inputs(directory: Path) -> FixtureInputs:
    """Read the committed fixture payloads."""

    def read(name: str) -> Any:
        return json.loads((directory / name).read_text(encoding="utf-8"))

    return FixtureInputs(
        roster=read("nflverse_rosters.json"),
        player_ids=read("nflverse_ff_playerids.json"),
        sleeper_players=read("sleeper_players.json"),
        mfl_directory=read("mfl_players.json"),
        mfl_adp=read("mfl_adp.json"),
        depth_snapshot=read("nflverse_depth_charts_2026.json"),
        depth_weekly=read("nflverse_depth_charts_2024.json"),
        projection_inputs=read("expected_points.json"),
    )


def run_fixture_pipeline(
    inputs: FixtureInputs,
    *,
    config: AppConfig | None = None,
    generated_at: datetime | None = None,
    build_id: str = FIXTURE_BUILD_ID,
    git_sha: str | None = None,
    aliases: AliasMap | None = None,
) -> FixturePipelineResult:
    """Run every stage in memory and return the records plus the quality gate."""
    app = config or load_app_config()
    now = generated_at or parse_utc(FIXTURE_GENERATED_AT)
    gate = QualityGate()

    # -- 1. adapters -------------------------------------------------------------------
    batches: dict[str, SourceBatch] = {}

    roster_adapter = NflverseRosterAdapter()
    gate.extend(roster_adapter.check_source_schema(inputs.roster))
    roster_batch = roster_adapter.normalize(inputs.roster, season=FIXTURE_SEASON, retrieved_at=now)
    gate.extend(roster_adapter.validate_raw(roster_batch).checks)
    batches["nflverse_rosters"] = roster_batch

    ids_adapter = NflversePlayerIdsAdapter()
    gate.extend(ids_adapter.check_source_schema(inputs.player_ids))
    ids_batch = ids_adapter.normalize(inputs.player_ids, retrieved_at=now)
    gate.extend(ids_adapter.validate_raw(ids_batch).checks)
    batches["nflverse_ff_playerids"] = ids_batch

    depth_adapter = NflverseDepthChartAdapter(season=FIXTURE_SEASON)
    gate.extend(depth_adapter.check_source_schema(inputs.depth_snapshot))
    depth_batch = depth_adapter.normalize(inputs.depth_snapshot, retrieved_at=now)
    gate.extend(depth_adapter.validate_raw(depth_batch).checks)
    batches["nflverse_depth_charts"] = depth_batch

    sleeper_adapter = SleeperPlayerAdapter()
    sleeper_batch = sleeper_adapter.normalize(inputs.sleeper_players, retrieved_at=now)
    gate.extend(sleeper_adapter.validate_raw(sleeper_batch).checks)
    batches["sleeper_players"] = sleeper_batch

    directory_adapter = MflPlayerDirectoryAdapter()
    gate.extend(directory_adapter.check_source_schema(inputs.mfl_directory))
    directory_batch = directory_adapter.normalize(inputs.mfl_directory, retrieved_at=now)
    gate.extend(directory_adapter.validate_raw(directory_batch).checks)
    directory = MflPlayerDirectory(frame=directory_batch.frame)
    batches["mfl_players"] = directory_batch

    # The fixture prices one cohort: the unfiltered aggregate, which is what ADR-012 calls
    # the widest reliable cohort. It is approximate for every preset, and the assignment
    # below says so rather than the quote rows claiming a preset they do not describe.
    cohort = widest_cohort()
    assignment = CohortAssignment(
        scoring_preset=str(_SCORING_PRESET),
        league_size=app.league.default_preset.teams,
        cohort=cohort,
        exact=False,
        sufficient=True,
        reason="the fixture prices one cohort; sufficiency is not measured here",
    )
    adp_adapter = MflAdpAdapter()
    adp_rows = inputs.mfl_adp["adp"]["player"]
    gate.extend(adp_adapter.check_source_schema(adp_rows))
    market_batch = adp_adapter.normalize(
        inputs.mfl_adp,
        season=FIXTURE_SEASON,
        cohort=cohort,
        directory=directory,
        retrieved_at=now,
    )
    gate.extend(adp_adapter.validate_raw(market_batch).checks)
    gate.extend(
        check_source_freshness(
            market_batch.metadata.retrieved_at_utc,
            now=now,
            max_age=MARKET_SOURCE_MAX_AGE,
            source_id=market_batch.source_id,
            stage="sources",
        ),
    )
    batches["mfl_adp"] = market_batch

    # -- 2. canonical identity ---------------------------------------------------------
    registry = build_registry(roster_batch.frame, player_ids=ids_batch.frame)
    gate.extend(registry.checks)

    espn_by_mfl = _mapping(directory_batch.frame, "mfl_id", "espn_id")
    gsis_by_mfl = _mapping(ids_batch.frame, "mfl_id", "gsis_id")
    names_by_mfl = _mapping(directory_batch.frame, "mfl_id", "name")

    market_outcomes = resolve_market_quotes(
        market_batch.frame,
        registry=registry,
        espn_by_mfl_id=espn_by_mfl,
        gsis_by_mfl_id=gsis_by_mfl,
        names_by_mfl_id=names_by_mfl,
        aliases=aliases or AliasMap.empty(),
        source_id=market_batch.source_id,
    )
    market_summary = summarize(market_outcomes, source_id=market_batch.source_id)
    gate.extend(
        coverage_checks(
            market_summary,
            minimum_coverage=FIXTURE_IDENTITY_COVERAGE_MINIMUM,
            stage="identity.market",
            # Ambiguity is fatal for *published* output; at the resolution stage it is the
            # expected, correct response to a conflicting fixture, and it is excluded below.
            ambiguous_severity=Severity.WARNING,
        ),
    )

    sleeper_outcomes = resolve_sleeper_status(
        sleeper_batch.frame,
        registry=registry,
        source_id=sleeper_batch.source_id,
        positions=CORE_POSITIONS,
    )
    sleeper_summary = summarize(sleeper_outcomes, source_id=sleeper_batch.source_id)
    gate.extend(
        coverage_checks(
            sleeper_summary,
            minimum_coverage=FIXTURE_SLEEPER_COVERAGE_MINIMUM,
            stage="identity.sleeper",
            ambiguous_severity=Severity.WARNING,
        ),
    )

    # -- 3. the intrinsic boundary -----------------------------------------------------
    # The stub consumes only football inputs. Auditing that here means the boundary is
    # checked by the build, not only by review (ADR-002, docs/TEST_STRATEGY.md 2.5).
    intrinsic_features = ("expected_points", "position", "team", "years_exp", "rookie_season")
    gate.extend(audit_intrinsic_feature_names(intrinsic_features))
    gate.extend(
        audit_intrinsic_source_lineage(
            {name: ["nflreadpy"] for name in intrinsic_features},
            registry=app.registry,
            stage="intrinsic.fixture_stub",
        ),
    )

    # -- 4. deterministic stub valuation and serialization -----------------------------
    projections = _projection_records(
        inputs.projection_inputs,
        registry=registry,
        build_id=build_id,
        generated_at=now,
    )
    tiers: list[dict[str, Any]] = []
    for preset_id in _LAUNCH_PRESETS:
        tiers.extend(
            _tier_records(
                inputs.projection_inputs,
                registry=registry,
                preset=app.league.preset(preset_id),
                build_id=build_id,
            ),
        )
    market_records = _market_snapshot_records(
        market_batch,
        outcomes=market_outcomes,
        assignment=assignment,
    )
    arbitrage = _arbitrage_records(
        tiers,
        market_batch=market_batch,
        outcomes=market_outcomes,
        assignment=assignment,
        build_id=build_id,
        snapshot_at=now,
    )
    trend_series = _trend_series_records(
        arbitrage,
        assignment=assignment,
        source_id=market_batch.source_id,
        build_id=build_id,
        snapshot_at=now,
    )

    status = _player_status_records(
        registry=registry,
        roster=roster_batch.frame,
        sleeper_batch=sleeper_batch,
        build_id=build_id,
        generated_at=now,
        published=[str(row["player_id"]) for row in tiers],
        gate=gate,
    )

    records = {
        "projections": projections,
        "tiers": tiers,
        "arbitrage": arbitrage,
        "market_trend_series": trend_series,
        "market_snapshot": market_records,
        "player_status": status.records,
    }
    gate.extend(_published_identity_checks(records, market_outcomes))

    metadata = _build_metadata(
        app,
        batches=batches,
        gate=gate,
        build_id=build_id,
        generated_at=now,
        git_sha=git_sha or _git_sha(),
        presets=_LAUNCH_PRESETS,
        status=status,
        market={
            "source_id": market_batch.source_id,
            "snapshot_key": snapshot_key(now),
            "snapshot_at_utc": isoformat_utc(now),
            "source_as_of_utc": None,
            "cohort_rule_version": COHORT_RULE_VERSION,
            "confidence_rubric_version": ARBITRAGE_CONFIDENCE_VERSION,
            "trend_rule_version": TREND_RULE.version,
            "trend_available": False,
            "assignments": [
                {
                    "scoring_preset": assignment.scoring_preset,
                    "league_size": assignment.league_size,
                    "cohort_id": assignment.cohort.cohort_id,
                    "exact": assignment.exact,
                    "sufficient": assignment.sufficient,
                    "source_format_detail": assignment.source_format_detail,
                },
            ],
        },
    )

    return FixturePipelineResult(
        registry=registry,
        batches=batches,
        market_outcomes=market_outcomes,
        sleeper_outcomes=sleeper_outcomes,
        records=records,
        build_metadata=metadata,
        gate=gate,
    )


def build_fixture_artifacts(
    *,
    fixture_dir: Path,
    out_dir: Path,
    config: AppConfig | None = None,
    generated_at: datetime | None = None,
    build_id: str = FIXTURE_BUILD_ID,
    git_sha: str | None = None,
) -> FixturePipelineResult:
    """Run the pipeline and write validated artifacts into ``out_dir``."""
    inputs = load_fixture_inputs(fixture_dir)
    result = run_fixture_pipeline(
        inputs,
        config=config,
        generated_at=generated_at,
        build_id=build_id,
        git_sha=git_sha,
    )
    now = generated_at or parse_utc(FIXTURE_GENERATED_AT)

    written: list[Path] = []
    for artifact, records in result.records.items():
        paths, checks = write_artifact(
            artifact,
            records,
            out_dir=out_dir,
            build_id=build_id,
            generated_at=now,
            arbitrage_mode=(
                result.build_metadata["arbitrage_mode"] if artifact == "arbitrage" else None
            ),
        )
        result.gate.extend(checks)
        written.extend(paths)

    # The gate summary has to reflect everything decided before it is serialized.
    result.build_metadata["quality_gate"] = result.gate.summary()
    result.build_metadata["warnings"] = result.gate.warning_messages()
    paths, checks = write_build_metadata(result.build_metadata, out_dir=out_dir)
    result.gate.extend(checks)
    written.extend(paths)

    result.gate.extend(validate_artifact_directory(out_dir).checks)
    result.written = written
    return result


# --------------------------------------------------------------------------------------
# Stub valuation. Replaced by Phases 4 and 5 - see the module docstring.
# --------------------------------------------------------------------------------------


def _projection_records(
    projection_inputs: Mapping[str, Any],
    *,
    registry: CanonicalRegistry,
    build_id: str,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for player_id, player, values in _fixture_players(projection_inputs, registry):
        records.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "model_version": FIXTURE_MODEL_VERSION,
                "season": FIXTURE_SEASON,
                "as_of_utc": isoformat_utc(generated_at),
                "player_id": player_id,
                "display_name": player.display_name,
                "team": player.team,
                "position": str(player.position),
                "scoring_preset": str(_SCORING_PRESET),
                "expected_points": values["expected_points"],
                "p10_points": values["p10_points"],
                "p25_points": values["p25_points"],
                "p50_points": values["p50_points"],
                "p75_points": values["p75_points"],
                "p90_points": values["p90_points"],
                "uncertainty_points": round(
                    (values["p90_points"] - values["p10_points"]) / 2.0,
                    2,
                ),
                "expected_games": values.get("expected_games"),
                "quality_flags": _player_flags(player),
            },
        )
    return records


@dataclass(frozen=True, slots=True)
class _ScoredPlayer:
    """One player's stub valuation, before ranking. Typed so the sort keys are checkable."""

    player_id: str
    player: CanonicalPlayer
    values: Mapping[str, float]
    expected_vorp: float
    vorp_quantiles: Mapping[str, float]

    @property
    def p50_points(self) -> float:
        return float(self.values["p50_points"])

    @property
    def spread(self) -> float:
        return float(self.values["p90_points"]) - float(self.values["p10_points"])


def _tier_records(
    projection_inputs: Mapping[str, Any],
    *,
    registry: CanonicalRegistry,
    preset: LeaguePreset,
    build_id: str,
) -> list[dict[str, Any]]:
    pool = list(_fixture_players(projection_inputs, registry))
    replacement = _replacement_points(pool, preset)

    scored = [
        _ScoredPlayer(
            player_id=player_id,
            player=player,
            values=values,
            expected_vorp=round(values["expected_points"] - replacement[player.position], 2),
            vorp_quantiles={
                f"{quantile}_vorp": round(
                    values[f"{quantile}_points"] - replacement[player.position],
                    2,
                )
                for quantile in ("p10", "p25", "p50", "p75", "p90")
            },
        )
        for player_id, player, values in pool
    ]

    # Documented tie-break (docs/DATA_CONTRACTS.md section 7): VORP, then P50 points, then
    # lower uncertainty, then a stable id. Deterministic at every step.
    scored.sort(key=lambda row: (-row.expected_vorp, -row.p50_points, row.spread, row.player_id))

    position_counts: dict[Position, int] = {}
    records: list[dict[str, Any]] = []
    tier_ordinal = 0
    previous_vorp: float | None = None
    for index, row in enumerate(scored, start=1):
        if previous_vorp is not None and (previous_vorp - row.expected_vorp) > TIER_GAP_THRESHOLD:
            tier_ordinal += 1
        previous_vorp = row.expected_vorp
        player = row.player
        position_counts[player.position] = position_counts.get(player.position, 0) + 1
        records.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "league_preset_id": preset.preset_id,
                "scoring_preset": str(_SCORING_PRESET),
                "player_id": row.player_id,
                "display_name": player.display_name,
                "team": player.team,
                "position": str(player.position),
                "fair_rank": index,
                "position_rank": position_counts[player.position],
                "tier_ordinal": tier_ordinal,
                "tier_label": f"Tier {tier_ordinal + 1}",
                "expected_vorp": row.expected_vorp,
                **row.vorp_quantiles,
                "expected_points": row.values["expected_points"],
                "uncertainty": round(row.spread / 2.0, 2),
                "quality_flags": _player_flags(player),
            },
        )
    return records


def _replacement_points(
    pool: Sequence[tuple[str, CanonicalPlayer, Mapping[str, float]]],
    preset: LeaguePreset,
) -> dict[Position, float]:
    """Points of the last startable player at each position.

    Clamped to the fixture pool, so with a 16-player fixture the baseline lands on the last
    player at each position and every preset yields the same VORP. That is the arithmetically
    correct answer for a pool this small, and it is another reason this is not a model:
    Phase 4 replaces it with simulated starter/FLEX allocation.
    """
    by_position: dict[Position, list[float]] = {}
    for _player_id, player, values in pool:
        by_position.setdefault(player.position, []).append(values["expected_points"])
    replacement: dict[Position, float] = {}
    for position, points in by_position.items():
        ordered = sorted(points, reverse=True)
        slots = preset.starters.get(str(position), 0) * preset.teams
        index = min(max(slots, 1), len(ordered))
        replacement[position] = ordered[index - 1]
    return replacement


def _arbitrage_records(
    tiers: Sequence[Mapping[str, Any]],
    *,
    market_batch: SourceBatch,
    outcomes: Sequence[ResolutionOutcome],
    assignment: CohortAssignment,
    build_id: str,
    snapshot_at: datetime,
) -> list[dict[str, Any]]:
    """The fixture's arbitrage rows, computed by the production A0 baseline.

    Phase 1 used a stub percentile here because Phase 5 did not exist. It does now, so the
    fixture drives the real thing: `ffdraft.arbitrage` computes the gaps, the score and the
    confidence, and this function only assembles the market prices to feed it. That means a
    change to A0 shows up in the golden artifacts, which is exactly what a contract fixture
    is for.
    """
    resolved = {
        outcome.external_player_id: outcome
        for outcome in outcomes
        if outcome.resolved and outcome.player_id
    }
    quotes: dict[str, tuple[Mapping[str, Any], ResolutionOutcome]] = {}
    for row in market_batch.frame.iter_rows(named=True):
        outcome = resolved.get(str(row["external_player_id"]))
        if outcome and outcome.player_id:
            quotes[outcome.player_id] = (row, outcome)

    prices: dict[tuple[str, int, str], MarketPrice] = {}
    league_sizes: dict[str, int] = {}
    for tier in tiers:
        player_id = str(tier["player_id"])
        found = quotes.get(player_id)
        if found is None:
            # An intrinsic player with no market price simply has no arbitrage row; the
            # tier board is unaffected (docs/TEST_STRATEGY.md 2.9).
            continue
        quote_row, outcome = found
        scoring = str(tier["scoring_preset"])
        league_size = assignment.league_size
        league_sizes[str(tier["league_preset_id"])] = league_size
        prices[(scoring, league_size, player_id)] = _fixture_price(
            player_id=player_id,
            scoring=scoring,
            league_size=league_size,
            row=quote_row,
            outcome=outcome,
            assignment=assignment,
            snapshot_at=snapshot_at,
        )

    # The rescued player needs a price of his own. A surfaced row only becomes an arbitrage
    # record when the priced market has an opinion about him — which is exactly why the ten
    # players that broke the first refresh were on the board at all — so the fixture prices
    # him before the market is sealed rather than surfacing someone nobody quoted.
    surfaces, surfaced_rows = _fixture_surface(tiers, assignment, snapshot_at)
    for row in surfaced_rows:
        prices[(str(row["scoring_preset"]), assignment.league_size, str(row["player_id"]))] = (
            _surfaced_price(row, assignment=assignment, snapshot_at=snapshot_at)
        )

    market = CurrentMarket(
        season=FIXTURE_SEASON,
        source_id=market_batch.source_id,
        snapshot_key=snapshot_key(snapshot_at),
        snapshot_at_utc=snapshot_at,
        prices=prices,
        assignments={(assignment.scoring_preset, assignment.league_size): assignment},
    )
    # A second market, and a player the market rescued from beyond the tier depth.
    #
    # Until this existed, *no* fixture in the repository carried either — every local gate
    # ran against a single-market bundle with no surfaced rows, so every consumer that only
    # misbehaves on the real shape was invisible until a production refresh hit it. Three
    # consecutive refreshes failed that way (ADR-067). The fixture is the check now: the
    # golden artifact has the shape production actually produces.
    extra_quotes = _fixture_ffc_quotes(tiers, prices)
    result = build_arbitrage_records(
        tiers,
        market=market,
        league_size_by_preset=league_sizes,
        build_id=build_id,
        season=FIXTURE_SEASON,
        generated_at=snapshot_at,
        gate=QualityGate(),
        extra_quotes={FFC_SOURCE_ID: extra_quotes} if extra_quotes else None,
        surfaces=surfaces or None,
        surfaced_rows=surfaced_rows,
    )
    return result.records


def _trend_series_records(
    arbitrage: Sequence[Mapping[str, Any]],
    *,
    assignment: CohortAssignment,
    source_id: str,
    build_id: str,
    snapshot_at: datetime,
) -> list[dict[str, Any]]:
    """A synthetic retained history for the fixture board (ADR-066).

    The production series comes from real snapshots taken on real days; a fixture has one
    capture, so the history is generated deterministically from each player's published ADP.
    That is enough for what this artifact is *for* here — pinning the contract, and giving
    the frontend a shape to render — and it is labelled a fixture everywhere the fixture
    build is labelled one.

    The walk is deterministic per player, so the golden artifact is byte-stable across runs:
    a fixture that changed on every build would make the golden comparison worthless.
    """
    from ffdraft.artifacts import record_schema_version
    from ffdraft.market.trend import TREND_RULE, TrendObservation, TrendResult, trend_series_records

    schema_version = record_schema_version("market_trend_series")
    days = 6
    observations: list[TrendObservation] = []
    trends: dict[str, TrendResult] = {}
    for row in arbitrage:
        player_id = str(row["player_id"])
        latest = float(row["market_adp"])
        # A gentle drift whose sign depends on the player id, so the fixture contains both
        # directions and neither is the one a test happens to look at first.
        step = 0.25 if sum(ord(char) for char in player_id) % 2 == 0 else -0.25
        for index in range(days):
            offset = days - 1 - index
            observations.append(
                TrendObservation(
                    player_id=player_id,
                    cohort_id=assignment.cohort.cohort_id,
                    observed_at=snapshot_at - timedelta(days=offset),
                    market_adp=max(0.1, latest + step * offset),
                ),
            )
        trends[player_id] = TrendResult(
            player_id=player_id,
            cohort_id=assignment.cohort.cohort_id,
            trend=round(step, 2),
            observation_days=days,
            span_days=float(days - 1),
            observations=days,
        )

    records: list[dict[str, Any]] = []
    blocks = {(str(r["league_preset_id"]), str(r["scoring_preset"])) for r in arbitrage}
    for preset_id, scoring in sorted(blocks):
        players = {
            str(r["player_id"])
            for r in arbitrage
            if str(r["league_preset_id"]) == preset_id and str(r["scoring_preset"]) == scoring
        }
        records.extend(
            trend_series_records(
                observations,
                trends=trends,
                build_id=build_id,
                market_source_id=source_id,
                scoring_preset=scoring,
                league_preset_id=preset_id,
                cohort_id=assignment.cohort.cohort_id,
                window_days=TREND_RULE.window_days,
                schema_version=schema_version,
                players=players,
            ),
        )
    return records


def _fixture_ffc_quotes(
    tiers: Sequence[Mapping[str, Any]],
    prices: Mapping[tuple[str, int, str], MarketPrice],
) -> dict[tuple[str, str], SourceQuote]:
    """A second ADP market for the fixture, derived from the first but never equal to it.

    The two markets must genuinely *disagree*, because agreement is what hid the bug: a
    fixture whose second market repeated the first would render the same number whichever
    source the page selected, and a consumer reading the wrong one would still look right.
    FFC's seven-day window prices a riser earlier than MyFantasyLeague's season aggregate,
    so the offset leans that way — and it is deterministic, because a golden artifact that
    moved between runs would be worthless to diff.

    Every third player is left unpriced on purpose: a source that covers only part of the
    board is the normal case, and the cross-market summary has to say "one market" for him
    rather than inventing a spread.
    """
    quotes: dict[tuple[str, str], SourceQuote] = {}
    for index, (key, price) in enumerate(sorted(prices.items())):
        if index % 3 == 2:
            continue
        scoring, _league_size, player_id = key
        # Deterministic, signed, and never zero: a fixed fraction of the price plus a small
        # alternating term, so some rows are cheaper on FFC and some dearer.
        offset = round(price.market_adp * 0.08 + (1.5 if index % 2 else -2.5), 1)
        adp = max(1.0, round(price.market_adp - offset, 1))
        quotes[(scoring, player_id)] = SourceQuote(
            source_id=FFC_SOURCE_ID,
            signal_type=MarketSignalType.ADP,
            player_id=player_id,
            scoring_preset=scoring,
            market_adp=adp,
            sample_size=1794,
            # FFC publishes a genuine standard deviation and no order statistics; MFL is the
            # other way round. Keeping that asymmetric in the fixture is what stops the
            # Dispersion column being written against one source's shape.
            adp_sd=round(2.0 + (index % 5), 1),
            league_size=None,
            aggregation_window_type="rolling",
            aggregation_window_days=7,
            cohort_id=f"ffc-{scoring.lower()}",
            cohort_detail=f"format={scoring.lower()}",
            snapshot_at_utc=isoformat_utc(price.snapshot_at_utc),
        )
    return quotes


def _fixture_surface(
    tiers: Sequence[Mapping[str, Any]],
    assignment: CohortAssignment,
    snapshot_at: datetime,
) -> tuple[dict[tuple[str, str], SurfaceUniverse], list[dict[str, Any]]]:
    """One player rescued from beyond the published tier depth, per block.

    Synthetic on purpose. The fixture board is far shallower than production's, so there is
    no genuine player past the depth to rescue; what matters is that the *shape* reaches the
    artifact, because it is the shape that broke three refreshes — an arbitrage row with no
    tier row, carrying `outside_tier_board` and a reason.
    """
    surfaces: dict[tuple[str, str], SurfaceUniverse] = {}
    surfaced: list[dict[str, Any]] = []
    blocks = sorted(
        {(str(row["league_preset_id"]), str(row["scoring_preset"])) for row in tiers},
    )
    for preset_id, scoring in blocks:
        block = [row for row in tiers if str(row["scoring_preset"]) == scoring]
        if not block:
            continue
        deepest = max(int(row["fair_rank"]) for row in block)
        anchor = min(block, key=lambda row: int(row["fair_rank"]))
        player_id = f"{anchor['player_id']}-surfaced"
        fair_rank = deepest + 40
        universe = SurfaceUniverse(
            scoring_preset=scoring,
            league_preset_id=preset_id,
            rule_version=SURFACE_RULE_VERSION,
            tier_depth=deepest,
            board_is_complete=True,
        )
        universe.entries[player_id] = SurfaceEntry(
            player_id=player_id,
            fair_rank=fair_rank,
            reasons=(SurfaceReason.MARKET_TOP300_FFC_ADP,),
            outside_tier_board=True,
        )
        surfaces[(preset_id, scoring)] = universe
        surfaced.append(
            {
                "player_id": player_id,
                "fair_rank": fair_rank,
                "display_name": f"{anchor.get('display_name', 'Player')} (surfaced)",
                "position": anchor.get("position"),
                "team": anchor.get("team"),
                "league_preset_id": preset_id,
                "scoring_preset": scoring,
            },
        )
    return surfaces, surfaced


def _surfaced_price(
    row: Mapping[str, Any],
    *,
    assignment: CohortAssignment,
    snapshot_at: datetime,
) -> MarketPrice:
    """The market's price for a player the model ranks past the published tier depth.

    Drafted far earlier than his fair rank, which is the whole reason the surface rule
    rescues him: a large positive `rank_gap` is what makes him worth showing.
    """
    return MarketPrice(
        player_id=str(row["player_id"]),
        scoring_preset=str(row["scoring_preset"]),
        league_size=assignment.league_size,
        market_adp=float(int(row["fair_rank"]) - 30),
        market_rank=int(row["fair_rank"]) - 30,
        sample_size=420,
        adp_low=float(int(row["fair_rank"]) - 45),
        adp_high=float(int(row["fair_rank"]) - 12),
        adp_sd=None,
        source_id=MFL_SOURCE_ID,
        cohort_id=assignment.cohort.cohort_id,
        cohort_detail=assignment.source_format_detail,
        cohort_exact=assignment.exact,
        cohort_sufficient=assignment.sufficient,
        snapshot_at_utc=snapshot_at,
        snapshot_stale=False,
        secondary_bridge_only=False,
        market_trend=None,
        trend_flags=(INSUFFICIENT_TREND_HISTORY,),
        # The same cohort flags every other price carries. A surfaced player is priced from
        # the same snapshot and the same cohort as everyone else — only his *visibility* is
        # decided differently — so a row of his that dropped `cohort_approximate` would be
        # claiming a cohort exactness the build never had.
        quality_flags=tuple(sorted({INSUFFICIENT_TREND_HISTORY, *assignment.quality_flags})),
    )


def _fixture_price(
    *,
    player_id: str,
    scoring: str,
    league_size: int,
    row: Mapping[str, Any],
    outcome: ResolutionOutcome,
    assignment: CohortAssignment,
    snapshot_at: datetime,
) -> MarketPrice:
    low = row["min_pick"]
    high = row["max_pick"]
    sample = row["sample_size"]
    secondary = FLAG_SECONDARY_ONLY in outcome.quality_flags
    flags = {*_split_flags(row["quality_flags"]), *assignment.quality_flags}
    if sample is not None and int(sample) < LOW_SAMPLE_THRESHOLD:
        flags.add(LOW_MARKET_SAMPLE)
    if low is not None and high is not None and (float(high) - float(low)) / league_size >= 5.0:
        flags.add(WIDE_MARKET_RANGE)
    if secondary:
        flags.add(SECONDARY_IDENTITY_BRIDGE_ONLY)
    # The fixture has one snapshot, so trend history can never be sufficient (ADR-042).
    flags.add(INSUFFICIENT_TREND_HISTORY)
    return MarketPrice(
        player_id=player_id,
        scoring_preset=scoring,
        league_size=league_size,
        market_adp=float(row["average_pick"]),
        market_rank=row["market_rank"],
        sample_size=None if sample is None else int(sample),
        adp_low=None if low is None else float(low),
        adp_high=None if high is None else float(high),
        adp_sd=None,
        source_id=str(row["source_id"]),
        cohort_id=assignment.cohort.cohort_id,
        cohort_detail=assignment.source_format_detail,
        cohort_exact=assignment.exact,
        cohort_sufficient=assignment.sufficient,
        snapshot_at_utc=snapshot_at,
        snapshot_stale=False,
        secondary_bridge_only=secondary,
        market_trend=None,
        trend_flags=(INSUFFICIENT_TREND_HISTORY,),
        quality_flags=tuple(sorted(flags)),
    )


def _player_status_records(
    *,
    registry: CanonicalRegistry,
    roster: pl.DataFrame,
    sleeper_batch: SourceBatch,
    build_id: str,
    generated_at: datetime,
    published: Sequence[str],
    gate: QualityGate,
) -> PlayerStatusResult:
    """The fixture's status artifact, built by the production Phase-5 code.

    The fixture's Sleeper payload deliberately includes an id whose reported ``gsis_id``
    contradicts the canonical one, so this exercises the fail-closed cross-check as well as
    the happy path (ADR-019).
    """
    capture = StatusCapture(
        source_id=sleeper_batch.source_id,
        season=FIXTURE_SEASON,
        snapshot_key=snapshot_key(generated_at),
        observed_at_utc=generated_at,
        adapter_version=SleeperPlayerAdapter.adapter_version,
        source_policy_version=SleeperPlayerAdapter.license_policy_version,
        rows=[
            {
                **row,
                "observed_at_utc": isoformat_utc(row["observed_at_utc"]),
            }
            for row in sleeper_batch.frame.iter_rows(named=True)
        ],
    )
    return build_player_status_records(
        registry=registry,
        roster=roster,
        capture=capture,
        build_id=build_id,
        season=FIXTURE_SEASON,
        generated_at=generated_at,
        player_ids=sorted(dict.fromkeys(published)),
        gate=gate,
    )


def _market_snapshot_records(
    market_batch: SourceBatch,
    *,
    outcomes: Sequence[ResolutionOutcome],
    assignment: CohortAssignment,
) -> list[dict[str, Any]]:
    resolved = {
        outcome.external_player_id: outcome.player_id
        for outcome in outcomes
        if outcome.resolved and outcome.player_id
    }
    records: list[dict[str, Any]] = []
    for row in market_batch.frame.iter_rows(named=True):
        player_id = resolved.get(str(row["external_player_id"]))
        if not player_id:
            continue
        records.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "source_id": row["source_id"],
                "snapshot_at_utc": isoformat_utc(row["retrieved_at_utc"]),
                "source_as_of_utc": None,
                "season": row["season"],
                # A quote belongs to a cohort; the preset it *serves* comes from the
                # assignment, which also records that the match is approximate (ADR-039).
                "league_size": assignment.league_size,
                "scoring_preset": assignment.scoring_preset,
                "player_id": player_id,
                "market_adp": float(row["average_pick"]),
                "market_rank": row["market_rank"],
                "sample_size": row["sample_size"],
                "adp_sd": None,
                "adp_low": row["min_pick"],
                "adp_high": row["max_pick"],
                "source_format_detail": assignment.source_format_detail,
                "quality_flags": sorted(
                    {*_split_flags(row["quality_flags"]), *assignment.quality_flags},
                ),
            },
        )
    return records


# --------------------------------------------------------------------------------------
# Metadata and helpers
# --------------------------------------------------------------------------------------


def _published_identity_checks(
    records: Mapping[str, Sequence[Mapping[str, Any]]],
    outcomes: Sequence[ResolutionOutcome],
) -> list[QualityCheck]:
    """`docs/DATA_CONTRACTS.md` section 12: zero ambiguous identities in public output.

    Ambiguity is expected at the resolution stage - the fixtures create it on purpose. What
    must never happen is an ambiguous record reaching a published artifact.
    """
    ambiguous_ids = {
        outcome.external_player_id for outcome in outcomes if outcome.status.value == "ambiguous"
    }
    if not ambiguous_ids:
        return [
            QualityCheck.ok(
                "public.no_ambiguous_identities",
                stage="artifacts",
                message="no ambiguous identities were produced",
                observed="0",
            ),
        ]
    leaked = [
        f"{artifact}:{record.get('player_id')}"
        for artifact, rows in records.items()
        for record in rows
        if str(record.get("player_id", "")).split(":", 1)[-1] in ambiguous_ids
    ]
    if leaked:
        return [
            QualityCheck.fail(
                "public.ambiguous_identity_published",
                stage="artifacts",
                message="an ambiguous identity reached a public artifact",
                observed="; ".join(leaked[:10]),
                expected="0",
            ),
        ]
    return [
        QualityCheck.ok(
            "public.no_ambiguous_identities",
            stage="artifacts",
            message="ambiguous identities were excluded from public artifacts",
            observed=f"{len(ambiguous_ids)} excluded",
        ),
    ]


def _build_metadata(
    app: AppConfig,
    *,
    batches: Mapping[str, SourceBatch],
    gate: QualityGate,
    build_id: str,
    generated_at: datetime,
    git_sha: str,
    presets: Sequence[str],
    status: PlayerStatusResult | None = None,
    market: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for batch in batches.values():
        entry = batch.metadata.build_metadata_entry()
        existing = seen.get(entry["source_id"])
        if existing is None:
            seen[entry["source_id"]] = entry
        else:
            # One source can contribute several resources; report the aggregate.
            existing["record_count"] += entry["record_count"]
            existing["warnings"] = sorted({*existing["warnings"], *entry["warnings"]})
            if entry["status"] != "pass":
                existing["status"] = entry["status"]
            # Keep the most recent genuine data-as-of time rather than whichever resource
            # happened to be loaded first; several resources share one source_id and only
            # some of them publish one at all.
            candidates = [
                value
                for value in (existing["source_as_of_utc"], entry["source_as_of_utc"])
                if value
            ]
            existing["source_as_of_utc"] = max(candidates) if candidates else None
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "build_id": build_id,
        "generated_at_utc": isoformat_utc(generated_at),
        "git_sha": git_sha,
        "season": FIXTURE_SEASON,
        "intrinsic_model_version": FIXTURE_MODEL_VERSION,
        "arbitrage_mode": app.arbitrage_mode,
        "arbitrage_model_version": None,
        "arbitrage_method_version": ARBITRAGE_METHOD_VERSION,
        "market": dict(market) if market is not None else None,
        "player_status": status.summary() if status is not None else None,
        "supported_presets": list(presets),
        "sources": [seen[key] for key in sorted(seen)],
        "quality_gate": gate.summary(),
        "warnings": gate.warning_messages(),
        "methodology_version": FIXTURE_METHODOLOGY_VERSION,
    }


def _fixture_players(
    projection_inputs: Mapping[str, Any],
    registry: CanonicalRegistry,
) -> list[tuple[str, CanonicalPlayer, dict[str, float]]]:
    """Fixture projections joined to canonical players, in deterministic id order."""
    scoring = str(_SCORING_PRESET)
    rows: list[tuple[str, CanonicalPlayer, dict[str, float]]] = []
    for gsis_id, by_preset in sorted(projection_inputs["players"].items()):
        player_id = f"gsis:{gsis_id}"
        player = registry.get(player_id)
        if player is None or player.entity_kind is not EntityKind.PLAYER:
            continue
        values = by_preset.get(scoring)
        if values is None:
            continue
        rows.append((player_id, player, dict(values)))
    return rows


def _player_flags(player: CanonicalPlayer) -> list[str]:
    flags: list[str] = []
    if player.status and player.status != "ACT":
        flags.append(f"roster_status_{player.status.lower()}")
    if player.rookie_season == FIXTURE_SEASON:
        flags.append("rookie")
    if not player.crosswalk.sleeper_id:
        flags.append("no_sleeper_status")
    return flags


def _split_flags(value: str | None) -> list[str]:
    if not value:
        return []
    return [flag for flag in value.split(",") if flag]


def _mapping(frame: pl.DataFrame, key: str, value: str) -> dict[str, str]:
    return {
        str(row[key]): str(row[value])
        for row in frame.select(key, value).iter_rows(named=True)
        if row[key] is not None and row[value] is not None
    }


def _git_sha() -> str:
    """Best-effort repository SHA. Falls back to a placeholder outside a checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "0000000"
    return result.stdout.strip() or "0000000"
