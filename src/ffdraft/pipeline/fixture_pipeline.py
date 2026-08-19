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
* the arbitrage score is a linear transform of the rank gap, not the Phase-5 baseline.

Every artifact it writes records ``intrinsic_model_version="fixture-stub-0"`` so a stub
build can never be mistaken for production output. Phases 4 and 5 replace the stub sections;
the identity, contract, quality and serialization code they feed is production code.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

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
    Confidence,
    EntityKind,
    MarketCohort,
    Position,
    QualityCheck,
    ResolutionOutcome,
    Severity,
    SourceBatch,
)
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
from ffdraft.quality import QualityGate, check_source_freshness
from ffdraft.quality.forbidden import (
    audit_intrinsic_feature_names,
    audit_intrinsic_source_lineage,
)
from ffdraft.quality.thresholds import MARKET_SOURCE_MAX_AGE
from ffdraft.sources import (
    NflverseDepthChartAdapter,
    NflversePlayerIdsAdapter,
    NflverseRosterAdapter,
    SleeperPlayerAdapter,
)
from ffdraft.sources.market import MflAdpAdapter, MflPlayerDirectory, MflPlayerDirectoryAdapter
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

    cohort = MarketCohort(
        scoring_preset=str(_SCORING_PRESET),
        league_size=app.league.default_preset.teams,
        filters={},
        approximate=True,
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
        cohort=cohort,
    )
    arbitrage = _arbitrage_records(
        tiers,
        market_batch=market_batch,
        outcomes=market_outcomes,
        registry=registry,
        build_id=build_id,
        arbitrage_mode=app.arbitrage_mode,
    )

    records = {
        "projections": projections,
        "tiers": tiers,
        "arbitrage": arbitrage,
        "market_snapshot": market_records,
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
    registry: CanonicalRegistry,
    build_id: str,
    arbitrage_mode: str,
) -> list[dict[str, Any]]:
    resolved = {
        outcome.external_player_id: outcome.player_id
        for outcome in outcomes
        if outcome.resolved and outcome.player_id
    }
    quotes: dict[str, Mapping[str, Any]] = {}
    for row in market_batch.frame.iter_rows(named=True):
        player_id = resolved.get(str(row["external_player_id"]))
        if player_id:
            quotes[player_id] = row

    priced = [
        (tier, quotes[str(tier["player_id"])]) for tier in tiers if str(tier["player_id"]) in quotes
    ]
    gaps = {
        str(tier["player_id"]): round(float(quote["average_pick"]) - int(tier["fair_rank"]), 2)
        for tier, quote in priced
    }
    scores = _percentile_scores(gaps)

    records: list[dict[str, Any]] = []
    for tier, quote in priced:
        # An intrinsic player with no market price simply has no arbitrage row; the tier
        # board is unaffected (docs/TEST_STRATEGY.md 2.9).
        market_adp = float(quote["average_pick"])
        rank_gap = gaps[str(tier["player_id"])]
        records.append(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "build_id": build_id,
                "league_preset_id": tier["league_preset_id"],
                "scoring_preset": tier["scoring_preset"],
                "player_id": tier["player_id"],
                "display_name": tier["display_name"],
                "team": tier["team"],
                "position": tier["position"],
                "fair_rank": tier["fair_rank"],
                "market_adp": market_adp,
                "market_rank": quote["market_rank"],
                "rank_gap": rank_gap,
                "arbitrage_mode": arbitrage_mode,
                "arbitrage_score": scores[str(tier["player_id"])],
                # ADR-010: baseline mode publishes no learned-model fields.
                "expected_surplus_vorp": None,
                "p_positive_surplus": None,
                "market_trend": None,
                "market_sample_size": quote["sample_size"],
                # MFL publishes no standard deviation, so this stays null (Phase-0 13.5).
                "market_adp_sd": None,
                "confidence": str(_confidence(quote["sample_size"])),
                "quality_flags": _split_flags(quote["quality_flags"]),
            },
        )
    return records


def _percentile_scores(gaps: Mapping[str, float]) -> dict[str, float]:
    """Rank the gaps into the schema's 0-100 band. A stub transform, not a model.

    A percentile rather than an affine transform of the gap, because the gap's scale
    depends on how deep the market board runs: a 16-player fixture priced against a
    250-pick board produces gaps in the hundreds, and any fixed linear mapping would pin
    most rows at 100 and tell a reader nothing. A percentile always spreads, is monotone in
    the gap, and is obviously relative - which is the honest description of a stub. Phase 5
    replaces it with the deterministic A0 baseline.
    """
    if not gaps:
        return {}
    ordered = sorted(gaps.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    return {
        player_id: round(100.0 * (index + 0.5) / count, 2)
        for index, (player_id, _gap) in enumerate(ordered)
    }


def _confidence(sample_size: int | None) -> Confidence:
    if sample_size is None or sample_size <= 0:
        return Confidence.UNKNOWN
    if sample_size >= 100:
        return Confidence.HIGH
    if sample_size >= 30:
        return Confidence.MEDIUM
    return Confidence.LOW


def _market_snapshot_records(
    market_batch: SourceBatch,
    *,
    outcomes: Sequence[ResolutionOutcome],
    cohort: MarketCohort,
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
                "league_size": row["league_size"],
                "scoring_preset": row["scoring_preset"],
                "player_id": player_id,
                "market_adp": float(row["average_pick"]),
                "market_rank": row["market_rank"],
                "sample_size": row["sample_size"],
                "adp_sd": None,
                "adp_low": row["min_pick"],
                "adp_high": row["max_pick"],
                "source_format_detail": cohort.source_format_detail,
                "quality_flags": _split_flags(row["quality_flags"]),
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
