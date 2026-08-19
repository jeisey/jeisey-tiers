"""The current-season production build, end to end and network-free.

Two halves, tested separately because they fail for different reasons.

The **front half** - sources, information cutoff, current status - is driven from the
committed historical fixtures with a build timestamp deliberately set before the season's
draft anchor, which is the situation a real August refresh is in.

The **back half** - sampling, allocation, ranking, segmentation, record shape, artifact
validation - is driven from a synthetic pool big enough for a twelve-team league to have
someone left on the bench. The fixture universe is thirty players, which cannot fill a
league and therefore cannot exercise replacement at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from ffdraft.artifacts import validate_artifact_directory, write_artifact, write_build_metadata
from ffdraft.config import load_app_config
from ffdraft.features.sources import load_fixture_sources
from ffdraft.modeling.calibration import MonotoneOnly
from ffdraft.modeling.folds import DEFAULT_SEED
from ffdraft.modeling.production import (
    ARCHITECTURE_HURDLE,
    ProductionSpec,
    train_production_model,
)
from ffdraft.paths import repo_root
from ffdraft.pipeline.current import (
    CURRENT_CUTOFF_RULE_VERSION,
    RETIRED_STATUS,
    CurrentBuildConfig,
    build_board_records,
    current_cutoff,
    run_current_build,
)
from ffdraft.quality import QualityGate

FIXTURE_SEASON = 2025
BEFORE_THE_ANCHOR = datetime(2025, 8, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def fixture_sources():
    return load_fixture_sources(repo_root() / "tests" / "fixtures" / "historical")


@pytest.fixture(scope="module")
def app_config():
    return load_app_config()


@pytest.fixture(scope="module")
def production_model(synthetic_modeling_dataset, tmp_path_factory):
    spec = ProductionSpec(
        model_version="test-current-v1",
        architecture=ARCHITECTURE_HURDLE,
        calibration_strategy_id=MonotoneOnly().strategy_id,
        target_scale_id="season_total",
        seed=DEFAULT_SEED,
        composition_draws=200,
        num_boost_round=30,
    )
    frame = synthetic_modeling_dataset.frame.filter(pl.col("season") <= 2022)
    model = train_production_model(frame, spec=spec, git_sha="0000000")
    directory = tmp_path_factory.mktemp("model")
    model.save(directory)
    return model, directory


def _config(**overrides: object) -> CurrentBuildConfig:
    payload: dict[str, object] = {
        "draws": 120,
        "ranking_statistic": "median_vorp",
        "tier_penalty": 3.0,
        "board_depth": 300,
        "seed": DEFAULT_SEED,
    }
    payload.update(overrides)
    return CurrentBuildConfig(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# The information cutoff
# ---------------------------------------------------------------------------------------


def test_a_build_before_the_anchor_uses_its_own_timestamp(fixture_sources) -> None:
    from ffdraft.anchors import build_season_anchors

    anchor = build_season_anchors(fixture_sources.sources.schedule, [FIXTURE_SEASON])[
        FIXTURE_SEASON
    ]
    cutoff = current_cutoff(anchor, BEFORE_THE_ANCHOR)
    assert cutoff.rule_version == CURRENT_CUTOFF_RULE_VERSION
    assert cutoff.anchor_at_utc == BEFORE_THE_ANCHOR
    assert cutoff.anchor_at_utc < anchor.anchor_at_utc


def test_a_build_after_the_anchor_still_stops_at_the_anchor(fixture_sources) -> None:
    """A September refresh must not mean something different by 'draft time' than August did."""
    from ffdraft.anchors import DRAFT_ANCHOR_RULE_VERSION, build_season_anchors

    anchor = build_season_anchors(fixture_sources.sources.schedule, [FIXTURE_SEASON])[
        FIXTURE_SEASON
    ]
    later = datetime(2025, 12, 1, tzinfo=UTC)
    cutoff = current_cutoff(anchor, later)
    assert cutoff.rule_version == DRAFT_ANCHOR_RULE_VERSION
    assert cutoff.anchor_at_utc == anchor.anchor_at_utc


def test_the_build_records_which_cutoff_applied(
    fixture_sources,
    production_model,
    app_config,
    tmp_path,
) -> None:
    _, model_dir = production_model
    result = run_current_build(
        season=FIXTURE_SEASON,
        model_dir=model_dir,
        out_dir=tmp_path / "artifacts",
        config=_config(),
        as_of=BEFORE_THE_ANCHOR,
        sources=fixture_sources,
        app=app_config,
        write=False,
    )
    assert result.cutoff.rule_version == CURRENT_CUTOFF_RULE_VERSION
    cutoff_check = next(
        check for check in result.gate.checks if check.check_id == "current.information_cutoff"
    )
    assert "as_of=" in cutoff_check.observed
    assert result.model_version == "test-current-v1"


def test_the_build_refuses_a_model_built_on_another_feature_contract(
    fixture_sources,
    production_model,
    app_config,
    tmp_path,
) -> None:
    from ffdraft.modeling.production import METADATA_FILE, FeatureSchemaMismatch

    _, model_dir = production_model
    corrupted = tmp_path / "corrupted"
    corrupted.mkdir()
    for path in model_dir.rglob("*"):
        target = corrupted / path.relative_to(model_dir)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    metadata_path = corrupted / METADATA_FILE
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload["feature_set_hash"] = "0123456789abcdef"
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FeatureSchemaMismatch):
        run_current_build(
            season=FIXTURE_SEASON,
            model_dir=corrupted,
            out_dir=tmp_path / "artifacts",
            config=_config(),
            as_of=BEFORE_THE_ANCHOR,
            sources=fixture_sources,
            app=app_config,
            write=False,
        )


def test_current_status_excludes_only_the_retired(
    fixture_sources,
    production_model,
    app_config,
    tmp_path,
) -> None:
    """Absence from a roster is not evidence of absence from the league."""
    from ffdraft.pipeline.current import _current_status

    roster = pl.DataFrame(
        {
            "gsis_id": ["00-0000001", "00-0000002", "00-0000003"],
            "status": [RETIRED_STATUS, "RES", "ACT"],
            "team": ["KC", "SF", "BUF"],
        },
    )
    status = _current_status(roster).sort("player_id")
    assert status.get_column("player_id").to_list() == [
        "gsis:00-0000001",
        "gsis:00-0000002",
        "gsis:00-0000003",
    ]
    assert status.get_column("current_status").to_list() == [RETIRED_STATUS, "RES", "ACT"]

    _, model_dir = production_model
    result = run_current_build(
        season=FIXTURE_SEASON,
        model_dir=model_dir,
        out_dir=tmp_path / "artifacts",
        config=_config(),
        as_of=BEFORE_THE_ANCHOR,
        sources=fixture_sources,
        app=app_config,
        write=False,
    )
    check = next(item for item in result.gate.checks if item.check_id == "current.status_filter")
    assert "excluded of" in check.observed


# ---------------------------------------------------------------------------------------
# The value chain
# ---------------------------------------------------------------------------------------


def _pool(model, count: int = 260, seed: int = 5) -> tuple[pl.DataFrame, pl.DataFrame]:
    """A pool large enough that a twelve-team league leaves somebody on the bench."""
    generator = np.random.default_rng(seed)
    positions = (["QB"] * 45 + ["RB"] * 75 + ["WR"] * 95 + ["TE"] * 45)[:count]
    centre = np.sort(generator.uniform(0.0, 320.0, size=len(positions)))[::-1]
    spread = generator.uniform(25.0, 95.0, size=len(positions))
    offsets = np.array([-1.28, -0.67, 0.0, 0.67, 1.28])
    quantiles = centre[:, None] + spread[:, None] * offsets[None, :]
    ids = [f"gsis:00-{index:07d}" for index in range(len(positions))]

    projections = pl.concat(
        [
            pl.DataFrame(
                {
                    "player_id": ids,
                    "position": positions,
                    "scoring_preset": [preset] * len(positions),
                    **{
                        f"p{level}_points": quantiles[:, index]
                        for index, level in enumerate(["10", "25", "50", "75", "90"])
                    },
                },
            )
            for preset in ("STD", "HALF", "PPR")
        ],
    )
    context = pl.DataFrame(
        {
            "player_id": ids,
            "display_name": [f"Player {index}" for index in range(len(positions))],
            "position": positions,
            "team": ["KC"] * len(positions),
            "current_status": ["ACT"] * len(positions),
            "rookie_flag": [index % 9 == 0 for index in range(len(positions))],
            "has_prior_season_stats": [index % 9 != 0 for index in range(len(positions))],
            "depth_context_state": ["prior_season_role_proxy"] * len(positions),
        },
    )
    del model
    return projections, context


def _records(production_model, app_config, build_id: str = "test-build"):
    model, _ = production_model
    projections, context = _pool(model)
    gate = QualityGate()
    records, diagnostics = build_board_records(
        projections,
        context,
        settings=app_config,
        config=_config(),
        model=model,
        season=2026,
        build_id=build_id,
        as_of=datetime(2026, 8, 1, tzinfo=UTC),
        gate=gate,
    )
    return records, diagnostics, gate


def test_every_launch_preset_gets_a_board(production_model, app_config) -> None:
    records, diagnostics, gate = _records(production_model, app_config)
    presets = {(row["league_preset_id"], row["scoring_preset"]) for row in records["tiers"]}
    assert presets == {
        (league, scoring)
        for league in ("redraft-10", "redraft-12", "redraft-14")
        for scoring in ("STD", "HALF", "PPR")
    }
    assert len(diagnostics["presets"]) == 9
    assert not gate.critical_failures


def test_fair_ranks_are_unique_and_tiers_contiguous(production_model, app_config) -> None:
    records, _, _ = _records(production_model, app_config)
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in records["tiers"]:
        grouped.setdefault((row["league_preset_id"], row["scoring_preset"]), []).append(row)
    for rows in grouped.values():
        ranks = [int(row["fair_rank"]) for row in rows]
        assert sorted(ranks) == list(range(1, len(ranks) + 1))
        ordered = sorted(rows, key=lambda row: int(row["fair_rank"]))
        ordinals = [int(row["tier_ordinal"]) for row in ordered]
        assert ordinals == sorted(ordinals)
        assert ordinals[0] == 0


def test_position_ranks_are_dense_within_each_position(production_model, app_config) -> None:
    records, _, _ = _records(production_model, app_config)
    board = [
        row
        for row in records["tiers"]
        if row["league_preset_id"] == "redraft-12" and row["scoring_preset"] == "PPR"
    ]
    by_position: dict[str, list[int]] = {}
    for row in board:
        by_position.setdefault(str(row["position"]), []).append(int(row["position_rank"]))
    for ranks in by_position.values():
        assert sorted(ranks) == list(range(1, len(ranks) + 1))


def test_league_size_changes_the_board(production_model, app_config) -> None:
    records, _, _ = _records(production_model, app_config)

    def vorp(preset: str) -> dict[str, float]:
        return {
            str(row["player_id"]): float(row["expected_vorp"])
            for row in records["tiers"]
            if row["league_preset_id"] == preset and row["scoring_preset"] == "PPR"
        }

    ten, fourteen = vorp("redraft-10"), vorp("redraft-14")
    shared = set(ten) & set(fourteen)
    assert shared
    assert any(abs(ten[key] - fourteen[key]) > 1e-6 for key in shared)


def test_the_artifacts_validate(production_model, app_config, tmp_path) -> None:
    records, _, _ = _records(production_model, app_config)
    generated = datetime(2026, 8, 1, tzinfo=UTC)
    out_dir = tmp_path / "artifacts"
    for artifact, rows in sorted(records.items()):
        paths, checks = write_artifact(
            artifact,
            rows,
            out_dir=out_dir,
            build_id="test-build",
            generated_at=generated,
            arbitrage_mode="baseline",
        )
        assert paths, [check.to_dict() for check in checks if check.blocking]
    metadata = {
        "schema_version": "1.0",
        "build_id": "test-build",
        "generated_at_utc": "2026-08-01T00:00:00Z",
        "git_sha": "0000000",
        "season": 2026,
        "intrinsic_model_version": "test-current-v1",
        "arbitrage_mode": "baseline",
        "arbitrage_model_version": None,
        "supported_presets": ["redraft-10", "redraft-12", "redraft-14"],
        "sources": [],
        "quality_gate": {"status": "pass", "critical_failures": 0, "warnings": 0},
        "warnings": [],
        "methodology_version": "test-current-v1",
    }
    paths, checks = write_build_metadata(metadata, out_dir=out_dir)
    assert paths, [check.to_dict() for check in checks if check.blocking]

    gate = validate_artifact_directory(out_dir)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


def test_the_build_is_byte_reproducible(production_model, app_config, tmp_path) -> None:
    """Identical model, build id, seed and inputs produce identical files."""
    generated = datetime(2026, 8, 1, tzinfo=UTC)
    digests: list[list[bytes]] = []
    for run in ("a", "b"):
        records, _, _ = _records(production_model, app_config)
        out_dir = tmp_path / run
        for artifact, rows in sorted(records.items()):
            write_artifact(
                artifact,
                rows,
                out_dir=out_dir,
                build_id="test-build",
                generated_at=generated,
                arbitrage_mode="baseline",
            )
        digests.append([path.read_bytes() for path in sorted(out_dir.iterdir())])
    assert digests[0] == digests[1]


def test_quality_flags_reach_the_records(production_model, app_config) -> None:
    records, _, _ = _records(production_model, app_config)
    flags = {flag for row in records["tiers"] for flag in row["quality_flags"]}
    assert "rookie" in flags
    assert "no_prior_season_stats" in flags


def test_a_supplied_roster_excludes_the_retired_and_flags_the_rest(
    fixture_sources,
    production_model,
    app_config,
    tmp_path,
) -> None:
    """The exclusion needs positive evidence, and everything else is an annotation."""
    _, model_dir = production_model
    universe = fixture_sources.sources.rosters[FIXTURE_SEASON - 1]
    ids = universe.get_column("gsis_id").to_list()[:4]
    roster = pl.DataFrame(
        {
            "gsis_id": ids,
            "status": [RETIRED_STATUS, "RES", "ACT", "CUT"][: len(ids)],
            "team": ["KC", "SF", "BUF", "NYJ"][: len(ids)],
        },
    )
    result = run_current_build(
        season=FIXTURE_SEASON,
        model_dir=model_dir,
        out_dir=tmp_path / "artifacts",
        config=_config(),
        as_of=BEFORE_THE_ANCHOR,
        sources=fixture_sources,
        current_roster=roster,
        app=app_config,
        write=False,
    )
    check = next(item for item in result.gate.checks if item.check_id == "current.status_filter")
    excluded = int(check.observed.split()[0])
    assert excluded >= 1
    flags = {flag for row in result.records["projections"] for flag in row["quality_flags"]}
    assert "no_current_roster_entry" in flags
    published = {row["player_id"] for row in result.records["projections"]}
    assert f"gsis:{ids[0]}" not in published


def test_no_roster_means_nothing_is_excluded_and_the_gate_says_so(
    fixture_sources,
    production_model,
    app_config,
    tmp_path,
) -> None:
    _, model_dir = production_model
    result = run_current_build(
        season=FIXTURE_SEASON,
        model_dir=model_dir,
        out_dir=tmp_path / "artifacts",
        config=_config(),
        as_of=BEFORE_THE_ANCHOR,
        sources=fixture_sources,
        app=app_config,
        write=False,
    )
    warning = next(
        item for item in result.gate.checks if item.check_id == "current.roster_status_unavailable"
    )
    assert not warning.blocking
    assert "0 excluded" in next(
        item.observed for item in result.gate.checks if item.check_id == "current.status_filter"
    )


def test_the_current_build_never_loads_the_target_seasons_statistics() -> None:
    """Before the season they do not exist; during it they are the outcome being predicted."""
    from ffdraft.features.sources import season_windows

    current = season_windows([2026], include_target_statistics=False)
    assert 2026 not in current.statistics
    assert current.rosters == (2025,)
    assert current.depth_charts == (2026,)

    historical = season_windows([2026])
    assert 2026 in historical.statistics
