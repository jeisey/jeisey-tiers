"""Natural tier segmentation and its stability.

`docs/TEST_STRATEGY.md` section 2.8 names the synthetic cases: a clear two-cluster board
should produce a boundary at the known gap, a smooth board should not fragment into
pathological tiers, an isolated elite player should be allowed to stand alone, membership
must be contiguous, and the bootstrap must be deterministic for a fixed seed.

Nothing here checks a hard-coded tier count. The count is an output.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from ffdraft.tiers.labels import LETTER_LABELS, tier_label
from ffdraft.tiers.segmentation import (
    adjacent_effect_sizes,
    segment_board,
    standardize,
)
from ffdraft.tiers.stability import adjusted_rand_index, bootstrap_stability, summarise_from_draws


def _board(values: list[float], spread: float | list[float] = 10.0) -> pl.DataFrame:
    spreads = [spread] * len(values) if isinstance(spread, float) else spread
    return pl.DataFrame(
        {
            "player_id": [f"p{index:03d}" for index in range(len(values))],
            "position": ["RB"] * len(values),
            "fair_rank": list(range(1, len(values) + 1)),
            "p25_vorp": [value - half / 2 for value, half in zip(values, spreads, strict=True)],
            "p50_vorp": values,
            "p75_vorp": [value + half / 2 for value, half in zip(values, spreads, strict=True)],
            "uncertainty": spreads,
        },
    )


def test_two_clear_clusters_produce_a_boundary_at_the_gap() -> None:
    values = [100.0 - index for index in range(20)] + [20.0 - index for index in range(20)]
    segmentation = segment_board(_board(values), penalty=3.0)
    assert 20 in segmentation.boundaries
    assert segmentation.tier_count >= 2


def test_a_smooth_board_does_not_fragment() -> None:
    """No cliff means no reason for many tiers; the penalty is what keeps it honest."""
    values = [100.0 - 0.25 * index for index in range(120)]
    segmentation = segment_board(_board(values), penalty=5.0)
    assert segmentation.tier_count <= 4


def test_an_isolated_elite_player_may_stand_alone() -> None:
    """``min_size=1`` means a genuine singleton is available, not that one is imposed.

    Whether a given board produces one is a question for the penalty and the evidence, and
    the frozen selection rule bounds the singleton *rate* rather than forbidding singletons.
    Here the gap is enormous and the penalty small, so the algorithm takes it.
    """
    values = [400.0] + [100.0 - index for index in range(40)]
    segmentation = segment_board(_board(values), penalty=1.0)
    assert segmentation.ordinals[0] == 0
    assert segmentation.ordinals[1] != 0
    assert segmentation.sizes[0] == 1


def test_membership_is_contiguous_in_fair_rank_order() -> None:
    generator = np.random.default_rng(4)
    values = np.sort(generator.uniform(0.0, 200.0, size=150))[::-1].tolist()
    segmentation = segment_board(_board(values), penalty=4.0)
    ordinals = list(segmentation.ordinals)
    assert ordinals == sorted(ordinals)
    for ordinal in set(ordinals):
        positions = [index for index, value in enumerate(ordinals) if value == ordinal]
        assert positions == list(range(positions[0], positions[-1] + 1))


def test_tier_count_is_not_fixed_and_responds_to_the_penalty() -> None:
    generator = np.random.default_rng(9)
    values = np.sort(generator.uniform(0.0, 250.0, size=200))[::-1].tolist()
    counts = {
        penalty: segment_board(_board(values), penalty=penalty).tier_count
        for penalty in (1.0, 5.0, 12.0)
    }
    assert counts[1.0] >= counts[5.0] >= counts[12.0]
    assert len(set(counts.values())) > 1


def test_boundary_diagnostics_describe_the_gap_they_sit_on() -> None:
    values = [100.0] * 10 + [20.0] * 10
    segmentation = segment_board(_board(values), penalty=1.0)
    assert segmentation.diagnostics
    diagnostic = next(item for item in segmentation.diagnostics if item.fair_rank_below == 11)
    assert diagnostic.p50_cliff == pytest.approx(80.0)
    assert diagnostic.effect_size > 1.0
    assert 0.0 <= diagnostic.probability_lower_exceeds_upper < 0.5


def test_boundary_effects_exceed_within_tier_effects_on_a_clustered_board() -> None:
    values = [100.0 - 0.1 * index for index in range(20)] + [
        20.0 - 0.1 * index for index in range(20)
    ]
    segmentation = segment_board(_board(values), penalty=3.0)
    assert segmentation.mean_boundary_effect_size > segmentation.median_within_tier_effect_size


def test_adjacent_effect_sizes_are_scale_free() -> None:
    p50 = np.array([100.0, 60.0, 20.0])
    spread = np.array([10.0, 10.0, 10.0])
    base = adjacent_effect_sizes(p50, spread)
    doubled = adjacent_effect_sizes(p50 * 2.0, spread * 2.0)
    assert np.allclose(base, doubled)


def test_standardize_leaves_a_constant_column_at_zero() -> None:
    matrix = np.array([[1.0, 5.0], [1.0, 7.0], [1.0, 9.0]])
    standardized = standardize(matrix)
    assert np.allclose(standardized[:, 0], 0.0)
    assert standardized[:, 1].std() == pytest.approx(1.0)


def test_an_empty_board_segments_to_nothing() -> None:
    segmentation = segment_board(_board([]), penalty=3.0)
    assert segmentation.tier_count == 0
    assert segmentation.ordinals == ()


def test_tier_labels_follow_the_contract() -> None:
    assert [tier_label(index) for index in range(7)] == list(LETTER_LABELS)
    assert tier_label(7) == "Late 1"
    assert tier_label(9) == "Late 3"
    with pytest.raises(ValueError):
        tier_label(-1)


def test_adjusted_rand_index_landmarks() -> None:
    assert adjusted_rand_index([0, 0, 1, 1], [0, 0, 1, 1]) == pytest.approx(1.0)
    assert adjusted_rand_index([0, 0, 1, 1], [1, 1, 0, 0]) == pytest.approx(1.0)
    assert adjusted_rand_index([0, 0, 0, 0], [0, 0, 0, 0]) == pytest.approx(1.0)
    assert adjusted_rand_index([0, 0, 1, 1], [0, 1, 0, 1]) < 0.1


def _draw_fixture(players: int = 60, draws: int = 400, seed: int = 2):
    generator = np.random.default_rng(seed)
    centre = np.sort(generator.uniform(0.0, 200.0, size=players))[::-1]
    vorp = centre[:, None] + generator.normal(0.0, 25.0, size=(players, draws))
    points = vorp + 120.0
    frame = pl.DataFrame(
        {
            "player_id": [f"p{index:03d}" for index in range(players)],
            "position": ["RB"] * players,
            "league_preset_id": ["redraft-12"] * players,
            "scoring_preset": ["PPR"] * players,
        },
    )
    return frame, vorp, points


def test_summarising_every_draw_reproduces_the_full_summary() -> None:
    frame, vorp, points = _draw_fixture()
    summary = summarise_from_draws(frame, vorp, points)
    assert summary.height == frame.height
    assert summary.get_column("expected_vorp").to_numpy() == pytest.approx(vorp.mean(axis=1))
    assert np.all(
        np.diff(
            summary.select("p10_vorp", "p25_vorp", "p50_vorp", "p75_vorp", "p90_vorp").to_numpy(),
            axis=1,
        )
        >= -1e-9,
    )


def test_bootstrap_is_deterministic_for_a_fixed_seed() -> None:
    frame, vorp, points = _draw_fixture()
    summary = summarise_from_draws(frame, vorp, points)
    from ffdraft.simulation.vorp import fair_ranking

    ranked = fair_ranking(summary, statistic="median_vorp").head(60)
    promoted = {3.0: segment_board(ranked, penalty=3.0)}
    kwargs = {
        "promoted": promoted,
        "promoted_player_ids": ranked.get_column("player_id").to_list(),
        "statistic": "median_vorp",
        "board_depth": 60,
        "replicates": 12,
        "seed": 17,
    }
    first = bootstrap_stability(summary, vorp, points, **kwargs)  # type: ignore[arg-type]
    second = bootstrap_stability(summary, vorp, points, **kwargs)  # type: ignore[arg-type]
    assert first[3.0].to_dict() == second[3.0].to_dict()
    assert 0.0 <= first[3.0].adjusted_rand <= 1.0


def test_bootstrap_evaluates_every_requested_penalty() -> None:
    frame, vorp, points = _draw_fixture()
    summary = summarise_from_draws(frame, vorp, points)
    from ffdraft.simulation.vorp import fair_ranking

    ranked = fair_ranking(summary, statistic="median_vorp").head(60)
    promoted = {penalty: segment_board(ranked, penalty=penalty) for penalty in (2.0, 8.0)}
    reports = bootstrap_stability(
        summary,
        vorp,
        points,
        promoted=promoted,
        promoted_player_ids=ranked.get_column("player_id").to_list(),
        statistic="median_vorp",
        board_depth=60,
        replicates=10,
        seed=21,
    )
    assert set(reports) == {2.0, 8.0}
    assert all(report.replicates == 10 for report in reports.values())
