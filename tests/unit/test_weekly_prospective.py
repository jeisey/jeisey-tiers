"""The prospective holdout: pregame only, never backfilled, and three distinct outcomes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pytest

from ffdraft.cli import main
from ffdraft.modeling.holdout import HoldoutSealError
from ffdraft.retention import SnapshotConflictError, SnapshotStore
from ffdraft.weekly import cli as weekly_cli
from ffdraft.weekly.capture import (
    LOOK_SOURCE_ID,
    GamedayCapture,
    recorded_looks,
    verify_gameday_store,
    write_gameday_capture,
)
from ffdraft.weekly.frozen import WEEKLY_QUANTILE_LEVELS
from ffdraft.weekly.frozen_v2 import WEEKLY_V2_PROSPECTIVE_TOKEN
from ffdraft.weekly.prospective import (
    complete_weeks,
    due_look,
    eligible_rows,
    evidence_counts,
    prospective_verdict,
)

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


# --- prospective_looks_v1: when each look is due, and the ledger that makes it happen once ---

NOW = datetime(2026, 12, 2, 15, 17, tzinfo=UTC)


def _games(week: int, kickoff: datetime) -> list[tuple[int, datetime | None, str, str]]:
    return [(week, kickoff, "BUF", "MIA"), (week, kickoff + timedelta(hours=3), "KC", "DEN")]


def test_a_week_is_complete_only_once_its_outcomes_have_arrived() -> None:
    teams = {"BUF", "MIA", "KC", "DEN"}
    games = _games(11, NOW - timedelta(days=3)) + _games(12, NOW - timedelta(hours=4))
    complete, over = complete_weeks(
        games,
        stats_teams={11: teams, 12: teams},
        snap_teams={11: teams, 12: teams},
        horizon_weeks=[11, 12],
        now=NOW,
    )
    # Week 12's late game kicked off four hours ago: not over yet.
    assert complete == [11] and not over
    # Week 11 again, but the snap counts have not landed for one team: its zero-point
    # appearances would be missing, so the week waits.
    complete, _ = complete_weeks(
        _games(11, NOW - timedelta(days=3)),
        stats_teams={11: teams},
        snap_teams={11: teams - {"DEN"}},
        horizon_weeks=[11],
        now=NOW,
    )
    assert complete == []
    complete, over = complete_weeks(
        _games(11, NOW - timedelta(days=3)),
        stats_teams={11: teams},
        snap_teams={11: teams},
        horizon_weeks=[11],
        now=NOW,
    )
    assert complete == [11] and over


@pytest.mark.parametrize(
    ("minimum_met", "season_complete", "recorded", "due"),
    [
        (False, False, {}, None),  # counting only
        (True, False, {}, "first"),  # the first time the minimum is met
        (True, False, {"first": "insufficient_evidence"}, None),  # waits for the season
        (True, True, {"first": "insufficient_evidence"}, "final"),
        (True, True, {"first": "promote"}, None),  # a decisive first look ends it
        (True, True, {"first": "reject"}, None),
        (True, True, {}, "final"),  # the minimum first met at the end: the final look alone
        (False, True, {}, "final"),  # the season ended short: the final look says so
        (True, True, {"first": "insufficient_evidence", "final": "promote"}, None),
    ],
)
def test_each_look_is_due_exactly_once(
    minimum_met: bool, season_complete: bool, recorded: dict[str, str], due: str | None
) -> None:
    taken = {look: {"outcome": outcome} for look, outcome in recorded.items()}
    counts = {"minimum_met": minimum_met}
    assert due_look(counts, season_complete=season_complete, recorded=taken) == due


def _run_prospective(store: Path, out: Path, *extra: str) -> dict[str, Any]:
    status = out / "status.json"
    assert (
        main(
            [
                "evaluate-weekly-v2-prospective",
                "--store",
                str(store),
                "--out",
                str(out),
                "--status",
                str(status),
                *extra,
            ],
        )
        == 0
    )
    return json.loads(status.read_text(encoding="utf-8"))


def test_the_scheduled_job_takes_each_look_once_and_records_it_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, out = tmp_path / "store", tmp_path / "out"
    snapshots = SnapshotStore(root=store, prefix="")
    clock = iter(NOW + timedelta(days=7 * index) for index in range(10))
    monkeypatch.setattr(weekly_cli, "_now", lambda: next(clock))
    season_over = {"value": False}
    same = _scored(weeks=8, v2_bias=3.0, v1_bias=3.0)

    def outcomes(eligible: pl.DataFrame, season: int, *, now: datetime):
        return same, list(range(1, 9)), season_over["value"]

    monkeypatch.setattr(weekly_cli, "_join_outcomes", outcomes)
    take = ("--take-due-look", "--confirm", WEEKLY_V2_PROSPECTIVE_TOKEN)

    # Without the token nothing is judged, the run fails (exit 2, the sealed-holdout code),
    # and nothing reaches the ledger.
    no_token = ["evaluate-weekly-v2-prospective", "--store", str(store), "--take-due-look"]
    assert main([*no_token, "--out", str(out)]) == 2
    assert recorded_looks(snapshots, season=2026) == {}

    # Counting alone never takes a look, even when one is due.
    status = _run_prospective(store, out)
    assert status["due"] == "first" and status["taken"] is None

    status = _run_prospective(store, out, *take)
    assert status["taken"] == "first" and status["outcome"] == "insufficient_evidence"
    assert not status["closed"]
    assert set(recorded_looks(snapshots, season=2026)) == {"first"}
    assert (out / "prospective_first.json").is_file()

    # A week later, same evidence: the first look is never taken again.
    status = _run_prospective(store, out, *take)
    assert status["due"] is None and status["taken"] is None

    season_over["value"] = True
    status = _run_prospective(store, out, *take)
    assert status["taken"] == "final" and status["closed"]
    looks = recorded_looks(snapshots, season=2026)
    assert set(looks) == {"first", "final"} and looks["final"]["look"] == "final"

    # Closed: a later run downloads nothing and takes nothing.
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a closed evaluation must not read outcomes")

    monkeypatch.setattr(weekly_cli, "_join_outcomes", forbidden)
    status = _run_prospective(store, out, *take)
    assert status["closed"] and status["taken"] is None

    # The store's own integrity check covers the looks, and the verdicts export for the card.
    captures, _, problems = verify_gameday_store(snapshots, season=2026)
    assert captures == 2 and problems == ()
    exported = tmp_path / "exported"
    export = ["evaluate-weekly-v2-prospective", "--store", str(store), "--export"]
    assert main([*export, "--out", str(exported)]) == 0
    assert sorted(path.name for path in exported.glob("prospective_*.json")) == [
        "prospective_final.json",
        "prospective_first.json",
    ]


def test_a_look_recorded_twice_refuses_rather_than_choosing(tmp_path: Path) -> None:
    snapshots = SnapshotStore(root=tmp_path, prefix="")
    for offset in (0, 7):
        write_gameday_capture(
            GamedayCapture(
                source_id=LOOK_SOURCE_ID,
                season=2026,
                observed_at_utc=NOW + timedelta(days=offset),
                rows=[],
                details={"look": "first", "verdict": {"outcome": "insufficient_evidence"}},
            ),
            store=snapshots,
        )
    with pytest.raises(SnapshotConflictError, match="recorded twice"):
        recorded_looks(snapshots, season=2026)
