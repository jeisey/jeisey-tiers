"""Shared test fixtures.

`scripts/` is still imported by path because the Phase-0 probe is a script, not a package
module. Everything Phase 1 added is imported normally from the installed ``ffdraft``
package, so a test failing on import means the package is genuinely broken rather than a
path shim being wrong.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.features.dictionary import FEATURE_DICTIONARY

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures"
PIPELINE_FIXTURES = FIXTURE_DIR / "pipeline"
SOURCE_SCHEMA_FIXTURES = FIXTURE_DIR / "source_schemas"
HISTORICAL_FIXTURES = FIXTURE_DIR / "historical"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def pipeline_fixture_dir() -> Path:
    return PIPELINE_FIXTURES


@pytest.fixture(scope="session")
def app_config():
    from ffdraft.config import load_app_config

    # An explicit empty environment: no test may read a provisioned secret (ADR-017).
    return load_app_config(root=REPO_ROOT, environ={})


@pytest.fixture(scope="session")
def fixture_inputs():
    from ffdraft.pipeline import load_fixture_inputs

    return load_fixture_inputs(PIPELINE_FIXTURES)


@pytest.fixture(scope="session")
def pipeline_result(fixture_inputs, app_config):
    from ffdraft.pipeline import run_fixture_pipeline

    return run_fixture_pipeline(fixture_inputs, config=app_config, git_sha="0000000")


@pytest.fixture(scope="session")
def built_artifacts(tmp_path_factory, app_config) -> Path:
    """Run the full fixture pipeline once and hand every test the same output directory."""
    from ffdraft.pipeline import build_fixture_artifacts

    out_dir = tmp_path_factory.mktemp("artifacts")
    build_fixture_artifacts(
        fixture_dir=PIPELINE_FIXTURES,
        out_dir=out_dir,
        config=app_config,
        git_sha="0000000",
    )
    return out_dir


@pytest.fixture(scope="session")
def read_source_schema():
    """Return a loader for the Phase-0 recorded upstream schemas.

    Adapters are written against these, so tests read them here rather than restating the
    upstream column list - a restated list would drift from the evidence it stands in for.
    """

    def load(name: str) -> dict[str, Any]:
        path = SOURCE_SCHEMA_FIXTURES / f"{name}.schema.json"
        return json.loads(path.read_text(encoding="utf-8"))

    return load


@pytest.fixture(scope="session")
def historical_fixture_dir() -> Path:
    return HISTORICAL_FIXTURES


@pytest.fixture(scope="session")
def historical_sources():
    """The synthetic historical sources, normalized through the real adapters."""
    from ffdraft.features.sources import load_fixture_sources

    return load_fixture_sources(HISTORICAL_FIXTURES)


@pytest.fixture(scope="session")
def historical_dataset(historical_sources, app_config):
    """One fixture-driven historical build, shared by every test that reads it.

    Built under :meth:`HistoricalThresholds.fixture` because the fixture deliberately
    contains a player with no birth date anywhere and is far too small for a production
    coverage threshold to mean anything - the same reasoning Phase 1 recorded for the
    16-player artifact fixture.
    """
    from ffdraft.features.sources import FIXTURE_TARGET_SEASONS
    from ffdraft.pipeline import build_historical_dataset
    from ffdraft.quality.thresholds import HistoricalThresholds
    from ffdraft.timeutil import parse_utc

    return build_historical_dataset(
        historical_sources.sources,
        config=app_config,
        seasons=FIXTURE_TARGET_SEASONS,
        generated_at=parse_utc("2026-01-01T00:00:00Z"),
        git_sha="0000000",
        thresholds=HistoricalThresholds.fixture(),
    )


@pytest.fixture(scope="session")
def historical_features(historical_dataset):
    return historical_dataset.features


# --------------------------------------------------------------------------------------
# Synthetic modelling fixtures
#
# The modelling tests must run without the real historical dataset, which is gitignored and
# takes minutes of nflverse downloads to rebuild. They therefore drive the real feature
# dictionary, the real join, the real folds and the real models over a small synthetic table
# whose signal is known by construction. They live in the root conftest because Phase 4's
# integration tests need a trained production model too, and a model needs a training set.
#
# The synthetic seasons deliberately include 2025, so every seal test exercises the same code
# path a real run would, against a season that is genuinely sealed.
# --------------------------------------------------------------------------------------

SYNTHETIC_SEASONS: tuple[int, ...] = tuple(range(2014, 2026))
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")
SCORING_PRESETS: tuple[str, ...] = ("STD", "HALF", "PPR")
PLAYERS_PER_POSITION = 40


def _blank(dtype: pl.DataType | type[pl.DataType]) -> object:
    if dtype == pl.Boolean:
        return False
    if dtype == pl.String:
        return "unknown"
    return None


def _varied(
    dtype: pl.DataType | type[pl.DataType],
    generator: np.random.Generator,
    index: int,
) -> object:
    if dtype == pl.Boolean:
        return bool(index % 2 == 0)
    if dtype == pl.Int32:
        return int(generator.integers(0, 12))
    return float(generator.normal(0.0, 1.0))


def synthetic_features(
    seasons: Sequence[int] = SYNTHETIC_SEASONS,
    players_per_position: int = PLAYERS_PER_POSITION,
    *,
    seed: int = 7,
) -> pl.DataFrame:
    """A feature table with every declared column and a known signal in a few of them."""
    generator = np.random.default_rng(seed)
    schema = {spec.name: spec.dtype for spec in FEATURE_DICTIONARY}
    rows: list[dict[str, object]] = []
    for season in seasons:
        for position in POSITIONS:
            for index in range(players_per_position):
                skill = float(generator.normal(0.0, 1.0))
                rookie = index % 8 == 0
                drafted = index % 5 != 0
                games = 0.0 if rookie else float(generator.integers(1, 17))
                base_rate = max(0.0, 8.0 + 3.0 * skill)
                row: dict[str, object] = {}
                for spec in FEATURE_DICTIONARY:
                    if spec.role.is_model_input and spec.dtype != pl.String:
                        # Give every model input some spread, so the era-stability audit is
                        # exercised rather than tripping over an artificially empty fixture.
                        # The explicit overrides below then restore the missingness and the
                        # era shape that actually matter.
                        row[spec.name] = _varied(spec.dtype, generator, index)
                    else:
                        row[spec.name] = _blank(spec.dtype)
                row.update(
                    {
                        "season": season,
                        "player_id": f"gsis:00-{position}{index:04d}",
                        "anchor_at_utc": None,
                        "feature_cutoff_rule_version": "draft_anchor_v1_tuesday_eod_pre_week1",
                        "gsis_id": f"00-{position}{index:04d}",
                        "display_name": f"{position} Player {index}",
                        "position": position,
                        "position_source": "roster",
                        "eligibility_basis": ("draft_class" if rookie else "prior_season_roster"),
                        "universe_era": ("snapshot_2025_plus" if season >= 2025 else "lagged_only"),
                        "depth_context_state": (
                            "depth_unavailable" if rookie else "prior_season_role_proxy"
                        ),
                        "rookie_flag": rookie,
                        "has_prior_season_stats": not rookie,
                        "prev1_games": None if rookie else int(games),
                        "prev1_team_games": None if rookie else 16,
                        "prev1_games_missed": None if rookie else max(0, 16 - int(games)),
                        "prev1_fantasy_ppg_std": None if rookie else base_rate,
                        "prev1_fantasy_ppg_ppr": None if rookie else base_rate + 1.5,
                        "prev1_fantasy_points_std": None if rookie else base_rate * games,
                        "prev1_fantasy_points_ppr": None if rookie else (base_rate + 1.5) * games,
                        "prev1_targets_pg": None if rookie else max(0.0, 4.0 + skill),
                        "prev1_carries_pg": None if rookie else max(0.0, 5.0 + skill),
                        "prev1_snap_share": None if rookie else min(1.0, max(0.0, 0.5 + skill / 5)),
                        # A handful of players have no published birth date, exactly as
                        # upstream: age is missing rather than guessed.
                        "age_at_anchor": None if index % 17 == 0 else float(22 + (index % 12)),
                        "age_at_anchor_known": index % 17 != 0,
                        "position_age_z": float(skill / 2),
                        # Unknown experience belongs to veterans, exactly as it does
                        # upstream: 510 rows of the 2016 roster publish no `years_exp`.
                        "experience_years": (
                            0 if rookie else (None if index % 11 == 0 else int(1 + index % 9))
                        ),
                        "experience_years_known": rookie or index % 11 != 0,
                        "drafted_flag": drafted,
                        "draft_round": int(1 + index % 7) if drafted else None,
                        "draft_overall": int(1 + index * 4) if drafted else None,
                        "draft_year": season - (index % 9) if drafted else None,
                        "seasons_since_draft": int(index % 9) if drafted else None,
                        "prior5_seasons": 0 if rookie else int(1 + index % 5),
                        "prior5_games": 0 if rookie else int(games * 2),
                        "prior_season_role_known": not rookie,
                        "prior_season_role_rank": None if rookie else int(1 + index % 6),
                        "combine_observed_flag": index % 3 == 0,
                        "height_in": float(70 + index % 8),
                        "weight_lb": float(190 + index % 40),
                        "team_at_anchor_known": season >= 2025,
                        "team_change_known": season >= 2025,
                        "team_change_flag": bool(index % 4 == 0) if season >= 2025 else None,
                        "depth_rank_observed": season >= 2025,
                        "depth_rank_at_anchor": int(1 + index % 5) if season >= 2025 else None,
                        "prev1_rush_denominator_met": not rookie,
                        "prev1_target_denominator_met": not rookie,
                        "prev1_pass_denominator_met": position == "QB" and not rookie,
                    },
                )
                rows.append(row)
    frame = pl.DataFrame(rows, schema=schema)
    return frame


def synthetic_labels(features: pl.DataFrame, *, seed: int = 11) -> pl.DataFrame:
    """Labels with a real, learnable relationship to the feature signal."""
    generator = np.random.default_rng(seed)
    records: list[dict[str, object]] = []
    for row in features.iter_rows(named=True):
        rate = row["prev1_fantasy_ppg_ppr"]
        games = row["prev1_games"] or 0
        draft = row["draft_round"] or 8
        for preset in SCORING_PRESETS:
            bonus = {"STD": 0.0, "HALF": 8.0, "PPR": 16.0}[preset]
            signal = (
                12.0 * float(rate if rate is not None else 4.0)
                + 1.5 * float(games)
                - 4.0 * float(draft)
                + bonus
            )
            played = int(np.clip(generator.normal(13.0, 3.0), 0, 17))
            points = float(max(0.0, signal + generator.normal(0.0, 25.0)))
            records.append(
                {
                    "season": row["season"],
                    "player_id": row["player_id"],
                    "scoring_preset": preset,
                    "position": row["position"],
                    "actual_fantasy_points": points,
                    "actual_games_played": played,
                    "actual_positional_rank": 1,
                },
            )
    frame = pl.DataFrame(records)
    return frame.with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("actual_games_played").cast(pl.Int32),
        pl.col("actual_positional_rank").cast(pl.Int32),
    )


@pytest.fixture(scope="session")
def synthetic_feature_frame() -> pl.DataFrame:
    return synthetic_features()


@pytest.fixture(scope="session")
def synthetic_label_frame(synthetic_feature_frame: pl.DataFrame) -> pl.DataFrame:
    return synthetic_labels(synthetic_feature_frame)


@pytest.fixture(scope="session")
def synthetic_modeling_dataset(synthetic_feature_frame, synthetic_label_frame):
    from ffdraft.modeling.dataset import build_modeling_frame

    return build_modeling_frame(synthetic_feature_frame, synthetic_label_frame)


# --------------------------------------------------------------------------------------
# Synthetic rest-of-season fixtures (Phase 11)
#
# The ROS tests need weekly rows, not season rows, and they need the awkward cases a real
# season contains: a bye, a mid-season injury, a player who never appears at all, a
# mid-season arrival absent from the preseason universe, and a team change. Generating them
# here keeps the assertions sharp - every quantity below is known by construction - and
# keeps the Phase-2 fixture files untouched.
# --------------------------------------------------------------------------------------

ROS_SEASONS: tuple[int, ...] = (2017, 2018, 2019, 2020, 2021)
ROS_PLAYERS_PER_POSITION = 10
_ROS_TEAMS: tuple[str, ...] = ("AAA", "BBB", "CCC", "DDD")


def _weekly_row(
    *,
    season: int,
    week: int,
    gsis_id: str,
    name: str,
    position: str,
    team: str,
    opponent: str,
    generator: np.random.Generator,
    quality: float,
) -> dict[str, Any]:
    """One scored appearance, shaped like the normalized weekly-stats contract."""
    targets = max(0.0, generator.normal(4.0 + 4.0 * quality, 2.0)) if position != "QB" else 0.0
    receptions = min(targets, max(0.0, targets * 0.65))
    carries = max(0.0, generator.normal(6.0 * quality, 3.0)) if position in {"RB", "QB"} else 0.0
    attempts = max(0.0, generator.normal(30.0, 5.0)) if position == "QB" else 0.0
    return {
        "season": season,
        "week": week,
        "season_type": "REG",
        "gsis_id": gsis_id,
        "display_name": name,
        "position": position,
        "team": team,
        "opponent_team": opponent,
        "pass_attempts": attempts,
        "completions": attempts * 0.63,
        "passing_yards": attempts * 7.2,
        "passing_tds": float(generator.integers(0, 3)) if position == "QB" else 0.0,
        "interceptions": float(generator.integers(0, 2)) if position == "QB" else 0.0,
        "passing_air_yards": attempts * 8.0,
        "carries": carries,
        "rushing_yards": carries * 4.3,
        "rushing_tds": float(generator.integers(0, 2)) if position in {"RB", "QB"} else 0.0,
        "targets": targets,
        "receptions": receptions,
        "receiving_yards": receptions * 11.0,
        "receiving_tds": float(generator.integers(0, 2)) if position != "QB" else 0.0,
        "receiving_air_yards": targets * 9.0,
        "fumbles_lost": 0.0,
        "two_point_conversions": 0.0,
        "upstream_fantasy_points_std": None,
        "upstream_fantasy_points_ppr": None,
        "upstream_fumbles_lost_total": None,
        "upstream_special_teams_tds": 0.0,
    }


def synthetic_weekly_stats(
    seasons: Sequence[int] = ROS_SEASONS,
    players_per_position: int = ROS_PLAYERS_PER_POSITION,
    *,
    seed: int = 23,
) -> pl.DataFrame:
    """Weekly rows for the ROS fixtures, with the awkward cases built in.

    Deliberate structure, per position index:

    * ``index % 10 == 0`` never appears at all - the survivorship row;
    * ``index % 7 == 3`` misses everything from week 9 - the season-ending injury;
    * ``index % 5 == 1`` changes team at week 8;
    * ``index % 6 == 2`` does not appear before week 5 - the mid-season arrival;
    * everyone else takes a bye in a position-dependent week.
    """
    from ffdraft.contracts.normalized import WEEKLY_STATS_CONTRACT
    from ffdraft.scoring.horizon import fantasy_horizon

    generator = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for season in seasons:
        horizon = fantasy_horizon(season)
        for position_index, position in enumerate(POSITIONS):
            for index in range(players_per_position):
                gsis_id = f"00-{position}{index:04d}"
                name = f"{position} Player {index}"
                quality = 0.3 + 0.7 * (players_per_position - index) / players_per_position
                team = _ROS_TEAMS[index % len(_ROS_TEAMS)]
                bye = 4 + (position_index + index) % 8
                for week in horizon.weeks:
                    if index % 10 == 0:
                        continue
                    if index % 7 == 3 and week >= 9:
                        continue
                    if index % 6 == 2 and week < 5:
                        continue
                    if week == bye:
                        continue
                    current = (
                        _ROS_TEAMS[(index + 1) % len(_ROS_TEAMS)]
                        if index % 5 == 1 and week >= 8
                        else team
                    )
                    opponent = _ROS_TEAMS[(index + week) % len(_ROS_TEAMS)]
                    rows.append(
                        _weekly_row(
                            season=season,
                            week=week,
                            gsis_id=gsis_id,
                            name=name,
                            position=position,
                            team=current,
                            opponent=opponent if opponent != current else _ROS_TEAMS[0],
                            generator=generator,
                            quality=quality,
                        ),
                    )
                # One playoff row per player-season, which the horizon must exclude.
                if index % 10 != 0:
                    playoff = _weekly_row(
                        season=season,
                        week=horizon.excluded_week,
                        gsis_id=gsis_id,
                        name=name,
                        position=position,
                        team=team,
                        opponent=_ROS_TEAMS[1],
                        generator=generator,
                        quality=quality,
                    )
                    playoff["season_type"] = "POST"
                    rows.append(playoff)
    return WEEKLY_STATS_CONTRACT.build(rows)


def synthetic_schedule(seasons: Sequence[int] = ROS_SEASONS) -> pl.DataFrame:
    """A round-robin schedule with one bye per team per season."""
    from ffdraft.contracts.normalized import SCHEDULE_CONTRACT
    from ffdraft.scoring.horizon import fantasy_horizon

    rows: list[dict[str, Any]] = []
    for season in seasons:
        for week in fantasy_horizon(season).weeks:
            pairs = [(0, 1), (2, 3)] if week % 2 else [(0, 2), (1, 3)]
            for home, away in pairs:
                if week == 5 and home == 0:
                    continue  # a real bye week, so remaining scheduled games can differ
                rows.append(
                    {
                        "game_id": f"{season}_{week:02d}_{home}_{away}",
                        "season": season,
                        "game_type": "REG",
                        "week": week,
                        "gameday": None,
                        "gametime": None,
                        "home_team": _ROS_TEAMS[home],
                        "away_team": _ROS_TEAMS[away],
                    },
                )
    return SCHEDULE_CONTRACT.build(rows)


def synthetic_ros_universe(
    seasons: Sequence[int] = ROS_SEASONS,
    players_per_position: int = ROS_PLAYERS_PER_POSITION,
) -> pl.DataFrame:
    """The preseason eligible universe: everyone except the mid-season arrivals."""
    rows = [
        {"season": season, "gsis_id": f"00-{position}{index:04d}"}
        for season in seasons
        for position in POSITIONS
        for index in range(players_per_position)
        if index % 6 != 2
    ]
    return pl.DataFrame(rows, schema={"season": pl.Int32, "gsis_id": pl.String})


@pytest.fixture(scope="session")
def ros_weekly_stats() -> pl.DataFrame:
    return synthetic_weekly_stats()


@pytest.fixture(scope="session")
def ros_schedule() -> pl.DataFrame:
    return synthetic_schedule()


@pytest.fixture(scope="session")
def ros_universe() -> pl.DataFrame:
    return synthetic_ros_universe()


@pytest.fixture(scope="session")
def ros_panel(ros_weekly_stats, ros_universe, app_config) -> pl.DataFrame:
    from ffdraft.ros.panel import build_weekly_panel

    return build_weekly_panel(
        ros_weekly_stats,
        app_config.league.scoring,
        seasons=ROS_SEASONS,
        universe=ros_universe,
    )


@pytest.fixture(scope="session")
def ros_dataset(ros_weekly_stats, ros_schedule, ros_universe, app_config):
    """A full ROS snapshot dataset built through the real pipeline, without a network."""
    from ffdraft.features.build import HistoricalSources
    from ffdraft.ros.dataset import build_ros_dataset

    preseason = synthetic_features(
        seasons=ROS_SEASONS, players_per_position=ROS_PLAYERS_PER_POSITION
    )
    sources = HistoricalSources(
        weekly_stats=ros_weekly_stats,
        schedule=ros_schedule,
        rosters={},
        depth_charts={},
        snap_counts=pl.DataFrame(),
        expected_points=pl.DataFrame(),
        draft_picks=pl.DataFrame(),
        combine=pl.DataFrame(),
        player_master=pl.DataFrame(),
    )
    return build_ros_dataset(
        sources,
        preseason,
        config=app_config,
        seasons=ROS_SEASONS,
        git_sha="0000000",
        verify_cutoff_independence=False,
    )


@pytest.fixture(scope="session")
def ros_preseason_frame():
    """The Phase-3 modelling frame the rest-of-season baselines fit their prior on."""
    from ffdraft.ros.baselines import preseason_modelling_frame

    features = synthetic_features(
        seasons=ROS_SEASONS,
        players_per_position=ROS_PLAYERS_PER_POSITION,
    )
    return preseason_modelling_frame(
        features,
        synthetic_labels(features),
        seasons=ROS_SEASONS,
    )


@pytest.fixture(scope="session")
def ros_fit_context(ros_dataset):
    """One concrete (fold, position, preset) job the estimator tests all share."""
    from ffdraft.ros.dictionary import ros_feature_selection
    from ffdraft.ros.estimators import RosFitContext
    from ffdraft.ros.folds import ROS_SEED, RosFold

    features = tuple(
        name for name in ros_feature_selection().included if name in ros_dataset.frame.columns
    )
    return RosFitContext(
        fold=RosFold(train_start_season=2017, train_end_season=2019, validation_season=2020),
        position="WR",
        scoring_preset="PPR",
        features=features,
        seed=ROS_SEED,
    )
