"""The weekly evaluation harness: the seal, the pools, the verdict, the bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.weekly.evaluate import (
    CANDIDATE_ID,
    WeeklyFinalEvalAuthorization,
    bootstrap_accuracy_difference,
    calibration_table,
    development_frame,
    evaluate_fold,
    pinball,
    run_weekly_experiment,
    verdict,
)
from ffdraft.weekly.frozen import (
    BASELINE_IDS,
    WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN,
    WEEKLY_SEALED_SEASON,
    WeeklySpec,
)

Rows = Callable[..., pl.DataFrame]

FAST = replace(WeeklySpec(), num_boost_round=8)


def test_the_sealed_season_is_absent_from_a_development_frame(weekly_rows: Rows) -> None:
    frame = weekly_rows(range(2023, 2026), per_season=20)
    assert WEEKLY_SEALED_SEASON not in development_frame(frame).get_column("season").to_list()
    authorization = WeeklyFinalEvalAuthorization(WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN, "test")
    assert (
        WEEKLY_SEALED_SEASON
        in development_frame(
            frame,
            authorization=authorization,
        )
        .get_column("season")
        .to_list()
    )


def test_a_development_run_cannot_score_the_sealed_season(weekly_rows: Rows) -> None:
    with pytest.raises(HoldoutSealError, match="sealed holdout"):
        run_weekly_experiment(weekly_rows(range(2023, 2026), per_season=20), seasons=(2025,))


@pytest.mark.parametrize(
    ("token", "reason", "match"),
    [
        ("RELEASE-ROS-FINAL-HOLDOUT-2025", "why", "exact confirmation token"),
        (WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN, "  ", "recorded reason"),
    ],
)
def test_the_seal_needs_its_own_token_and_a_reason(token: str, reason: str, match: str) -> None:
    with pytest.raises(HoldoutSealError, match=match):
        WeeklyFinalEvalAuthorization(token, reason)


def test_pinball_is_zero_on_a_perfect_point_and_asymmetric_otherwise() -> None:
    levels = [0.1, 0.5, 0.9]
    exact = pinball(np.array([10.0]), np.array([[10.0, 10.0, 10.0]]), levels)
    assert exact[0] == 0.0
    under = pinball(np.array([12.0]), np.array([[10.0, 10.0, 10.0]]), levels)
    over = pinball(np.array([8.0]), np.array([[10.0, 10.0, 10.0]]), levels)
    assert under[0] == pytest.approx(over[0])


def test_a_fold_scores_every_model_on_the_same_pairs(weekly_rows: Rows) -> None:
    frame = weekly_rows(range(2017, 2021), per_season=120)
    fold = evaluate_fold(frame, season=2020, spec=FAST)
    sizes = {model_id: pairs["probability"].shape[0] for model_id, pairs in fold.pairs.items()}
    assert set(sizes) == {CANDIDATE_ID, *BASELINE_IDS}
    assert len(set(sizes.values())) == 1 and next(iter(sizes.values())) > 0
    for pairs in fold.pairs.values():
        assert np.all((pairs["probability"] >= 0) & (pairs["probability"] <= 1))


def _pooled(candidate: dict[str, float], baseline: dict[str, float]) -> dict[str, dict[str, float]]:
    return {CANDIDATE_ID: candidate, **{baseline_id: baseline for baseline_id in BASELINE_IDS}}


GOOD = {
    "pinball": 1.0,
    "pair_accuracy": 0.66,
    "pair_brier": 0.2,
    "coverage_80": 0.8,
    "coverage_50": 0.5,
}
BASE = {
    "pinball": 1.2,
    "pair_accuracy": 0.64,
    "pair_brier": 0.22,
    "coverage_80": 0.8,
    "coverage_50": 0.5,
}


def test_the_verdict_passes_only_when_every_clause_does() -> None:
    by_season = {season: _pooled(GOOD, BASE) for season in (2020, 2021, 2022, 2023, 2024)}
    boot = {"difference": 0.02, "lower": 0.01, "upper": 0.03, "clusters": 80, "replicates": 1000}
    assert verdict(_pooled(GOOD, BASE), by_season, boot, development=True)["passed"]
    # A bootstrap interval touching zero fails the accuracy clause in development.
    weak = {**boot, "lower": -0.001}
    assert not verdict(_pooled(GOOD, BASE), by_season, weak, development=True)["passed"]
    # So does coverage outside its band.
    wide = {**GOOD, "coverage_80": 0.9}
    assert not verdict(_pooled(wide, BASE), by_season, boot, development=True)["passed"]


def test_the_holdout_verdict_reads_only_its_declared_clauses() -> None:
    decision = verdict(_pooled(GOOD, BASE), {}, None, development=False)
    assert set(decision["clauses"]) == {
        "pinball_below_best_baseline",
        "pairwise_accuracy_above_best_baseline",
        "pairwise_brier_below_best_baseline",
        "coverage_80_in_band",
    }
    assert decision["passed"]


def test_the_bootstrap_resamples_whole_weeks() -> None:
    clusters = np.repeat(np.arange(10), 50)
    candidate = {"cluster": clusters, "correct": np.ones(500)}
    baseline = {"cluster": clusters, "correct": np.zeros(500)}
    result = bootstrap_accuracy_difference(candidate, baseline, replicates=200, level=0.95)
    assert result["clusters"] == 10
    assert result["difference"] == pytest.approx(1.0)
    assert result["lower"] == pytest.approx(1.0)


def test_calibration_bins_the_favourite_and_what_happened() -> None:
    pairs = {"probability": np.array([0.8, 0.2, 0.52]), "outcome": np.array([1.0, 1.0, 0.0])}
    table = calibration_table(pairs)
    top = next(row for row in table if row["low"] == 0.8)
    assert top["pairs"] == 2
    assert top["observed"] == pytest.approx(0.5)
    low = next(row for row in table if row["low"] == 0.5)
    assert low["observed"] == 0.0


def test_the_report_frame_is_one_row_per_scored_row(weekly_rows: Rows) -> None:
    frame = weekly_rows(range(2017, 2021), per_season=60)
    fold = evaluate_fold(frame, season=2020, spec=FAST)
    assert fold.rows.height == frame.filter(pl.col("season") == 2020).height
