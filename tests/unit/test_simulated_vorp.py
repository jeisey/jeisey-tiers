"""Simulated VORP: the draw loop around the one canonical allocation.

The claims worth testing are not "the numbers are right" but the structural ones the design
rests on: replacement is resampled with everyone else rather than fixed, league shape
changes the answer, the same draws are reused across presets so a preset difference is a
scarcity difference, quantiles come out monotone, and the fair-rank tie-break is the one
`docs/DATA_CONTRACTS.md` section 7 declares.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.config import load_league_config
from ffdraft.simulation.sampler import DomainBounds
from ffdraft.simulation.vorp import (
    SimulationConfig,
    fair_ranking,
    sample_points,
    simulate_vorp,
)

WIDE = DomainBounds(-1e6, 1e6)


@pytest.fixture(scope="module")
def league():
    return load_league_config()


def _pool(count: int = 240, *, seed: int = 3) -> pl.DataFrame:
    """A pool large enough that different league sizes genuinely reach different players."""
    generator = np.random.default_rng(seed)
    positions = ["QB"] * 40 + ["RB"] * 70 + ["WR"] * 90 + ["TE"] * 40
    positions = positions[:count]
    centre = np.sort(generator.uniform(0.0, 300.0, size=len(positions)))[::-1]
    spread = generator.uniform(20.0, 90.0, size=len(positions))
    offsets = np.array([-1.28, -0.67, 0.0, 0.67, 1.28])
    quantiles = centre[:, None] + spread[:, None] * offsets[None, :]
    return pl.DataFrame(
        {
            "player_id": [f"gsis:{index:04d}" for index in range(len(positions))],
            "position": positions,
            **{
                f"p{level}_points": quantiles[:, index]
                for index, level in enumerate(["10", "25", "50", "75", "90"])
            },
        },
    )


def _config(draws: int = 300, seed: int = 5) -> SimulationConfig:
    return SimulationConfig(
        draws=draws,
        seed=seed,
        model_version="test-model",
        scoring_preset="PPR",
        build_id="test-build",
    )


def _bounds() -> dict[str, DomainBounds]:
    return dict.fromkeys(("QB", "RB", "WR", "TE"), WIDE)


def test_simulation_is_deterministic(league) -> None:
    pool, config = _pool(), _config()
    first = simulate_vorp(pool, preset=league.preset("redraft-12"), config=config, bounds=_bounds())
    second = simulate_vorp(
        pool, preset=league.preset("redraft-12"), config=config, bounds=_bounds()
    )
    assert first.players.equals(second.players)


def test_vorp_quantiles_are_monotone(league) -> None:
    result = simulate_vorp(
        _pool(),
        preset=league.preset("redraft-12"),
        config=_config(),
        bounds=_bounds(),
    )
    columns = ["p10_vorp", "p25_vorp", "p50_vorp", "p75_vorp", "p90_vorp"]
    matrix = result.players.select(columns).to_numpy()
    assert np.all(np.diff(matrix, axis=1) >= -1e-9)
    assert np.all(result.players.get_column("uncertainty").to_numpy() >= -1e-9)


def test_replacement_varies_by_draw(league) -> None:
    """The whole reason the loop exists: scarcity is uncertain, not a constant to subtract."""
    result = simulate_vorp(
        _pool(),
        preset=league.preset("redraft-12"),
        config=_config(),
        bounds=_bounds(),
    )
    for row in result.replacement:
        assert row["p90"] > row["p10"], f"{row['position']} replacement never moved"


def test_vorp_is_not_a_shifted_copy_of_points(league) -> None:
    """If replacement were fixed, every player's VORP spread would equal his point spread."""
    result = simulate_vorp(
        _pool(),
        preset=league.preset("redraft-12"),
        config=_config(),
        bounds=_bounds(),
    )
    point_spread = (
        result.players.get_column("p90_points") - result.players.get_column("p10_points")
    ).to_numpy()
    vorp_spread = (
        result.players.get_column("p90_vorp") - result.players.get_column("p10_vorp")
    ).to_numpy()
    assert not np.allclose(point_spread, vorp_spread)


def test_league_size_moves_replacement_and_therefore_vorp(league) -> None:
    pool, config = _pool(), _config()
    points = sample_points(pool, config=config, bounds=_bounds())
    small = simulate_vorp(
        pool,
        preset=league.preset("redraft-10"),
        config=config,
        bounds=_bounds(),
        points=points,
    )
    large = simulate_vorp(
        pool,
        preset=league.preset("redraft-14"),
        config=config,
        bounds=_bounds(),
        points=points,
    )
    small_replacement = {row["position"]: row["mean"] for row in small.replacement}
    large_replacement = {row["position"]: row["mean"] for row in large.replacement}
    for position in ("RB", "WR"):
        assert large_replacement[position] < small_replacement[position], position
    assert not small.players.get_column("expected_vorp").equals(
        large.players.get_column("expected_vorp"),
    )


def test_the_same_draws_are_reused_across_presets(league) -> None:
    """A preset difference must be a scarcity difference, not Monte Carlo noise."""
    pool, config = _pool(), _config()
    points = sample_points(pool, config=config, bounds=_bounds())
    ten = simulate_vorp(
        pool,
        preset=league.preset("redraft-10"),
        config=config,
        bounds=_bounds(),
        points=points,
    )
    twelve = simulate_vorp(
        pool,
        preset=league.preset("redraft-12"),
        config=config,
        bounds=_bounds(),
        points=points,
    )
    assert ten.players.get_column("expected_points").equals(
        twelve.players.get_column("expected_points"),
    )


def test_a_pool_smaller_than_the_starting_slots_reports_it(league) -> None:
    tiny = _pool().filter(pl.col("position") == "QB").head(4)
    result = simulate_vorp(
        tiny,
        preset=league.preset("redraft-12"),
        config=_config(draws=20),
        bounds=_bounds(),
    )
    assert result.unfilled_slots
    assert result.players.get_column("quality_flags").to_list()[0] == "replacement_unavailable"


def test_fair_ranks_are_unique_and_dense() -> None:
    players = pl.DataFrame(
        {
            "player_id": ["c", "a", "b"],
            "position": ["RB", "RB", "WR"],
            "expected_vorp": [10.0, 30.0, 20.0],
            "p50_vorp": [11.0, 31.0, 21.0],
            "p50_points": [100.0, 300.0, 200.0],
            "uncertainty": [5.0, 5.0, 5.0],
        },
    )
    ranked = fair_ranking(players, statistic="expected_vorp")
    assert ranked.get_column("fair_rank").to_list() == [1, 2, 3]
    assert ranked.get_column("player_id").to_list() == ["a", "b", "c"]
    assert sorted(ranked.get_column("fair_rank").to_list()) == [1, 2, 3]


def test_fair_rank_tie_break_follows_the_declared_order() -> None:
    """Value, then P50 points, then lower uncertainty, then a stable id."""
    players = pl.DataFrame(
        {
            "player_id": ["z", "y", "x", "w"],
            "position": ["RB"] * 4,
            "expected_vorp": [10.0, 10.0, 10.0, 10.0],
            "p50_vorp": [10.0, 10.0, 10.0, 10.0],
            "p50_points": [100.0, 100.0, 120.0, 100.0],
            "uncertainty": [4.0, 2.0, 9.0, 2.0],
        },
    )
    ranked = fair_ranking(players, statistic="expected_vorp")
    assert ranked.get_column("player_id").to_list() == ["x", "w", "y", "z"]


def test_position_rank_follows_fair_rank_within_position() -> None:
    players = pl.DataFrame(
        {
            "player_id": ["a", "b", "c", "d"],
            "position": ["RB", "WR", "RB", "WR"],
            "expected_vorp": [40.0, 30.0, 20.0, 10.0],
            "p50_vorp": [40.0, 30.0, 20.0, 10.0],
            "p50_points": [1.0, 1.0, 1.0, 1.0],
            "uncertainty": [1.0, 1.0, 1.0, 1.0],
        },
    )
    ranked = fair_ranking(players, statistic="expected_vorp").sort("fair_rank")
    assert ranked.get_column("position_rank").to_list() == [1, 1, 2, 2]


def test_median_and_expected_statistics_can_disagree() -> None:
    """The reason `phase4_ranking_v1` exists: a skewed distribution orders differently."""
    players = pl.DataFrame(
        {
            "player_id": ["steady", "boom"],
            "position": ["RB", "RB"],
            "expected_vorp": [20.0, 25.0],
            "p50_vorp": [22.0, 12.0],
            "p50_points": [100.0, 90.0],
            "uncertainty": [10.0, 60.0],
        },
    )
    by_median = fair_ranking(players, statistic="median_vorp").sort("fair_rank")
    by_expected = fair_ranking(players, statistic="expected_vorp").sort("fair_rank")
    assert by_median.get_column("player_id").to_list() == ["steady", "boom"]
    assert by_expected.get_column("player_id").to_list() == ["boom", "steady"]


def test_unknown_ranking_statistic_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown ranking statistic"):
        fair_ranking(pl.DataFrame({"player_id": ["a"]}), statistic="ceiling")


def test_league_preset_does_not_enter_the_draw_seed() -> None:
    config = _config()
    assert "redraft-12" not in [str(part) for part in config.seed_material]
    assert config.to_dict()["player_draws_depend_on_league_preset"] is False
