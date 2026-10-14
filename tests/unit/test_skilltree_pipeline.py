"""The Skill Tree inside the in-season build (ADR-107): one play-by-play read, and failure
that costs its own artifacts and nothing else."""

from __future__ import annotations

from typing import Any

import polars as pl
import pytest

from ffdraft.pipeline import ros
from ffdraft.quality import QualityGate


def test_play_by_play_is_read_at_most_once_and_failures_are_reported(monkeypatch):
    calls: list[int] = []

    class Loaders:
        def load_pbp(self, seasons: list[int]) -> pl.DataFrame:
            calls.append(seasons[0])
            return pl.DataFrame({"season": [2026]})

    monkeypatch.setattr(ros, "nflverse_loaders", lambda: Loaders())
    frame, error = ros._load_play_by_play(None, allow_fetch=True, season=2026)
    assert error is None and frame is not None and calls == [2026]
    # A frame already in hand is never downloaded again; a replay never downloads at all.
    assert ros._load_play_by_play(frame, allow_fetch=True, season=2026)[0] is frame
    assert ros._load_play_by_play(None, allow_fetch=False, season=2026) == (None, None)
    assert calls == [2026]

    class Broken:
        def load_pbp(self, seasons: list[int]) -> pl.DataFrame:
            raise ConnectionError("500")

    monkeypatch.setattr(ros, "nflverse_loaders", lambda: Broken())
    assert ros._load_play_by_play(None, allow_fetch=True, season=2026) == (
        None,
        "ConnectionError: 500",
    )


def test_drive_breadth_reads_the_shared_frame_and_never_downloads(monkeypatch):
    def refuse() -> Any:  # pragma: no cover - reaching it is the failure
        raise AssertionError("drive breadth must not download play-by-play itself")

    monkeypatch.setattr(ros, "nflverse_loaders", refuse)
    gate = QualityGate()
    usage = [{"player_id": "gsis:00-0000001", "position": "WR", "weeks": []}]
    summary = ros._drive_breadth(
        usage,
        roster=pl.DataFrame(),
        season=2026,
        through_week=5,
        pbp=None,
        pbp_error="ConnectionError: 500",
        gate=gate,
    )
    assert summary["status"] == "unavailable"
    assert "ConnectionError" in summary["reason"]
    assert any(check.check_id == "ros.drive_breadth_failed" for check in gate.checks)


def test_a_skill_tree_failure_withholds_both_artifacts_and_keeps_the_build(monkeypatch):
    import ffdraft.signals.skilltree as skilltree

    def explode(**_: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(skilltree, "build_skill_tree", explode)

    class Sources:
        weekly_stats = pl.DataFrame()
        schedule = pl.DataFrame()
        player_master = pl.DataFrame()
        rosters: dict[int, pl.DataFrame] = {}
        snap_counts = pl.DataFrame()

    class Loaded:
        sources = Sources()

    gate = QualityGate()
    records, definitions, summary = ros._skill_tree(
        records={},
        snapshot_frame=pl.DataFrame(),
        registry=None,
        loaded=Loaded(),
        roster=pl.DataFrame(),
        pbp=None,
        pbp_error=None,
        nextgen=None,
        combine_testers=None,
        allow_fetch=False,
        season=2026,
        cutoff=ros.RosCutoff(season=2026, through_week=5),
        build_id="b",
        gate=gate,
    )
    assert records == [] and definitions == []
    assert summary == {
        "method_version": "skill_tree_v1",
        "status": "failed",
        "reason": "RuntimeError: boom",
    }
    assert gate.passed  # a warning, never a critical
    assert any(check.check_id == "ros.skill_tree_failed" for check in gate.checks)


@pytest.mark.parametrize("artifact", ["player_skill_tree", "skill_tree_definitions"])
def test_the_validator_knows_both_artifacts_are_in_season(artifact: str):
    from ffdraft.artifacts import validate

    assert artifact in validate._IN_SEASON_ARTIFACTS
