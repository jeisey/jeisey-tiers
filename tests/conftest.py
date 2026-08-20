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
