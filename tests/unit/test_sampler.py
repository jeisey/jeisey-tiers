"""The deterministic Monte Carlo sampler.

Four properties carry the whole Phase-4 simulation and each is asserted directly: the
quantile function is monotone and refuses to be built from anything else, interpolation is
exact at the supported levels, the tails are the documented linear continuation clamped to
declared bounds, and the draws are reproducible from the seed material and the player's own
id rather than from the pool he happens to be in.
"""

from __future__ import annotations

import numpy as np
import pytest

from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.simulation.sampler import (
    DomainBounds,
    QuantileFunction,
    normal_draws,
    seed_material_int,
    uniform_draws,
)

LEVELS = QUANTILE_LEVELS
WIDE = DomainBounds(-1e9, 1e9)


def _function(rows: list[list[float]], bounds: DomainBounds = WIDE) -> QuantileFunction:
    return QuantileFunction(LEVELS, np.array(rows, dtype=np.float64), bounds)


def test_a_crossing_grid_is_refused() -> None:
    """Repair belongs upstream; by the time a distribution reaches the sampler it is settled."""
    with pytest.raises(ValueError, match="crossing quantiles"):
        _function([[10.0, 9.0, 20.0, 30.0, 40.0]])


def test_a_non_finite_grid_is_refused() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _function([[10.0, 20.0, float("nan"), 30.0, 40.0]])


def test_levels_must_increase() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        QuantileFunction((0.1, 0.1, 0.5, 0.75, 0.9), np.zeros((1, 5)), WIDE)


def test_evaluation_is_exact_at_the_supported_levels() -> None:
    function = _function([[0.0, 50.0, 100.0, 180.0, 260.0]])
    values = function.evaluate(np.array([list(LEVELS)]))
    assert values.tolist() == [[0.0, 50.0, 100.0, 180.0, 260.0]]


def test_interpolation_between_levels_is_linear_and_monotone() -> None:
    function = _function([[0.0, 50.0, 100.0, 180.0, 260.0]])
    # Halfway between P25 (50) and P50 (100) in u-space is 0.375.
    assert function.evaluate(np.array([[0.375]]))[0][0] == pytest.approx(75.0)
    grid = np.linspace(0.001, 0.999, 400)[None, :]
    sampled = function.evaluate(grid)[0]
    assert np.all(np.diff(sampled) >= -1e-9)


def test_tails_continue_the_adjacent_segment_slope() -> None:
    """The documented rule, checked arithmetically rather than described."""
    function = _function([[0.0, 30.0, 100.0, 180.0, 260.0]])
    # Below P10 the (P10, P25) slope is 30/0.15 = 200 per unit of u.
    assert function.evaluate(np.array([[0.05]]))[0][0] == pytest.approx(-10.0)
    # Above P90 the (P75, P90) slope is 80/0.15.
    assert function.evaluate(np.array([[0.95]]))[0][0] == pytest.approx(260.0 + 80.0 / 3.0)


def test_bounds_clamp_the_extrapolated_tails_only() -> None:
    tight = DomainBounds(-5.0, 300.0)
    function = _function([[0.0, 30.0, 100.0, 180.0, 260.0]], tight)
    assert function.evaluate(np.array([[0.0]]))[0][0] == -5.0
    assert function.evaluate(np.array([[1.0]]))[0][0] <= 300.0
    # Inside the supported range the bound never binds.
    assert function.evaluate(np.array([[0.5]]))[0][0] == pytest.approx(100.0)


def test_negative_totals_are_allowed() -> None:
    """This project's scoring presets make a negative season total possible, so nothing
    clamps at zero."""
    bounds = DomainBounds.from_training(np.array([-4.0, 0.0, 200.0, 400.0]))
    assert bounds.lower < 0.0
    function = _function([[-3.0, 0.0, 5.0, 40.0, 120.0]], bounds)
    assert float(np.min(function.evaluate(np.linspace(0.0, 1.0, 50)[None, :]))) < 0.0


def test_domain_bounds_are_asymmetric_by_design() -> None:
    """Records fall upward far more often than seasons collapse below the worst ever seen."""
    bounds = DomainBounds.from_training(np.array([0.0, 100.0]))
    assert bounds.lower == pytest.approx(-5.0)
    assert bounds.upper == pytest.approx(115.0)


def test_same_seed_material_gives_identical_draws() -> None:
    ids = ["gsis:a", "gsis:b", "gsis:c"]
    first = uniform_draws(ids, 64, seed_material=("model-1", "sim-1", "PPR", 7))
    second = uniform_draws(ids, 64, seed_material=("model-1", "sim-1", "PPR", 7))
    assert np.array_equal(first, second)


def test_different_seed_material_gives_different_draws() -> None:
    ids = ["gsis:a"]
    first = uniform_draws(ids, 64, seed_material=("model-1", "sim-1", "PPR", 7))
    second = uniform_draws(ids, 64, seed_material=("model-1", "sim-1", "PPR", 8))
    assert not np.array_equal(first, second)


def test_a_players_draws_do_not_depend_on_the_pool() -> None:
    """Adding a rookie to the board must not move anybody else's floor by an accident."""
    material = ("model-1", "sim-1", "PPR", 7)
    small = uniform_draws(["gsis:a", "gsis:b"], 32, seed_material=material)
    large = uniform_draws(["gsis:z", "gsis:a", "gsis:q", "gsis:b"], 32, seed_material=material)
    assert np.array_equal(small[0], large[1])
    assert np.array_equal(small[1], large[3])


def test_seed_material_hash_is_stable_across_processes() -> None:
    """Python's own hash is salted per process, so it cannot appear near a reproducible seed."""
    assert seed_material_int(("a", 1)) == seed_material_int(("a", 1))
    assert seed_material_int(("a", 1)) != seed_material_int(("a", 2))


def test_normal_draws_are_reproducible_and_shaped_per_stream() -> None:
    ids = ["gsis:a", "gsis:b"]
    first = normal_draws(ids, 16, seed_material=("m", 1), streams=2)
    second = normal_draws(ids, 16, seed_material=("m", 1), streams=2)
    assert first.shape == (2, 2, 16)
    assert np.array_equal(first, second)
    assert not np.array_equal(first[0], first[1])


def test_probability_integral_transform_inverts_evaluation() -> None:
    function = _function([[0.0, 30.0, 100.0, 180.0, 260.0]])
    for value, expected in ((30.0, 0.25), (100.0, 0.50), (180.0, 0.75)):
        assert function.probability_integral_transform(np.array([value]))[0] == pytest.approx(
            expected,
            abs=1e-9,
        )


def test_probability_integral_transform_puts_a_flat_segment_at_its_midpoint() -> None:
    """Games played is zero at the lowest quantiles for most players; the transform must not
    pretend to resolve inside a genuine flat region."""
    function = _function([[0.0, 0.0, 0.0, 4.0, 9.0]])
    assert function.probability_integral_transform(np.array([0.0]))[0] == pytest.approx(0.175)


def test_sampling_requires_one_id_per_row() -> None:
    function = _function([[0.0, 1.0, 2.0, 3.0, 4.0]])
    with pytest.raises(ValueError, match="player id"):
        function.sample(["a", "b"], 4, seed_material=("m",))


def test_draw_count_must_be_positive() -> None:
    with pytest.raises(ValueError, match="draws must be positive"):
        uniform_draws(["a"], 0, seed_material=("m",))
