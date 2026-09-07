"""The generalized retained-history path (ADR-081).

Phase 5 built one source a trailing window and a trend; Phase 10 added a second source and
gave it neither. The module under test is the extraction that ended that asymmetry, so the
cases here are the ones that decide whether a *second* source is a first-class market or a
special case:

* its cohort vocabulary is its own, and is read from its own rows rather than assumed;
* its window is anchored on its own newest capture, not on another source's clock;
* its slope comes from the same frozen `phase5_trend_v1` function, unweakened;
* a cohort it cannot resolve is refused rather than guessed at.

Nothing here re-implements the trend. If a test in this file could pass while
:mod:`ffdraft.market.trend` changed meaning, it would be testing the wrong thing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ffdraft.market.history import (
    build_retained_history,
    cohorts_by_scoring_preset,
    expand_cohorts_over_league_sizes,
)
from ffdraft.market.snapshot import MarketSnapshot, SnapshotManifest

NOW = datetime(2026, 9, 6, 11, 22, 48, tzinfo=UTC)
FFC = "fantasyfootballcalculator_adp"


def _manifest(moment: datetime, *, source_id: str = FFC) -> SnapshotManifest:
    return SnapshotManifest(
        manifest_version="1.0",
        source_id=source_id,
        season=2026,
        snapshot_key=moment.strftime("%Y-%m-%dT%H-%M-%SZ"),
        retrieved_at_utc=moment.isoformat().replace("+00:00", "Z"),
        adapter_version="1.0",
        source_policy_version="1.0",
    )


def _row(
    player_id: str,
    adp: float,
    *,
    cohort_id: str = "ffc-ppr",
    scoring: str = "PPR",
) -> dict[str, Any]:
    return {
        "source_id": FFC,
        "season": 2026,
        "cohort_id": cohort_id,
        "scoring_preset": scoring,
        "player_id": player_id,
        "average_pick": adp,
        "entity_kind": "player",
    }


def _snapshot(moment: datetime, rows: list[dict[str, Any]]) -> MarketSnapshot:
    return MarketSnapshot(manifest=_manifest(moment), rows=tuple(rows))


def _window(offsets_hours: tuple[float, ...], *, start_adp: float = 24.0) -> list[MarketSnapshot]:
    """A capture cadence measured back from ``NOW``, one player, drifting earlier."""
    return [
        _snapshot(
            NOW - timedelta(hours=offset),
            [_row("gsis:001", round(start_adp + offset * 0.05, 2))],
        )
        for offset in sorted(offsets_hours, reverse=True)
    ]


# --------------------------------------------------------------------------------------
# Cohorts are the source's own, and are read rather than assumed
# --------------------------------------------------------------------------------------


def test_a_sources_cohorts_are_derived_from_its_own_retained_rows() -> None:
    snapshot = _snapshot(
        NOW,
        [
            _row("gsis:001", 24.0, cohort_id="ffc-ppr", scoring="PPR"),
            _row("gsis:002", 25.0, cohort_id="ffc-half-ppr", scoring="HALF"),
            _row("gsis:003", 26.0, cohort_id="ffc-standard", scoring="STD"),
        ],
    )
    resolved, ambiguous = cohorts_by_scoring_preset(snapshot)

    assert resolved == {"PPR": "ffc-ppr", "HALF": "ffc-half-ppr", "STD": "ffc-standard"}
    assert ambiguous == {}


def test_a_scoring_preset_served_by_two_cohorts_is_reported_not_resolved() -> None:
    """Choosing between them would mix populations, which is the one thing the rule forbids."""
    snapshot = _snapshot(
        NOW,
        [
            _row("gsis:001", 24.0, cohort_id="ppr", scoring="PPR"),
            _row("gsis:002", 25.0, cohort_id="ppr-no-keeper", scoring="PPR"),
        ],
    )
    resolved, ambiguous = cohorts_by_scoring_preset(snapshot)

    assert resolved == {}
    assert ambiguous == {"PPR": ["ppr", "ppr-no-keeper"]}


def test_a_source_that_does_not_observe_league_size_repeats_one_cohort_across_sizes() -> None:
    """FFC accepts ``teams`` and ignores it (ADR-056), so every size gets the same cohort.

    The key exists because the caller asks per preset; the value does not vary because the
    source cannot see the difference. That repetition is the claim, not a shortcut.
    """
    expanded = expand_cohorts_over_league_sizes({"PPR": "ffc-ppr"}, [10, 12, 14])

    assert expanded == {
        ("PPR", 10): "ffc-ppr",
        ("PPR", 12): "ffc-ppr",
        ("PPR", 14): "ffc-ppr",
    }


# --------------------------------------------------------------------------------------
# The frozen rule, asked once per source
# --------------------------------------------------------------------------------------


def test_the_window_is_anchored_on_the_sources_own_newest_capture() -> None:
    """Two sources are captured by two jobs, hours apart. Neither anchors the other."""
    history = build_retained_history(
        _window((48.0, 24.0, 0.0)),
        source_id=FFC,
        cohorts={("PPR", 12): "ffc-ppr"},
    )

    assert history.anchored_at == NOW
    assert len(history.snapshots) == 3


def test_a_real_history_whose_span_is_short_charts_without_a_slope() -> None:
    """The production state on the day the bug was found, and the whole point of ADR-081.

    Four observation days — which the rule accepts — over 62 hours of span, which it does
    not. Five points to draw and no number to print. Conflating those two questions is what
    made a market with seven real snapshots read "0 snapshots so far".
    """
    history = build_retained_history(
        _window((62.0, 55.0, 38.0, 19.0, 0.0)),
        source_id=FFC,
        cohorts={("PPR", 12): "ffc-ppr"},
    )

    result = history.trend_for("ffc-ppr", "gsis:001")
    assert result is not None
    assert result.observation_days == 4
    assert result.span_days < 3.0
    assert result.trend is None, "the frozen rule must not be softened to make a chart appear"
    assert history.trend_available is False

    assert len(history.observations_for("ffc-ppr")) == 5, (
        "every retained observation is available to draw, unfiltered by the slope's gate"
    )


def test_enough_span_produces_the_same_slope_the_frozen_rule_would() -> None:
    from ffdraft.market.trend import TREND_RULE, compute_trends

    snapshots = _window((96.0, 72.0, 48.0, 24.0, 0.0))
    history = build_retained_history(
        snapshots,
        source_id=FFC,
        cohorts={("PPR", 12): "ffc-ppr"},
    )
    direct = compute_trends(
        history.observations_for("ffc-ppr"),
        now=NOW,
        cohort_id="ffc-ppr",
        rule=TREND_RULE,
    )

    assert history.trends_for("ffc-ppr") == direct
    assert history.trend_available is True
    # Every ADP fell over the window, so the player is being taken earlier.
    result = history.trend_for("ffc-ppr", "gsis:001")
    assert result is not None
    assert result.trend is not None
    assert result.trend > 0


def test_cohorts_are_never_mixed_across_sources_or_within_one() -> None:
    snapshots = [
        _snapshot(
            NOW - timedelta(days=offset),
            [
                _row("gsis:001", 24.0 + offset, cohort_id="ffc-ppr", scoring="PPR"),
                _row("gsis:001", 90.0 - offset, cohort_id="ffc-standard", scoring="STD"),
            ],
        )
        for offset in (4, 2, 0)
    ]
    history = build_retained_history(
        snapshots,
        source_id=FFC,
        cohorts={("PPR", 12): "ffc-ppr", ("STD", 12): "ffc-standard"},
    )

    ppr = history.trend_for("ffc-ppr", "gsis:001")
    std = history.trend_for("ffc-standard", "gsis:001")
    assert ppr is not None and std is not None
    # The two cohorts moved in opposite directions; a mixed fit would produce neither.
    assert ppr.trend is not None and std.trend is not None
    assert ppr.trend > 0 > std.trend


def test_an_empty_window_is_an_empty_history_rather_than_an_error() -> None:
    history = build_retained_history([], source_id=FFC, cohorts={("PPR", 12): "ffc-ppr"})

    assert history.is_empty
    assert history.snapshot_keys == ()
    assert history.trend_available is False
    assert history.observations_for("ffc-ppr") == []
    assert history.cohort_for("PPR", 12) == "ffc-ppr"
