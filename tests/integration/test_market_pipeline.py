"""The Phase-5 market pipeline end to end, from retained bytes to a published board.

Everything here is offline and deterministic: a synthetic append-only store, a synthetic
tier artifact, and the frozen cohort selection. That is the property the whole Phase-5
architecture was arranged for — an arbitrage board is a pure function of retained evidence,
so it can be rebuilt months later and diffed against the commit that captured it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from ffdraft.artifacts import validate_artifact_directory, write_artifact
from ffdraft.market.cohorts import (
    CANDIDATE_COHORTS,
    CohortMeasurement,
    cohort_by_id,
    select_cohorts,
)
from ffdraft.market.snapshot import (
    CohortCapture,
    MarketSnapshotStore,
    SnapshotManifest,
)
from ffdraft.pipeline.market import ArbitrageBuildRequest, run_arbitrage_build
from ffdraft.retention import canonical_json, content_hash, gzip_bytes, snapshot_key
from ffdraft.timeutil import isoformat_utc, parse_utc

SOURCE = "myfantasyleague_adp"
SEASON = 2026
BUILD_ID = "2026-intrinsic-cb-hurdle-v1-20260820T120000Z"
GENERATED_AT = parse_utc("2026-08-20T12:00:00Z")

#: A synthetic board deep enough that the production coverage gate means something.
#:
#: Three players are named because the tests reason about them: an aligned favourite, a
#: clear bargain the market is late on, and a reach the market is early on. The rest are
#: filler priced near their fair rank, and exactly one is left unpriced so the "no price,
#: no arbitrage row" path is exercised without dragging coverage under the gate.
_NAMED: tuple[tuple[int, str, str, float | None, int | None], ...] = (
    (1, "Aurelio Banks", "RB", 2.4, 400),
    (2, "Kester Aduba", "WR", 2.0, 380),
    (3, "Noel Ferrante", "WR", 18.0, 350),
    (4, "Idris Vantol", "QB", 3.0, 300),
    (5, "Pace Whitfield", "TE", None, None),
)
_POSITIONS = ("RB", "WR", "QB", "TE")


def _board() -> list[tuple[str, int, str, str, float | None, int | None]]:
    rows = [
        (f"gsis:00-{rank:07d}", rank, name, position, adp, sample)
        for rank, name, position, adp, sample in _NAMED
    ]
    rows.extend(
        (
            f"gsis:00-{rank:07d}",
            rank,
            f"Filler {rank}",
            _POSITIONS[rank % len(_POSITIONS)],
            float(rank) + 1.5,
            120,
        )
        for rank in range(6, 26)
    )
    return rows


BOARD = _board()

PRESETS = [("PPR", 12)]


def _tier_records() -> list[dict[str, object]]:
    return [
        {
            "schema_version": "1.0",
            "build_id": BUILD_ID,
            "league_preset_id": "redraft-12",
            "scoring_preset": "PPR",
            "player_id": player_id,
            "display_name": name,
            "team": "BUF",
            "position": position,
            "fair_rank": rank,
            "position_rank": 1,
            "tier_ordinal": 1,
            "tier_label": "Tier 1",
            "expected_vorp": 100.0 - rank,
            "p10_vorp": 10.0,
            "p25_vorp": 20.0,
            "p50_vorp": 30.0,
            "p75_vorp": 40.0,
            "p90_vorp": 50.0,
            "expected_points": 250.0 - rank,
            "uncertainty": 20.0,
            "quality_flags": [],
        }
        for player_id, rank, name, position, _adp, _sample in BOARD
    ]


def _market_rows(cohort_id: str, *, shift: float = 0.0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for player_id, _rank, name, position, adp, sample in BOARD:
        if adp is None:
            continue
        rows.append(
            {
                "source_id": SOURCE,
                "season": SEASON,
                "cohort_id": cohort_id,
                "external_player_id": player_id.split(":")[1],
                "player_id": player_id,
                "resolution_reason": "both_bridges_agree",
                "resolution_bridges": ["espn_id_via_nflverse_rosters", "mfl_id_via_ff_playerids"],
                "display_name": name,
                "position": position,
                "team": "BUF",
                "average_pick": adp + shift,
                "market_rank": int(adp),
                "min_pick": max(1.0, adp - 4.0),
                "max_pick": adp + 8.0,
                "sample_size": sample,
                "selection_pct": 90.0,
                "entity_kind": "player",
                "raw_position": position,
                "source_format_detail": cohort_by_id(cohort_id).filter_query,
                "quality_flags": ["adp_sd_unavailable", "source_as_of_unavailable"],
            },
        )
    return rows


def _write_snapshot(
    store: MarketSnapshotStore,
    moment: str,
    *,
    cohort_id: str = "no-keeper",
    shift: float = 0.0,
) -> str:
    stamped = parse_utc(moment)
    raw = gzip_bytes(canonical_json({"adp": {"player": []}}))
    rows = _market_rows(cohort_id, shift=shift)
    manifest = SnapshotManifest(
        manifest_version="1.0",
        source_id=SOURCE,
        season=SEASON,
        snapshot_key=snapshot_key(stamped),
        retrieved_at_utc=isoformat_utc(stamped),
        adapter_version="2.0",
        source_policy_version="mfl-developer-rules/2026-08-17",
        cohorts=(
            CohortCapture(
                cohort_id=cohort_id,
                filters=dict(cohort_by_id(cohort_id).filters),
                label=cohort_by_id(cohort_id).label,
                raw_path=f"cohorts/{cohort_id}/adp.raw.json.gz",
                raw_content_hash=content_hash(raw),
                row_count=len(rows),
                total_drafts=500,
                resolved_players=len(rows),
                resolvable_players=len(rows),
            ),
        ),
    )
    store.write(
        manifest=manifest,
        normalized_rows=rows,
        raw_payloads={f"cohorts/{cohort_id}/adp.raw.json.gz": raw},
    )
    return manifest.snapshot_key


FFC_SOURCE = "fantasyfootballcalculator_adp"
FFC_COHORT = "ffc-ppr"


def _ffc_rows(*, shift: float = 0.0, drop: frozenset[str] = frozenset()) -> list[dict[str, object]]:
    """A retained Fantasy Football Calculator snapshot's normalized rows.

    Deliberately *not* MyFantasyLeague's shape: a scoring-tagged cohort, a rolling window, a
    genuine standard deviation, no order statistics, and a null ``league_size`` because FFC
    accepts ``teams`` and ignores it (ADR-056). Only a source that differs in these ways can
    catch a pipeline that quietly treats every market as the first one.
    """
    rows: list[dict[str, object]] = []
    for player_id, _rank, name, position, adp, sample in BOARD:
        if adp is None or player_id in drop:
            continue
        rows.append(
            {
                "source_id": FFC_SOURCE,
                "season": SEASON,
                "cohort_id": FFC_COHORT,
                "market_signal_type": "adp",
                "external_player_id": f"ffc:{player_id}",
                "player_id": player_id,
                "display_name": name,
                "position": position,
                "raw_position": position,
                "team": "BUF",
                # FFC prices a riser earlier than MyFantasyLeague's season aggregate, so the
                # two markets genuinely disagree. Agreement is what hides a consumer reading
                # the wrong one.
                "average_pick": round(adp * 0.9 + shift, 2),
                "market_rank": None,
                "min_pick": None,
                "max_pick": None,
                "adp_sd": 3.4,
                "consensus_rank_mean": None,
                "consensus_rank_min": None,
                "consensus_rank_max": None,
                "consensus_rank_sd": None,
                "sample_size": sample,
                "selection_pct": None,
                "scoring_preset": "PPR",
                "league_size": None,
                "aggregation_window_type": "rolling",
                "aggregation_window_days": 7,
                "entity_kind": "player",
                "source_display_name": name,
                "source_team": "BUF",
                "source_format_detail": "format=ppr&position=all&teams=12",
                "quality_flags": ["league_size_not_observed"],
            },
        )
    return rows


def _write_ffc_snapshot(
    store: MarketSnapshotStore,
    moment: str,
    *,
    shift: float = 0.0,
    drop: frozenset[str] = frozenset(),
) -> str:
    stamped = parse_utc(moment)
    raw = gzip_bytes(canonical_json({"players": []}))
    rows = _ffc_rows(shift=shift, drop=drop)
    manifest = SnapshotManifest(
        manifest_version="1.0",
        source_id=FFC_SOURCE,
        season=SEASON,
        snapshot_key=snapshot_key(stamped),
        retrieved_at_utc=isoformat_utc(stamped),
        adapter_version="1.0",
        source_policy_version="ffc-adp-rest-api-terms/2026-09-02",
        cohorts=(
            CohortCapture(
                cohort_id=FFC_COHORT,
                filters={"format": "ppr", "teams": "12", "position": "all"},
                label="FFC recent PPR ADP",
                raw_path=f"cohorts/{FFC_COHORT}/adp.raw.json.gz",
                raw_content_hash=content_hash(raw),
                row_count=len(rows),
                resolved_players=len(rows),
                resolvable_players=len(rows),
            ),
        ),
    )
    store.write(
        manifest=manifest,
        normalized_rows=rows,
        raw_payloads={f"cohorts/{FFC_COHORT}/adp.raw.json.gz": raw},
    )
    return manifest.snapshot_key


def _sufficient(cohort_id: str) -> CohortMeasurement:
    """A cohort that clears every clause of the frozen rule comfortably."""
    return CohortMeasurement(
        cohort_id=cohort_id,
        filters=dict(cohort_by_id(cohort_id).filters),
        priced_players=320,
        total_drafts=500,
        total_picks=900,
        resolved_players=315,
        resolvable_players=320,
        ambiguous_players=0,
        non_player_entities=12,
        top100_board_coverage=0.99,
        top150_board_coverage=0.96,
        median_top150_sample_size=90.0,
        min_pick_available=320,
        max_pick_available=320,
        adp_min=1.2,
        adp_max=220.0,
        total_rows=340,
        non_core_rows=18,
        unclassified_rows=2,
    )


def _insufficient(cohort_id: str) -> CohortMeasurement:
    """A cohort that clears every clause except the volume bar - the 2026 launch condition.

    ADR-045: filtering to keeper-free drafts necessarily shrinks the cohort-level count, so
    ``min_total_drafts`` is the one clause a qualifying cohort fails while its per-player
    evidence stays intact.
    """
    return replace(_sufficient(cohort_id), total_drafts=125)


def _selection(
    path: Path,
    *,
    cohort_id: str = "no-keeper",
    sufficient: bool = True,
) -> Path:
    measure = _sufficient if sufficient else _insufficient
    measurements = {
        cohort.cohort_id: measure(cohort.cohort_id)
        for cohort in CANDIDATE_COHORTS
        if cohort.cohort_id == cohort_id
    }
    assignments, _ = select_cohorts(measurements, presets=PRESETS)
    path.write_text(
        json.dumps(
            {
                "rule_version": "phase5_cohort_v1",
                "snapshot_key": "2026-08-20T12-00-00Z",
                "assignments": [item.to_dict() for _, item in sorted(assignments.items())],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def artifacts(tmp_path) -> Path:
    directory = tmp_path / "data"
    directory.mkdir()
    # Written through the production serializer, so the synthetic board is a real artifact
    # rather than a hand-rolled shape the validator would reject for the wrong reason.
    _paths, checks = write_artifact(
        "tiers",
        _tier_records(),
        out_dir=directory,
        build_id=BUILD_ID,
        generated_at=GENERATED_AT,
    )
    assert not [check for check in checks if check.blocking]
    (directory / "build_metadata.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "build_id": BUILD_ID,
                "generated_at_utc": isoformat_utc(GENERATED_AT),
                "git_sha": "0000000",
                "season": SEASON,
                "intrinsic_model_version": "intrinsic-cb-hurdle-v1",
                "arbitrage_mode": "baseline",
                "arbitrage_model_version": None,
                "supported_presets": ["redraft-10", "redraft-12", "redraft-14"],
                "sources": [
                    {
                        "source_id": "nflreadpy",
                        "status": "pass",
                        "retrieved_at_utc": isoformat_utc(GENERATED_AT),
                        "record_count": 100,
                        "warnings": [],
                    },
                ],
                "quality_gate": {"status": "pass", "critical_failures": 0, "warnings": 1},
                "warnings": [
                    "tiers are published having not passed the frozen tier stability gate",
                ],
                "methodology_version": "phase4_intrinsic_v1",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return directory


@pytest.fixture
def store(tmp_path) -> MarketSnapshotStore:
    return MarketSnapshotStore(root=tmp_path / "market-data")


def _run(store, artifacts, tmp_path, **overrides):
    overrides.setdefault("selection_path", _selection(tmp_path / "cohorts.json"))
    request = ArbitrageBuildRequest(
        season=SEASON,
        store=store,
        artifacts_dir=artifacts,
        as_of=GENERATED_AT,
        **overrides,
    )
    return run_arbitrage_build(request)


# --------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------


def test_a_board_is_built_from_retained_bytes_alone(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)

    assert result.gate.passed, [check.to_dict() for check in result.gate.critical_failures]
    assert len(result.records) == len(BOARD) - 1, "the unpriced player has no arbitrage row"
    assert (artifacts / "arbitrage.json").is_file()
    assert (artifacts / "arbitrage.csv").is_file()

    gate = validate_artifact_directory(artifacts)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


def test_the_sign_convention_survives_the_whole_pipeline(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    by_id = {record["player_id"]: record for record in result.records}

    # Fair rank 3, market ADP 18: the model would take him fifteen picks earlier.
    bargain = by_id["gsis:00-0000003"]
    assert bargain["rank_gap"] == 15.0
    assert bargain["regional_value_gap"] > 0

    # Fair rank 4, market ADP 3: the market is reaching.
    reach = by_id["gsis:00-0000004"]
    assert reach["rank_gap"] == -1.0
    assert reach["regional_value_gap"] < 0

    assert bargain["arbitrage_score"] > reach["arbitrage_score"]
    for record in result.records:
        assert record["rank_gap"] == pytest.approx(
            record["market_adp"] - record["fair_rank"],
            abs=1e-6,
        )


def test_baseline_mode_publishes_no_learned_fields(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    for record in result.records:
        assert record["arbitrage_mode"] == "baseline"
        assert record["expected_surplus_vorp"] is None
        assert record["p_positive_surplus"] is None
        assert record["market_adp_sd"] is None
    envelope = json.loads((artifacts / "arbitrage.json").read_text())
    assert envelope["arbitrage_mode"] == "baseline"


def test_every_row_carries_its_market_provenance(store, artifacts, tmp_path):
    key = _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    for record in result.records:
        assert record["market_source_id"] == SOURCE
        assert record["market_cohort_id"] == "no-keeper"
        assert "approximate cohort" in record["market_cohort_detail"]
        assert record["market_snapshot_at_utc"] == "2026-08-20T11:00:00Z"
        assert record["market_adp_low"] is not None
        assert record["market_adp_high"] is not None
    assert result.snapshot_key == key


def test_the_build_is_deterministic(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    first = _run(store, artifacts, tmp_path)
    first_bytes = (artifacts / "arbitrage.json").read_bytes()
    second = _run(store, artifacts, tmp_path)
    assert first.records == second.records
    assert (artifacts / "arbitrage.json").read_bytes() == first_bytes


# --------------------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------------------


def test_a_single_snapshot_publishes_a_null_trend(store, artifacts, tmp_path):
    """The expected launch state. Null plus a flag, never a fabricated movement."""
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    assert result.trend_available is False
    for record in result.records:
        assert record["market_trend"] is None
        assert "insufficient_trend_history" in record["quality_flags"]


def test_enough_retained_history_turns_the_trend_on(store, artifacts, tmp_path):
    for offset, shift in ((3, 6.0), (2, 4.0), (0, 0.0)):
        moment = GENERATED_AT - timedelta(days=offset, hours=1)
        _write_snapshot(store, isoformat_utc(moment), shift=shift)
    result = _run(store, artifacts, tmp_path)

    assert result.trend_available is True
    assert len(result.trend_history_keys) == 3
    for record in result.records:
        assert record["market_trend"] is not None
        # Every ADP fell over the window, so every player is being taken earlier.
        assert record["market_trend"] > 0
        assert "insufficient_trend_history" not in record["quality_flags"]


# --------------------------------------------------------------------------------------
# Every retained market has a history, not just the first one (ADR-081)
# --------------------------------------------------------------------------------------
#
# The defect these cover was invisible to every gate in the repository. `pipeline/market.py`
# loaded a trailing window for MyFantasyLeague and read only the *latest* snapshot for every
# other source, so a second market arrived with a price and a structurally null trend, and
# `market_trend_series.json` carried no record for it at all. The artifact was valid; the
# board was valid; the card said "0 snapshots so far" beside a current FFC ADP while seven
# real FFC snapshots sat in the store.
#
# Nothing here asserts a number the frozen rule did not produce. What they assert is that the
# rule is *asked*, once per source, over that source's own retained window.


def test_retained_ffc_snapshots_produce_an_ffc_series(store, artifacts, tmp_path):
    """The failing case, stated directly: FFC snapshots exist, so an FFC history exists."""
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    for moment in ("2026-08-18T11:00:00Z", "2026-08-19T11:00:00Z", "2026-08-20T11:05:00Z"):
        _write_ffc_snapshot(store, moment)
    result = _run(store, artifacts, tmp_path)

    ffc = [row for row in result.trend_series if row["market_source_id"] == FFC_SOURCE]
    assert ffc, "retained FFC snapshots must produce an FFC history"
    assert {row["cohort_id"] for row in ffc} == {FFC_COHORT}
    assert all(len(row["points"]) == 3 for row in ffc)


def test_retained_mfl_snapshots_produce_an_mfl_series(store, artifacts, tmp_path):
    """The behaviour that already worked, pinned so generalising it cannot lose it."""
    for offset, shift in ((3, 6.0), (2, 4.0), (0, 0.0)):
        moment = GENERATED_AT - timedelta(days=offset, hours=1)
        _write_snapshot(store, isoformat_utc(moment), shift=shift)
    result = _run(store, artifacts, tmp_path)

    mfl = [row for row in result.trend_series if row["market_source_id"] == SOURCE]
    assert mfl
    assert all(len(row["points"]) == 3 for row in mfl)
    assert all(row["market_trend"] is not None for row in mfl)


def test_each_market_keeps_its_own_history_and_its_own_slope(store, artifacts, tmp_path):
    """Two markets, two windows, two answers — and one of them is null on purpose.

    MyFantasyLeague has four days of span and clears `phase5_trend_v1`. FFC has three
    observations inside two days: enough to draw, not enough to fit. That is the production
    state on the day the bug was found, and the point is that the two states coexist in one
    build without either being borrowed from the other.
    """
    for offset, shift in ((4, 8.0), (2, 4.0), (0, 0.0)):
        _write_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(days=offset, hours=1)))
        del shift
    for hours, shift in ((30.0, 1.2), (20.0, 0.8), (2.0, 0.0)):
        _write_ffc_snapshot(
            store,
            isoformat_utc(GENERATED_AT - timedelta(hours=hours)),
            shift=shift,
        )
    result = _run(store, artifacts, tmp_path)

    by_source: dict[str, list[dict]] = {}
    for row in result.trend_series:
        by_source.setdefault(str(row["market_source_id"]), []).append(row)
    assert set(by_source) == {SOURCE, FFC_SOURCE}
    # No synthetic market. `cross` is a view the reader selects, not a source anyone captured.
    assert "cross" not in by_source

    assert all(row["market_trend"] is None for row in by_source[FFC_SOURCE]), (
        "FFC spans 28 hours; the frozen rule needs three days and must not be softened"
    )
    assert all(len(row["points"]) == 3 for row in by_source[FFC_SOURCE]), (
        "the chart draws what was observed even while the slope is uncomputable"
    )

    ffc_quotes = [
        entry
        for record in result.records
        for entry in record["markets"]
        if entry["source_id"] == FFC_SOURCE
    ]
    assert ffc_quotes
    assert all(entry["market_trend"] is None for entry in ffc_quotes)
    assert all("insufficient_trend_history" in entry["quality_flags"] for entry in ffc_quotes), (
        "a null slope must say why it is null rather than reading as no movement"
    )


def test_a_markets_slope_and_its_charted_history_are_one_number(store, artifacts, tmp_path):
    """ADR-066 promised this agreement and nothing checked it. Now the validator does."""
    for offset in (4, 2, 0):
        _write_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(days=offset, hours=1)))
    for offset in (4, 2, 0):
        _write_ffc_snapshot(
            store,
            isoformat_utc(GENERATED_AT - timedelta(days=offset, hours=2)),
            shift=float(offset),
        )
    result = _run(store, artifacts, tmp_path)
    assert result.gate.passed

    published = {
        (
            str(record["league_preset_id"]),
            str(record["scoring_preset"]),
            str(entry["source_id"]),
            str(record["player_id"]),
        ): entry
        for record in result.records
        for entry in record["markets"]
    }
    assert result.trend_series
    for row in result.trend_series:
        key = (
            str(row["league_preset_id"]),
            str(row["scoring_preset"]),
            str(row["market_source_id"]),
            str(row["player_id"]),
        )
        quote = published[key]
        assert row["market_trend"] == quote["market_trend"]
        assert row["points"][-1]["market_adp"] == pytest.approx(quote["market_adp"], abs=0.01)

    gate = validate_artifact_directory(artifacts)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]
    assert any(check.check_id == "cross_artifact.trend_series_agreement" for check in gate.checks)


def test_ffcs_cohort_is_mapped_across_every_supported_league_size(store, artifacts, tmp_path):
    """One FFC cohort per scoring preset, repeated across sizes — never claimed as observed.

    FFC accepts ``teams`` and ignores it (ADR-056). The map is keyed by preset *and* size
    because that is how the series writer asks; the value does not vary with size because the
    source cannot see the difference, and the published ``league_size`` stays null so nothing
    downstream can read the repetition as an observation.
    """
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    _write_ffc_snapshot(store, "2026-08-20T11:05:00Z")
    result = _run(store, artifacts, tmp_path)

    ffc = [row for row in result.trend_series if row["market_source_id"] == FFC_SOURCE]
    assert ffc
    assert {row["cohort_id"] for row in ffc} == {FFC_COHORT}
    quotes = [
        entry
        for record in result.records
        for entry in record["markets"]
        if entry["source_id"] == FFC_SOURCE
    ]
    assert quotes
    assert all(entry["league_size"] is None for entry in quotes)


def test_a_player_a_market_has_dropped_keeps_no_chart_under_that_market(store, artifacts, tmp_path):
    """The window is seven days wide; a market's current price list is not.

    A player FFC quoted on Tuesday and dropped by Friday still has observations inside the
    window. Charting them would put an FFC history under a card that says "no current FFC
    ADP" — the same category of contradiction as the borrowed slope, reached from the other
    side. Found by the new cross-artifact check on a real 2026 build, on 20 players.
    """
    dropped = BOARD[1][0]
    _write_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(hours=1)))
    _write_ffc_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(days=2)))
    _write_ffc_snapshot(
        store,
        isoformat_utc(GENERATED_AT - timedelta(hours=2)),
        drop=frozenset({dropped}),
    )
    result = _run(store, artifacts, tmp_path)

    ffc = [row for row in result.trend_series if row["market_source_id"] == FFC_SOURCE]
    assert ffc, "the market that still prices the board keeps its history"
    assert dropped not in {row["player_id"] for row in ffc}
    # ...and MyFantasyLeague, which does still price him, keeps his chart.
    mfl = {row["player_id"] for row in result.trend_series if row["market_source_id"] == SOURCE}
    assert dropped in mfl

    gate = validate_artifact_directory(artifacts)
    assert gate.passed, [check.to_dict() for check in gate.critical_failures]


def test_a_market_with_no_retained_history_degrades_to_a_price(store, artifacts, tmp_path):
    """One source captured, the other not. The board publishes; the absence is recorded."""
    for offset in (4, 2, 0):
        _write_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(days=offset, hours=1)))
    result = _run(store, artifacts, tmp_path)

    assert {row["market_source_id"] for row in result.trend_series} == {SOURCE}
    assert result.trend_series_sources == (SOURCE,)
    assert any(check.check_id == "market.extra_source_absent" for check in result.gate.warnings)
    assert result.gate.passed, "a missing second market must never take the board down"
    trend_sources = result.metadata["market"]["trend_sources"]
    assert [entry["source_id"] for entry in trend_sources] == [SOURCE]


def test_a_stale_second_market_is_not_charted_and_says_so(store, artifacts, tmp_path):
    """A snapshot older than the freshness rule prices nothing, so it charts nothing."""
    _write_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(hours=1)))
    _write_ffc_snapshot(store, isoformat_utc(GENERATED_AT - timedelta(days=9)))
    result = _run(store, artifacts, tmp_path)

    assert FFC_SOURCE not in result.trend_series_sources
    assert any(check.check_id == "market.extra_source_stale" for check in result.gate.warnings)
    assert result.gate.passed


# --------------------------------------------------------------------------------------
# Degraded paths
# --------------------------------------------------------------------------------------


def test_a_missing_snapshot_fails_the_arbitrage_build_and_leaves_tiers_alone(
    store,
    artifacts,
    tmp_path,
):
    tiers_before = (artifacts / "tiers.json").read_bytes()
    result = _run(store, artifacts, tmp_path)

    assert not result.gate.passed
    assert any(
        check.check_id == "arbitrage.no_retained_snapshot"
        for check in result.gate.critical_failures
    )
    assert not (artifacts / "arbitrage.json").exists()
    assert (artifacts / "tiers.json").read_bytes() == tiers_before


def test_a_stale_snapshot_flags_every_row_and_caps_confidence(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-10T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    assert result.records
    for record in result.records:
        assert "market_snapshot_stale" in record["quality_flags"]
        assert record["confidence"] == "low"


def test_a_player_with_no_price_keeps_his_tier_row(store, artifacts, tmp_path):
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)
    priced = {record["player_id"] for record in result.records}
    assert "gsis:00-0000005" not in priced

    tiers = json.loads((artifacts / "tiers.json").read_text())["records"]
    assert any(record["player_id"] == "gsis:00-0000005" for record in tiers)
    assert any(item["player_id"] == "gsis:00-0000005" for item in result.unpriced_top_players)


# --------------------------------------------------------------------------------------
# Build metadata
# --------------------------------------------------------------------------------------


def test_the_market_identity_gate_refuses_an_unresolvable_cohort(store, artifacts, tmp_path):
    """A cohort this project cannot join is a cohort it cannot publish (DATA_CONTRACTS 12)."""
    stamped = parse_utc("2026-08-20T11:00:00Z")
    raw = gzip_bytes(canonical_json({"adp": {"player": []}}))
    rows = _market_rows("no-keeper")
    # Half the priced core-position rows lose their canonical id, as an unresolved market
    # row would. They stay in the snapshot as evidence; they just cannot become prices.
    for row in rows[: len(rows) // 2]:
        row["player_id"] = None
        row["resolution_reason"] = "no_bridge_resolved"
    manifest = SnapshotManifest(
        manifest_version="1.0",
        source_id=SOURCE,
        season=SEASON,
        snapshot_key=snapshot_key(stamped),
        retrieved_at_utc=isoformat_utc(stamped),
        adapter_version="2.0",
        source_policy_version="mfl-developer-rules/2026-08-17",
        cohorts=(
            CohortCapture(
                cohort_id="no-keeper",
                filters=dict(cohort_by_id("no-keeper").filters),
                label="non-keeper drafts",
                raw_path="cohorts/no-keeper/adp.raw.json.gz",
                raw_content_hash=content_hash(raw),
                row_count=len(rows),
                total_drafts=500,
            ),
        ),
    )
    store.write(
        manifest=manifest,
        normalized_rows=rows,
        raw_payloads={"cohorts/no-keeper/adp.raw.json.gz": raw},
    )

    result = _run(store, artifacts, tmp_path)
    assert not result.gate.passed
    assert any(
        check.check_id == "market.identity_coverage" for check in result.gate.critical_failures
    )
    assert not (artifacts / "arbitrage.json").exists()


def test_unresolved_market_rows_cannot_reach_a_published_row(store, artifacts, tmp_path):
    """Retained as evidence, excluded from output. Asserted rather than assumed."""
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    snapshot = store.read(SOURCE, SEASON, "2026-08-20T11-00-00Z")
    result = _run(store, artifacts, tmp_path)
    assert all(row.get("player_id") for row in snapshot.rows)
    assert all(record["player_id"] for record in result.records)


def test_the_arbitrage_build_merges_metadata_and_keeps_phase_4_warnings(
    store,
    artifacts,
    tmp_path,
):
    """A rewritten build_metadata.json would erase the tier-stability warning (ADR-035)."""
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    result = _run(store, artifacts, tmp_path)

    metadata = json.loads((artifacts / "build_metadata.json").read_text())
    assert any("tier stability gate" in warning for warning in metadata["warnings"])
    assert metadata["intrinsic_model_version"] == "intrinsic-cb-hurdle-v1"
    assert metadata["methodology_version"] == "phase4_intrinsic_v1"
    assert {source["source_id"] for source in metadata["sources"]} == {"nflreadpy", SOURCE}

    market = metadata["market"]
    assert market["source_id"] == SOURCE
    assert market["snapshot_key"] == result.snapshot_key
    assert market["source_as_of_utc"] is None
    assert market["cohort_rule_version"] == "phase5_cohort_v1"
    assert market["trend_available"] is False
    assert metadata["arbitrage_method_version"] == "a0_rank_gap_v1"
    assert metadata["arbitrage_model_version"] is None


def test_a_failed_sufficiency_clause_travels_into_build_metadata(store, artifacts, tmp_path):
    """ADR-047: the frontend must be able to say *why* a whole board reads `low`.

    Every row on the 2026 launch board carries `low` confidence for one shared reason. A UI
    that showed 2,122 identical unexplained pills would read as "the model is unsure about
    these players", which is the opposite of what `confidence` means (ADR-041). The reason it
    needs is the clause the frozen rule actually failed, in the rule's own words - so the
    build publishes it rather than leaving a consumer to hardcode today's measurement, which
    goes stale as draft season fills the cohort out.
    """
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    selection = _selection(tmp_path / "selection.json", sufficient=False)
    result = _run(store, artifacts, tmp_path, selection_path=selection)

    metadata = json.loads((artifacts / "build_metadata.json").read_text())
    assignments = metadata["market"]["assignments"]
    assert assignments, "the build recorded no cohort assignment"
    for assignment in assignments:
        assert assignment["sufficient"] is False
        # The observed value and the bound both travel; neither is rounded or reworded.
        assert assignment["failed_clauses"] == ["total_drafts 125 < 300"]

    # And the rows agree with the metadata that explains them.
    assert {record["confidence"] for record in result.records} == {"low"}
    for record in result.records:
        assert "cohort_insufficient" in record["quality_flags"]


def test_a_sufficient_cohort_publishes_an_empty_clause_list(store, artifacts, tmp_path):
    """The field is always present, so a consumer never has to distinguish absent from empty."""
    _write_snapshot(store, "2026-08-20T11:00:00Z")
    _run(store, artifacts, tmp_path)

    metadata = json.loads((artifacts / "build_metadata.json").read_text())
    for assignment in metadata["market"]["assignments"]:
        assert assignment["sufficient"] is True
        assert assignment["failed_clauses"] == []
