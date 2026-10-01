"""The prospective holdout: pregame only, never backfilled, and three distinct outcomes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.weekly.frozen import WEEKLY_QUANTILE_LEVELS
from ffdraft.weekly.frozen_v2 import WEEKLY_V2_PROSPECTIVE_TOKEN
from ffdraft.weekly.prospective import eligible_rows, evidence_counts, prospective_verdict

FROZEN = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)
KEYS = [f"q{round(level * 100):02d}" for level in WEEKLY_QUANTILE_LEVELS]
Z = {
    "q05": -1.645,
    "q10": -1.2816,
    "q25": -0.6745,
    "q50": 0.0,
    "q75": 0.6745,
    "q90": 1.2816,
    "q95": 1.645,
}


def _quantiles(centre: float) -> dict[str, float]:
    return {key: centre + Z[key] * 5.0 for key in KEYS}


def _shadow(
    built: datetime, *, kickoff: datetime = KICKOFF, v2: bool = True, centre: float = 10.0
) -> dict[str, Any]:
    return {
        "as_of_utc": built.isoformat().replace("+00:00", "Z"),
        "kickoff_utc": kickoff.isoformat().replace("+00:00", "Z"),
        "player_id": "gsis:00-0000001",
        "gsis_id": "00-0000001",
        "scoring_preset": "PPR",
        "game_id": "2026_05_BUF_MIA",
        "season": 2026,
        "target_week": 5,
        "position": "WR",
        "v1": _quantiles(centre),
        "v2": _quantiles(centre + 1.0) if v2 else None,
        "b0_inputs": {"games_to_date": 4, "ppg_to_date": 12.0},
    }


def test_the_last_pregame_row_is_the_one_scored() -> None:
    rows = [
        _shadow(KICKOFF - timedelta(days=2), centre=8.0),
        _shadow(KICKOFF - timedelta(hours=3), centre=9.0),
        _shadow(KICKOFF + timedelta(minutes=5), centre=50.0),  # built after kickoff
    ]
    frame = eligible_rows(rows, frozen_at=FROZEN)
    assert frame.height == 1
    assert frame.get_column("v1__q50").item() == pytest.approx(9.0)
    assert frame.get_column("b0").item() == pytest.approx(12.0)


def test_a_game_before_the_freeze_and_a_row_without_v2_are_not_evidence() -> None:
    early = _shadow(FROZEN - timedelta(days=2), kickoff=FROZEN - timedelta(hours=1))
    missing = _shadow(KICKOFF - timedelta(hours=3), v2=False)
    assert eligible_rows([early, missing], frozen_at=FROZEN).is_empty()


def _scored(*, weeks: int, v2_bias: float, v1_bias: float = 3.0, seed: int = 5) -> pl.DataFrame:
    """Pools wider than v1's decision depth, so every pool is full."""
    rng = np.random.default_rng(seed)
    sizes = {"QB": 32, "RB": 80, "WR": 100, "TE": 40}
    records: list[dict[str, Any]] = []
    for week in range(1, weeks + 1):
        for preset in ("STD", "HALF", "PPR"):
            for position, size in sizes.items():
                for index in range(size):
                    centre = float(rng.uniform(4, 24))
                    actual = float(rng.normal(centre, 5.0))
                    record: dict[str, Any] = {
                        "player_id": f"{position}{index}",
                        "scoring_preset": preset,
                        "target_week": week,
                        "position": position,
                        "b0": centre,
                        "actual": actual,
                    }
                    for key in KEYS:
                        record[f"v1__{key}"] = centre + v1_bias + Z[key] * 5.0
                        record[f"v2__{key}"] = centre + v2_bias + Z[key] * 5.0
                    records.append(record)
    return pl.DataFrame(records)


def test_short_of_the_minimum_it_is_insufficient_evidence_without_opening_anything() -> None:
    scored = _scored(weeks=3, v2_bias=0.0)
    counts = evidence_counts(scored)
    assert counts["weeks"] == 3 and not counts["minimum_met"]
    verdict = prospective_verdict(scored, look="first", confirmation=None)
    assert verdict["outcome"] == "insufficient_evidence"
    assert verdict["reason"] == "minimum evidence not met"


def test_a_look_needs_its_own_token_once_the_minimum_is_met() -> None:
    scored = _scored(weeks=8, v2_bias=0.0)
    assert evidence_counts(scored)["minimum_met"]
    with pytest.raises(HoldoutSealError, match="exact token"):
        prospective_verdict(scored, look="first", confirmation="PROSPECTIVE-WEEKLY-V1")
    with pytest.raises(ValueError, match="look"):
        prospective_verdict(scored, look="third", confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN)


def test_a_clearly_better_v2_is_promoted_and_a_clearly_worse_one_rejected() -> None:
    better = prospective_verdict(
        _scored(weeks=8, v2_bias=0.0, v1_bias=3.0),
        look="first",
        confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN,
    )
    assert better["outcome"] == "promote", better["summary"]
    assert better["interval"]["lower"] > 0.0
    worse = prospective_verdict(
        _scored(weeks=8, v2_bias=7.0, v1_bias=0.0),
        look="final",
        confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN,
    )
    assert worse["outcome"] == "reject", worse["summary"]


def test_an_indistinguishable_v2_is_insufficient_evidence_not_a_rejection() -> None:
    same = prospective_verdict(
        _scored(weeks=8, v2_bias=3.0, v1_bias=3.0),
        look="final",
        confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN,
    )
    assert same["outcome"] == "insufficient_evidence"
    assert same["interval"]["difference"] == pytest.approx(0.0)


def test_the_verdict_is_deterministic() -> None:
    scored = _scored(weeks=8, v2_bias=0.5)
    first = prospective_verdict(scored, look="first", confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN)
    again = prospective_verdict(scored, look="first", confirmation=WEEKLY_V2_PROSPECTIVE_TOKEN)
    assert first == again
