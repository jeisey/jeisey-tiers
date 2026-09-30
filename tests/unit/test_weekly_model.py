"""``wc1_quantile_gbm_conformal_v1`` on synthetic rows: monotone, closed, reproducible, sealed."""

from __future__ import annotations

import gzip
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from ffdraft.weekly.frozen import FEATURE_FAMILIES, WeeklySpec
from ffdraft.weekly.model import WeeklyArtifactMismatch, WeeklyModel, fit_weekly_model

Rows = Callable[..., pl.DataFrame]

FAST = replace(WeeklySpec(), num_boost_round=12)


def test_quantiles_are_monotone_and_offsets_are_measured(weekly_rows: Rows) -> None:
    frame = weekly_rows()
    model = fit_weekly_model(frame, spec=FAST)
    group = model.groups["WR-PPR"]
    assert model.calibration_season == 2020
    assert len(group.offsets) == len(FAST.levels)
    assert group.calibration_rows == 400
    predictions = model.predict(frame.filter(pl.col("season") == 2020))
    assert predictions.shape == (400, 7)
    assert np.all(np.diff(predictions, axis=1) >= 0)


def test_an_unfitted_group_is_nan_never_a_number(weekly_rows: Rows) -> None:
    frame = weekly_rows()
    model = fit_weekly_model(frame, spec=FAST)
    other = frame.head(3).with_columns(pl.lit("TE").alias("position"))
    assert np.all(np.isnan(model.predict(other)))


def test_the_driver_account_closes_on_the_median(weekly_rows: Rows) -> None:
    frame = weekly_rows()
    model = fit_weekly_model(frame, spec=FAST)
    sample = frame.filter(pl.col("season") == 2020).head(25)
    medians = model.predict(sample)[:, FAST.levels.index(0.5)]
    for account, median in zip(model.drivers(sample), medians, strict=True):
        assert account is not None
        assert set(account["families"]) == set(FEATURE_FAMILIES)
        total = (
            account["baseline"]
            + sum(account["families"].values())
            + account["calibration"]
            + account["rearrangement"]
        )
        assert total == pytest.approx(float(median), abs=1e-9)


def test_calibration_needs_two_training_seasons(weekly_rows: Rows) -> None:
    with pytest.raises(ValueError, match="two training seasons"):
        fit_weekly_model(weekly_rows(range(2017, 2018)), spec=FAST)


def test_the_artifact_round_trips_to_identical_predictions_and_bytes(
    tmp_path: Path, weekly_rows: Rows
) -> None:
    frame = weekly_rows(per_season=250)
    first = fit_weekly_model(frame)
    first.save(tmp_path / "a")
    second = fit_weekly_model(frame)
    second.save(tmp_path / "b")
    boosters_a = sorted((tmp_path / "a" / "boosters").iterdir())
    boosters_b = sorted((tmp_path / "b" / "boosters").iterdir())
    assert [path.read_bytes() for path in boosters_a] == [path.read_bytes() for path in boosters_b]
    loaded = WeeklyModel.load(tmp_path / "a")
    sample = frame.head(40)
    assert np.array_equal(loaded.predict(sample), first.predict(sample))


def test_a_different_specification_is_refused_at_load(tmp_path: Path, weekly_rows: Rows) -> None:
    model = fit_weekly_model(weekly_rows(per_season=150), spec=FAST)
    model.save(tmp_path / "fast")
    with pytest.raises(WeeklyArtifactMismatch, match="different specification"):
        WeeklyModel.load(tmp_path / "fast")


def test_an_altered_booster_is_refused_at_load(tmp_path: Path, weekly_rows: Rows) -> None:
    model = fit_weekly_model(weekly_rows(per_season=150))
    model.save(tmp_path / "m")
    target = sorted((tmp_path / "m" / "boosters").iterdir())[0]
    text = (
        gzip.decompress(target.read_bytes())
        .decode("utf-8")
        .replace("leaf_value=", "leaf_value=0", 1)
    )
    target.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    with pytest.raises(WeeklyArtifactMismatch, match="digest"):
        WeeklyModel.load(tmp_path / "m")
