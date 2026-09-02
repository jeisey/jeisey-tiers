"""The three Phase-10 source adapters, against their measured contracts.

Every payload below is shaped from `docs/source-probes/2026-09-02/phase10-report.md` — the
field names, types and envelope structure are the runner's, and only the values are
synthetic. That split is the point: a fixture whose *shape* is invented would pass while
production broke, and a fixture carrying real vendor rows would be a small redistribution.

The schema-drift tests matter as much as the happy paths. A renamed upstream column that
silently becomes a column of nulls three stages later is the failure this project's adapter
boundary exists to convert into a loud one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ffdraft.contracts import AggregationWindow, EntityKind, MarketSignalType
from ffdraft.contracts.enums import BehaviorType
from ffdraft.sources.base import SourceFetchError
from ffdraft.sources.fantasypros import (
    FANTASYPROS_DAILY_REQUEST_CAP,
    FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS,
    RESPONSE_TRUNCATED,
    CallPlan,
    FantasyProsEcrAdapter,
    RequestBudget,
    fantasypros_cohort,
)
from ffdraft.sources.ffc import (
    LEAGUE_SIZE_NOT_OBSERVED,
    FfcAdpAdapter,
    classify_ffc_entity,
    ffc_cohort,
)
from ffdraft.sources.sleeper import TRENDING_LIMIT, TRENDING_LOOKBACK_HOURS, SleeperTrendingAdapter

SCHEMAS = Path(__file__).parents[1] / "fixtures" / "source_schemas"
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Fantasy Football Calculator
# --------------------------------------------------------------------------------------


def ffc_payload(**overrides) -> dict:
    """The measured FFC envelope, with synthetic rows."""
    payload = {
        "status": "Success",
        "meta": {
            "type": "half-ppr",
            "teams": 12,
            "rounds": 15,
            "total_drafts": 3142,
            "start_date": "2026-08-26",
            "end_date": "2026-09-02",
        },
        "players": [
            {
                "player_id": 4001,
                "name": "Tobias Vandermeer",
                "position": "QB",
                "team": "BUF",
                "adp": 33.4,
                "adp_formatted": "3.09",
                "times_drafted": 412,
                "high": 21,
                "low": 58,
                "stdev": 6.7,
                "bye": 7,
            },
            {
                "player_id": 4002,
                "name": "Marcus Delacroix",
                "position": "RB",
                "team": "ARI",
                "adp": 12.1,
                "adp_formatted": "1.12",
                "times_drafted": 3100,
                "high": 4,
                "low": 26,
                "stdev": 3.2,
                "bye": 11,
            },
            {
                "player_id": 4003,
                "name": "Arizona Cardinals",
                "position": "DEF",
                "team": "ARI",
                "adp": 180.5,
                "adp_formatted": "15.01",
                "times_drafted": 90,
                "high": 150,
                "low": 210,
                "stdev": 14.0,
                "bye": 11,
            },
        ],
    }
    payload.update(overrides)
    return payload


def ffc_batch(payload=None, fmt: str = "half-ppr"):
    return FfcAdpAdapter().normalize(
        payload if payload is not None else ffc_payload(),
        season=2026,
        cohort=ffc_cohort(fmt),
        retrieved_at=NOW,
    )


def test_ffc_normalizes_the_measured_schema() -> None:
    frame = ffc_batch().frame
    assert frame.height == 3
    row = frame.filter(frame["external_player_id"] == "4001").to_dicts()[0]
    assert row["average_pick"] == 33.4
    assert row["adp_sd"] == 6.7
    assert row["sample_size"] == 412
    assert row["market_signal_type"] == str(MarketSignalType.ADP)
    assert row["source_display_name"] == "Tobias Vandermeer"


def test_ffc_never_claims_a_league_size() -> None:
    """`teams` is accepted and ignored, so a claim would be unsupported (ADR-056)."""
    batch = ffc_batch()
    assert batch.frame.get_column("league_size").null_count() == batch.frame.height
    flags = batch.frame.get_column("quality_flags").to_list()
    assert all(LEAGUE_SIZE_NOT_OBSERVED in flag for flag in flags)
    assert not [
        check
        for check in FfcAdpAdapter().semantic_checks(batch)
        if check.check_id == "market.ffc_claims_league_size"
    ]


def test_ffc_records_the_rolling_window_it_measured() -> None:
    """MFL is cumulative; conflating the two would invite an average of unlike things."""
    batch = ffc_batch()
    row = batch.frame.to_dicts()[0]
    assert row["aggregation_window_type"] == str(AggregationWindow.ROLLING)
    assert row["aggregation_window_days"] == 7
    assert batch.metadata.detail["window_start_date"] == "2026-08-26"
    assert batch.metadata.detail["total_drafts"] == "3142"


def test_ffc_falls_back_to_an_unknown_window_rather_than_inventing_one() -> None:
    payload = ffc_payload()
    payload["meta"] = {"total_drafts": 100}
    row = ffc_batch(payload).frame.to_dicts()[0]
    assert row["aggregation_window_type"] == str(AggregationWindow.UNKNOWN)
    assert row["aggregation_window_days"] is None


def test_ffc_orders_high_and_low_numerically_rather_than_by_label() -> None:
    """FFC's "high" is the earliest pick, i.e. the smaller number.

    Ordering the pair is correct under either convention, so a vendor that swapped the
    labels could not silently invert a published range.
    """
    first = next(r for r in ffc_batch().frame.to_dicts() if r["external_player_id"] == "4001")
    assert (first["min_pick"], first["max_pick"]) == (21.0, 58.0)

    swapped = ffc_payload()
    swapped["players"][0]["high"], swapped["players"][0]["low"] = 58, 21
    other = next(
        r for r in ffc_batch(swapped).frame.to_dicts() if r["external_player_id"] == "4001"
    )
    assert (other["min_pick"], other["max_pick"]) == (21.0, 58.0)


def test_ffc_counts_the_high_low_orientation_as_evidence() -> None:
    detail = ffc_batch().metadata.detail
    assert detail["high_low_comparable_rows"] == "3"
    assert detail["high_le_low_rows"] == "3", "measured: high is the earlier, smaller pick"


def test_ffc_publishes_no_data_as_of_instant() -> None:
    """A window of dates is not an instant; promoting it would manufacture precision."""
    batch = ffc_batch()
    assert batch.frame.get_column("source_as_of_utc").null_count() == batch.frame.height
    assert batch.metadata.source_as_of_utc is None


def test_ffc_classifies_a_team_defence_as_a_team_unit() -> None:
    row = next(r for r in ffc_batch().frame.to_dicts() if r["external_player_id"] == "4003")
    assert row["entity_kind"] == str(EntityKind.TEAM_UNIT)
    assert ffc_batch().metadata.detail["team_unit_rows"] == "1"


@pytest.mark.parametrize(
    ("token", "kind"),
    [
        ("QB", EntityKind.PLAYER),
        ("PK", EntityKind.PLAYER),
        ("DEF", EntityKind.TEAM_UNIT),
        ("DST", EntityKind.TEAM_UNIT),
        ("TMWR", EntityKind.UNKNOWN),
        ("", EntityKind.UNKNOWN),
        (None, EntityKind.UNKNOWN),
    ],
)
def test_ffc_entity_classification_is_exact(token, kind) -> None:
    assert classify_ffc_entity(token) is kind


def test_ffc_drops_a_row_with_no_usable_price_and_counts_it() -> None:
    payload = ffc_payload()
    payload["players"].append({"player_id": 4004, "name": "X", "position": "WR", "adp": 0})
    batch = ffc_batch(payload)
    assert batch.frame.height == 3
    assert batch.metadata.detail["rows_without_usable_price"] == "1"


def test_ffc_schema_drift_is_caught_at_the_boundary() -> None:
    """A renamed upstream column must fail loudly, not become a column of nulls."""
    payload = ffc_payload()
    for row in payload["players"]:
        row["standard_deviation"] = row.pop("stdev")
    checks = FfcAdpAdapter().check_source_schema(payload["players"])
    failures = [check for check in checks if check.status == "fail"]
    assert failures, "a missing required column produced no failure"
    assert any("stdev" in (check.observed or "") + (check.expected or "") for check in failures)


def test_ffc_cohorts_are_scoring_only() -> None:
    for fmt, scoring in (("standard", "STD"), ("half-ppr", "HALF"), ("ppr", "PPR")):
        cohort = ffc_cohort(fmt)
        assert cohort.scoring_semantics == scoring
        assert cohort.league_size_semantics is None
        assert cohort.is_exact_for(scoring, 12) is False, "an unconstrained axis is never exact"


def test_an_unknown_ffc_format_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown FFC format"):
        ffc_cohort("super-flex")


def test_ffc_accepts_a_bare_row_list_as_well_as_the_envelope() -> None:
    rows = ffc_payload()["players"]
    assert ffc_batch(rows).frame.height == 3


# --------------------------------------------------------------------------------------
# FantasyPros
# --------------------------------------------------------------------------------------


def fp_payload(*, limited: bool = True, rows: int = 10) -> dict:
    return {
        "sport": "NFL",
        "type": "Draft Half PPR",
        "ranking_type_name": "draft",
        "year": "2026",
        "week": "0",
        "position_id": "RB",
        "scoring": "HALF",
        "count": 407,
        "total_experts": 104,
        "last_updated": "9/02",
        "limit": 10,
        "public_api_limited": limited,
        "tier": "free",
        "players": [
            {
                "player_id": 20000 + index,
                "player_name": f"Synthetic Back {index}",
                "player_position_id": "RB",
                "player_team_id": "BUF",
                "player_yahoo_id": 30000 + index,
                "sportsdata_id": f"aaaaaaaa-0000-0000-0000-{index:012d}",
                "cbs_player_id": 40000 + index,
                "rank_ecr": index + 1,
                "rank_ave": index + 1.4,
                "rank_min": index + 1,
                "rank_max": index + 5,
                "rank_std": 1.3,
                "pos_rank": f"RB{index + 1}",
                "tier": 1,
            }
            for index in range(rows)
        ],
    }


def fp_batch(payload=None):
    return FantasyProsEcrAdapter().normalize(
        payload if payload is not None else fp_payload(),
        season=2026,
        cohort=fantasypros_cohort("HALF"),
        retrieved_at=NOW,
    )


def test_fantasypros_emits_expert_consensus_and_never_a_price() -> None:
    """Measured: no endpoint this key can reach carries an ADP field (ADR-064)."""
    frame = fp_batch().frame
    assert frame.get_column("market_signal_type").unique().to_list() == [str(MarketSignalType.ECR)]
    assert frame.get_column("average_pick").null_count() == frame.height
    assert frame.get_column("adp_sd").null_count() == frame.height
    assert frame.get_column("min_pick").null_count() == frame.height


def test_fantasypros_puts_expert_dispersion_in_rank_columns_not_pick_columns() -> None:
    row = fp_batch().frame.to_dicts()[0]
    assert row["market_rank"] == 1
    assert row["consensus_rank_mean"] == 1.4
    assert row["consensus_rank_min"] == 1
    assert row["consensus_rank_max"] == 5
    assert row["consensus_rank_sd"] == 1.3


def test_the_expert_panel_is_the_sample_size() -> None:
    assert fp_batch().frame.to_dicts()[0]["sample_size"] == 104


def test_a_ranking_has_no_aggregation_window() -> None:
    row = fp_batch().frame.to_dicts()[0]
    assert row["aggregation_window_type"] == str(AggregationWindow.NOT_APPLICABLE)
    assert row["aggregation_window_days"] is None


def test_a_truncated_response_fails_closed() -> None:
    """The measurement that decides the whole disposition, asserted rather than trusted."""
    batch = fp_batch()
    checks = FantasyProsEcrAdapter().semantic_checks(batch)
    truncation = next(c for c in checks if c.check_id == "market.fantasypros_truncated")
    assert truncation.status == "fail"
    assert truncation.severity == "critical"
    assert RESPONSE_TRUNCATED in batch.metadata.warning_codes
    assert batch.metadata.detail["public_api_limited"] == "True"
    assert batch.metadata.detail["envelope_count"] == "407"


def test_a_complete_response_would_pass() -> None:
    """The guard is about truncation, not about FantasyPros. A full response is fine."""
    payload = fp_payload(limited=False, rows=407)
    payload["count"] = 407
    batch = fp_batch(payload)
    checks = FantasyProsEcrAdapter().semantic_checks(batch)
    assert not [c for c in checks if c.check_id == "market.fantasypros_truncated"]


def test_count_exceeding_the_delivered_rows_is_also_truncation() -> None:
    """Two independent signals, because a future tier might drop the explicit flag."""
    payload = fp_payload(limited=False, rows=10)
    payload.pop("public_api_limited")
    batch = fp_batch(payload)
    checks = FantasyProsEcrAdapter().semantic_checks(batch)
    assert any(c.check_id == "market.fantasypros_truncated" for c in checks)


def test_a_partial_date_never_becomes_a_timestamp() -> None:
    """`last_updated` is "9/02": a month and a day, with no year and no time."""
    batch = fp_batch()
    assert batch.frame.get_column("source_as_of_utc").null_count() == batch.frame.height
    assert batch.metadata.detail["last_updated"] == "9/02"
    assert all("source_as_of_date_partial" in f for f in batch.frame["quality_flags"].to_list())


def test_the_request_budget_refuses_to_exceed_the_internal_cap() -> None:
    budget = RequestBudget(limit=3, min_interval_seconds=0.0)
    for _ in range(3):
        budget.spend()
    assert budget.remaining == 0
    with pytest.raises(SourceFetchError, match="daily request cap"):
        budget.spend()


def test_the_default_budget_is_half_the_vendors_allowance() -> None:
    """Roadmap 10.1.3 halves the stated 100/day for operational headroom."""
    assert FANTASYPROS_DAILY_REQUEST_CAP == 50
    assert FANTASYPROS_MIN_REQUEST_INTERVAL_SECONDS == 1.0
    assert RequestBudget().limit == FANTASYPROS_DAILY_REQUEST_CAP


def test_the_call_plan_is_the_smallest_that_covers_the_core_positions() -> None:
    plan = CallPlan(cohort=fantasypros_cohort("HALF"))
    assert plan.positions == ("QB", "RB", "WR", "TE")
    assert plan.request_count == 4
    assert plan.request_count * 3 <= FANTASYPROS_DAILY_REQUEST_CAP, "three cohorts must fit"


def test_the_call_plan_sends_the_parameters_the_endpoint_requires() -> None:
    """Measured: `position=ALL` 400s unless `type=draft&week=0` accompany it."""
    params = CallPlan(cohort=fantasypros_cohort("HALF")).params("RB")
    assert params == {"position": "RB", "scoring": "HALF", "type": "draft", "week": "0"}


def test_fetch_without_a_key_fails_honestly_rather_than_measuring_a_different_surface() -> None:
    from ffdraft.sources.base import SourceConfig

    config = SourceConfig(season=2026, options={"cohort": fantasypros_cohort("HALF")})
    with pytest.raises(SourceFetchError, match="no API key"):
        FantasyProsEcrAdapter().fetch(as_of=NOW, config=config)


def test_fantasypros_schema_drift_is_caught_at_the_boundary() -> None:
    payload = fp_payload()
    for row in payload["players"]:
        row["ecr_rank"] = row.pop("rank_ecr")
    checks = FantasyProsEcrAdapter().check_source_schema(payload["players"])
    assert [check for check in checks if check.status == "fail"]


# --------------------------------------------------------------------------------------
# Sleeper trending
# --------------------------------------------------------------------------------------


def trending_batch(rows=None, *, behavior=BehaviorType.ADD, lookback=24, limit=100):
    payload = (
        rows
        if rows is not None
        else [
            {"player_id": "4034", "count": 259065},
            {"player_id": "6786", "count": 17793},
        ]
    )
    return SleeperTrendingAdapter().normalize(
        payload,
        behavior_type=behavior,
        lookback_hours=lookback,
        limit=limit,
        retrieved_at=NOW,
    )


def test_sleeper_trending_normalizes_the_bare_list_the_api_returns() -> None:
    frame = trending_batch().frame
    assert frame.height == 2
    row = frame.to_dicts()[0]
    assert row["count"] == 259065
    assert row["behavior_type"] == str(BehaviorType.ADD)


def test_the_snapshot_records_the_request_because_the_response_records_nothing() -> None:
    """Measured: the rows carry no timestamp and no window, only a count."""
    batch = trending_batch(lookback=6, limit=25)
    row = batch.frame.to_dicts()[0]
    assert row["lookback_hours"] == 6
    assert row["request_limit"] == 25
    assert row["snapshot_at_utc"] == NOW
    assert batch.metadata.detail["lookback_hours"] == "6"


def test_add_and_drop_are_separate_behaviours() -> None:
    add = trending_batch(behavior=BehaviorType.ADD).frame.to_dicts()[0]
    drop = trending_batch(behavior=BehaviorType.DROP).frame.to_dicts()[0]
    assert add["behavior_type"] != drop["behavior_type"]


def test_the_defaults_match_the_measured_request() -> None:
    assert TRENDING_LOOKBACK_HOURS == 24
    assert TRENDING_LIMIT == 100


def test_a_row_without_a_count_or_an_id_is_dropped_and_counted() -> None:
    batch = trending_batch([{"player_id": "4034"}, {"count": 5}, {"player_id": "1", "count": 2}])
    assert batch.frame.height == 1
    assert batch.metadata.detail["sleeper_trending_rows_without_id_or_count"] == "2"


def test_behaviour_snapshots_state_that_they_are_not_a_price() -> None:
    checks = SleeperTrendingAdapter().semantic_checks(trending_batch())
    assert any(
        c.check_id == "sleeper.behavior_is_not_a_price" and c.status == "pass" for c in checks
    )


# --------------------------------------------------------------------------------------
# The recorded schemas themselves
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "ffc_adp_half_ppr",
        "fantasypros_consensus_rankings_half",
        "sleeper_trending_add",
    ],
)
def test_each_new_adapter_has_a_recorded_schema_carrying_its_evidence(name: str) -> None:
    """A schema fixture with no provenance is a guess someone wrote down."""
    payload = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    assert payload["recorded_at"] == "2026-09-02"
    assert "phase10-report" in payload["evidence"]
    assert payload["measured_facts"]
