"""An empty MFL capture after drafting ends is the market draining, not an outage (ADR-095).

The scheduled refresh of 2026-09-30 failed its *capture* job on ``market.capture_empty``:
MyFantasyLeague's draft feed had thinned from 735 keeper-free drafts (2026-08-31) to 28
(2026-09-24) and then to four drafts with no price rows in any cohort. Until that day the
check was right to be critical — an empty capture during draft season is an outage — but the
draft board has read the draft-time market since ADR-094, so nothing downstream needed the
row, and the failed capture job skipped the build and the deploy: the in-season site stopped
refreshing over a feed nobody reads.

The fix is a flag the caller sets from the season state, so these tests pin both halves of it:
after the window closes an empty capture warns and appends nothing, and *before* it closes the
same capture is still a critical failure that is still written down the same way.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import ffdraft.market.capture as capture_module
from ffdraft.cli import main
from ffdraft.identity.aliases import AliasMap
from ffdraft.market.capture import build_snapshot, capture_market
from ffdraft.market.identity import load_market_identity
from ffdraft.market.snapshot import MarketSnapshotStore
from ffdraft.sources import NflversePlayerIdsAdapter, NflverseRosterAdapter
from ffdraft.sources.market import MFL_SOURCE_ID

SEASON = 2026
STAMP = datetime(2026, 9, 30, 11, 27, 47, tzinfo=UTC)

#: What MFL answered on 2026-09-30: an envelope that still counts drafts and carries no rows.
DRAINED = {"adp": {"timestamp": "1790767667", "totalDrafts": "4", "totalPicks": "0"}}
DRAINED_EXPLICIT = {
    "adp": {"timestamp": "1790767667", "totalDrafts": "4", "totalPicks": "0", "player": []},
}

CLOSED = "market.capture_empty_post_draft"
OPEN = "market.capture_empty"


@pytest.fixture
def identity(pipeline_fixture_dir: Path) -> Any:
    roster = NflverseRosterAdapter().normalize(
        json.loads((pipeline_fixture_dir / "nflverse_rosters.json").read_text()),
        season=SEASON,
        retrieved_at=STAMP,
    )
    ids = NflversePlayerIdsAdapter().normalize(
        json.loads((pipeline_fixture_dir / "nflverse_ff_playerids.json").read_text()),
        retrieved_at=STAMP,
    )
    assert isinstance(roster.frame, pl.DataFrame)
    return load_market_identity(SEASON, as_of=STAMP, roster=roster.frame, player_ids=ids.frame)


@pytest.fixture
def players(pipeline_fixture_dir: Path) -> Any:
    return json.loads((pipeline_fixture_dir / "mfl_players.json").read_text())


@pytest.fixture
def priced(pipeline_fixture_dir: Path) -> Any:
    return json.loads((pipeline_fixture_dir / "mfl_adp.json").read_text())


@pytest.fixture
def store(tmp_path: Path) -> MarketSnapshotStore:
    return MarketSnapshotStore(tmp_path / "market-data")


def _ids(result: Any) -> dict[str, Any]:
    return {check.check_id: check for check in result.gate.checks}


def _snapshot(players: Any, identity: Any, payload: Any, **kwargs: Any) -> Any:
    return build_snapshot(
        season=SEASON,
        retrieved_at=STAMP,
        raw_by_cohort={
            "unfiltered": payload,
            "no-keeper": payload,
            "no-mock-no-keeper": payload,
            "ppr-no-keeper": payload,
        },
        raw_players=players,
        identity=identity,
        aliases=AliasMap.empty(),
        **kwargs,
    )


def _serve(monkeypatch: pytest.MonkeyPatch, players: Any, adp: Any) -> None:
    def fetch(*, params: dict[str, str], **_: object) -> Any:
        return players if params.get("TYPE") == "players" else adp

    monkeypatch.setattr(capture_module, "_fetch_json", fetch)


# --- the verdict -----------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [DRAINED, DRAINED_EXPLICIT], ids=["no-rows", "empty-list"])
def test_an_empty_capture_is_still_critical_while_drafts_are_running(
    players: Any,
    identity: Any,
    payload: Any,
) -> None:
    """The default. An outage during draft season must keep failing the job."""
    result = _snapshot(players, identity, payload)
    checks = _ids(result)

    assert result.rows == []
    assert OPEN in checks
    assert checks[OPEN].blocking
    assert CLOSED not in checks
    assert not result.gate.passed


@pytest.mark.parametrize("payload", [DRAINED, DRAINED_EXPLICIT], ids=["no-rows", "empty-list"])
def test_an_empty_capture_after_the_draft_window_closes_is_a_warning(
    players: Any,
    identity: Any,
    payload: Any,
) -> None:
    result = _snapshot(players, identity, payload, draft_window_closed=True)
    checks = _ids(result)

    assert result.rows == []
    assert CLOSED in checks
    assert not checks[CLOSED].blocking
    assert OPEN not in checks
    assert result.gate.passed
    # Still counted, so a run summary can say the market drained rather than say nothing.
    assert CLOSED in {check.check_id for check in result.gate.warnings}


def test_the_closed_window_does_not_change_a_capture_that_priced_something(
    players: Any,
    identity: Any,
    priced: Any,
) -> None:
    open_window = _snapshot(players, identity, priced)
    closed_window = _snapshot(players, identity, priced, draft_window_closed=True)

    assert open_window.rows
    assert closed_window.rows == open_window.rows
    for result in (open_window, closed_window):
        checks = _ids(result)
        assert "market.capture_nonempty" in checks
        assert OPEN not in checks
        assert CLOSED not in checks
        assert result.gate.passed


def test_a_single_priced_cohort_is_not_an_empty_capture(
    players: Any,
    identity: Any,
    priced: Any,
) -> None:
    """Emptiness is a property of the capture, not of one cohort (ADR-012 keeps those)."""
    result = build_snapshot(
        season=SEASON,
        retrieved_at=STAMP,
        raw_by_cohort={"unfiltered": priced, "no-keeper": DRAINED},
        raw_players=players,
        identity=identity,
        aliases=AliasMap.empty(),
        draft_window_closed=True,
    )
    checks = _ids(result)

    assert result.rows
    assert "market.capture_nonempty" in checks
    assert CLOSED not in checks


# --- what reaches the store -------------------------------------------------------------------


def test_a_drained_capture_after_the_window_closes_writes_nothing(
    store: MarketSnapshotStore,
    identity: Any,
    players: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero-price snapshot is not evidence of a price, and the store is immutable."""
    _serve(monkeypatch, players, DRAINED)

    result = capture_market(
        season=SEASON,
        store=store,
        as_of=STAMP,
        identity=identity,
        pause_seconds=0.0,
        draft_window_closed=True,
    )

    assert result.gate.passed
    assert result.write is None
    assert result.withheld
    assert store.keys(MFL_SOURCE_ID, SEASON) == []
    assert [path for path in store.root.rglob("*") if path.is_file()] == []


def test_a_priced_capture_after_the_window_closes_is_still_retained(
    store: MarketSnapshotStore,
    identity: Any,
    players: Any,
    priced: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The thinning tail keeps being recorded; only a capture with *nothing* is withheld."""
    _serve(monkeypatch, players, priced)

    result = capture_market(
        season=SEASON,
        store=store,
        as_of=STAMP,
        identity=identity,
        pause_seconds=0.0,
        draft_window_closed=True,
    )

    assert result.gate.passed
    assert result.withheld is None
    assert result.write is not None
    assert len(store.keys(MFL_SOURCE_ID, SEASON)) == 1


def test_an_empty_capture_before_the_window_closes_is_not_withheld_by_the_new_path(
    store: MarketSnapshotStore,
    identity: Any,
    players: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flag is opt-in: the default path keeps its behaviour and its critical verdict."""
    _serve(monkeypatch, players, DRAINED)

    result = capture_market(
        season=SEASON,
        store=store,
        as_of=STAMP,
        identity=identity,
        pause_seconds=0.0,
    )

    assert not result.gate.passed
    assert result.withheld is None


# --- the command the workflow runs ------------------------------------------------------------


def _run_cli(
    monkeypatch: pytest.MonkeyPatch,
    store: MarketSnapshotStore,
    identity: Any,
    *extra: str,
) -> int:
    """``snapshot-market`` with the network and the identity load replaced."""
    import ffdraft.cli as cli_module

    real = cli_module.capture_market

    def with_identity(**kwargs: Any) -> Any:
        return real(identity=identity, **kwargs)

    monkeypatch.setattr(cli_module, "capture_market", with_identity)
    return main(
        [
            "snapshot-market",
            "--season",
            str(SEASON),
            "--store",
            str(store.root),
            "--as-of",
            "2026-09-30T11:27:47Z",
            "--pause",
            "0",
            *extra,
        ],
    )


def test_the_command_exits_zero_and_says_why_nothing_was_retained(
    store: MarketSnapshotStore,
    identity: Any,
    players: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _serve(monkeypatch, players, DRAINED)

    code = _run_cli(monkeypatch, store, identity, "--draft-window-closed")
    out = capsys.readouterr().out

    assert code == 0
    assert "normalized rows: 0" in out
    assert "not retained" in out
    assert CLOSED in out
    assert "quality gate: pass" in out
    assert store.keys(MFL_SOURCE_ID, SEASON) == []


def test_the_command_still_exits_nonzero_without_the_flag(
    store: MarketSnapshotStore,
    identity: Any,
    players: Any,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _serve(monkeypatch, players, DRAINED)

    code = _run_cli(monkeypatch, store, identity)
    out = capsys.readouterr().out

    assert code == 1
    assert f"[critical] {OPEN}" in out
    assert "quality gate: fail" in out
