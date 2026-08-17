"""Opt-in live source smoke tests (docs/TEST_STRATEGY.md 2.4).

These are deliberately excluded from the default test run (`-m 'not live'`) so that local
development and PR CI never depend on third-party availability. Run them when you want to
know whether an upstream contract has drifted::

    uv run pytest -m live

Each test asserts only the contract the pipeline actually relies on, so a cosmetic upstream
addition does not fail the suite but a removed key does.
"""

from __future__ import annotations

import pytest
import source_probe as sp

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def http() -> sp.HttpProbe:
    return sp.HttpProbe(timeout=60.0, sleep_seconds=1.0)


def _require_reachable(finding: sp.Finding) -> None:
    if finding.status == sp.BLOCKED_EGRESS:
        pytest.skip(f"{finding.source_id} unreachable from this environment: {finding.notes}")


def test_nflverse_player_stats_exposes_scoring_components():
    findings = sp.probe_nflverse(
        [
            (
                "live_player_stats_2024",
                "load_player_stats",
                {"seasons": [2024], "summary_level": "reg"},
                "live smoke",
            )
        ]
    )
    finding = findings[0]
    _require_reachable(finding)
    assert finding.status == sp.OK
    assert (finding.record_count or 0) > 500
    columns = {column["name"] for column in finding.columns}
    # The scoring engine is built from raw components, not upstream fantasy totals.
    for required in (
        "player_id",
        "position",
        "passing_yards",
        "passing_tds",
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "receiving_yards",
        "receiving_tds",
    ):
        assert required in columns, f"missing scoring component: {required}"


def test_nflverse_current_roster_carries_canonical_ids():
    findings = sp.probe_nflverse(
        [("live_rosters_current", "load_rosters", {"seasons": [2026]}, "live smoke")]
    )
    finding = findings[0]
    _require_reachable(finding)
    assert finding.status == sp.OK
    columns = {column["name"] for column in finding.columns}
    assert {"gsis_id", "sleeper_id", "espn_id", "status"} <= columns


def test_mfl_current_adp_returns_priced_players(http: sp.HttpProbe):
    finding = sp._probe_mfl_adp(
        http,
        check_id="live_mfl_adp",
        year=2026,
        params={"TYPE": "adp", "JSON": 1},
        question="live smoke",
    )
    _require_reachable(finding)
    assert finding.status == sp.OK
    assert (finding.record_count or 0) >= 100
    fields = {column["name"] for column in finding.columns}
    assert "id" in fields
    assert "averagePick" in fields


def test_sleeper_state_and_players(http: sp.HttpProbe):
    findings = {f.check_id: f for f in sp.probe_sleeper(http)}
    state = findings["sleeper_state_nfl"]
    _require_reachable(state)
    assert state.status == sp.OK
    assert {"season", "week", "season_type"} <= set(state.coverage)

    players = findings["sleeper_players_nfl"]
    _require_reachable(players)
    assert players.status == sp.OK
    assert (players.record_count or 0) > 1000
    fields = {column["name"] for column in players.columns}
    assert {"player_id", "position", "team"} <= fields
