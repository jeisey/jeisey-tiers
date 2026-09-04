"""The in-season Opportunity Board: intrinsic value beside behaviour, never mixed with it.

Roadmap 12.3 replaces the draft comparison after drafts are done. What replaces it is *not*
another price: nobody is drafting in November, so the external evidence available is what
managers are actually doing — Sleeper's documented add and drop counts over a declared
lookback window.

**The one rule that shapes every line below.**

    Behaviour may decide whether a player is **surfaced**. It may never change his
    projection, his remaining VORP, his fair rank, or his tier.

That is enforced structurally rather than promised. Every intrinsic column on an opportunity
row is **copied from the published `ros_tiers` record for the same player**, and where a
surfaced player has no published record it is copied from the same fair-ranked board the
tier artifact was cut from. There is no code path in this module that computes an intrinsic
value, so there is none that could modify one; a test asserts field-by-field equality between
the two artifacts.

**Two things this module refuses to do**, both because they would be wrong rather than
because they would be hard:

*It never calls an add count an ADP.* An add count is a number of transactions inside a
window. A draft pick number is a position in an ordering. They share no unit, no
denominator and no interpretation.

*It never subtracts a rank from a count.* `ros_fair_rank - add_rank` is arithmetic on two
orderings of different populations by different criteria, and the result would look like an
edge and mean nothing (roadmap 10.3, 12.3). Adds and drops *are* differenced into
``net_add_count``, and that is legitimate for the narrow reason that both sides are the same
unit, measured over the same window, by the same feed, at the same moment.

**Degradation.** The behaviour feed is optional and the board says so per row
(``behavior_available``). A capture that is missing, unreadable or stale leaves every
intrinsic column exactly as the rest-of-season build produced it and empties the behaviour
columns — the Opportunity Board loses a column, the ROS board loses nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ffdraft.behavior.capture import BehaviorCapture
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import BehaviorType, Severity, SurfaceReason
from ffdraft.identity.registry import CanonicalRegistry
from ffdraft.market.surface import (
    SURFACE_RULE_VERSION,
    TIER_DEPTH_RULE,
    SurfaceMembership,
    SurfaceUniverse,
    build_surface_universe,
)
from ffdraft.quality import QualityGate

__all__ = [
    "BEHAVIOR_MAX_AGE_HOURS",
    "OPPORTUNITY_METHOD_VERSION",
    "SURFACE_ADD_COUNT_MINIMUM",
    "BehaviorSignals",
    "build_opportunity_records",
    "resolve_behavior_signals",
]

#: Bump when the meaning of an opportunity row changes.
OPPORTUNITY_METHOD_VERSION = "phase12_opportunity_v1"

#: How stale a retained behaviour snapshot may be before the board stops presenting it as
#: current. Two days rather than one: the in-season capture cadence is daily, so a single
#: missed refresh should degrade the *label* rather than blank the column, and a second
#: missed one should blank it.
BEHAVIOR_MAX_AGE_HOURS = 48.0

#: How many adds inside the window make a player relevant enough to surface from beyond the
#: intrinsic tier depth. A threshold, and therefore a judgement: it is the smallest value
#: that is unambiguously a signal rather than noise in a top-100 feed whose smallest counts
#: are single digits. It decides **visibility only**, so being wrong about it costs a row on
#: a board, never a number on one.
SURFACE_ADD_COUNT_MINIMUM = 500

#: The role signal that surfaces a player the feed has not noticed yet: a share of his
#: team's offensive snaps over the last three weeks that a starter has and a reserve does
#: not. Visibility only, exactly as above.
SURFACE_SNAP_SHARE_MINIMUM = 0.55


@dataclass
class BehaviorSignals:
    """One resolved behaviour snapshot, keyed by canonical player id.

    ``available`` is the single question the board asks. Everything else is provenance the
    row carries so a reader can tell a zero from an absence: a player with no add row inside
    a top-N feed has ``add_count`` 0, and a build with no feed at all has ``None``.
    """

    available: bool
    source_id: str | None = None
    snapshot_at_utc: datetime | None = None
    lookback_hours: int | None = None
    request_limit: int | None = None
    age_hours: float | None = None
    degraded_reason: str | None = None
    add_counts: Mapping[str, int] = field(default_factory=dict)
    drop_counts: Mapping[str, int] = field(default_factory=dict)
    add_ranks: Mapping[str, int] = field(default_factory=dict)
    drop_ranks: Mapping[str, int] = field(default_factory=dict)
    matched_players: int = 0
    unresolved_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "available": self.available,
            "snapshot_at_utc": (
                self.snapshot_at_utc.isoformat().replace("+00:00", "Z")
                if self.snapshot_at_utc
                else None
            ),
            "lookback_hours": self.lookback_hours,
            "request_limit": self.request_limit,
            "add_rows": len(self.add_counts),
            "drop_rows": len(self.drop_counts),
            "matched_players": self.matched_players,
            "age_hours": None if self.age_hours is None else round(self.age_hours, 2),
            "degraded_reason": self.degraded_reason,
            "signal_semantics": (
                "add and drop COUNTS over the requested lookback window, from the feed's "
                "own snapshot. Transactions, not a price: never an ADP, never a draft rank, "
                "and never differenced against a fair rank."
            ),
        }

    def checks(self, *, stage: str = "opportunity") -> list[QualityCheck]:
        if self.available:
            return [
                QualityCheck.ok(
                    "opportunity.behavior_available",
                    stage=stage,
                    message=(
                        f"behaviour signals from {self.source_id} over a "
                        f"{self.lookback_hours}h requested window; counts are transactions "
                        "and are never converted into a price or a rank gap"
                    ),
                    observed=(
                        f"{len(self.add_counts)} add row(s), {len(self.drop_counts)} drop "
                        f"row(s), {self.matched_players} matched to canonical players"
                    ),
                ),
            ]
        return [
            QualityCheck.fail(
                "opportunity.behavior_unavailable",
                stage=stage,
                message=(
                    "the optional behaviour feed is unavailable, so the Opportunity Board "
                    "publishes intrinsic rest-of-season value with empty behaviour columns; "
                    "no rest-of-season number is affected"
                ),
                observed=self.degraded_reason or "no capture",
                expected="a retained add/drop snapshot inside the freshness window",
                severity=Severity.WARNING,
            ),
        ]


def resolve_behavior_signals(
    capture: BehaviorCapture | None,
    *,
    registry: CanonicalRegistry | None,
    as_of: datetime,
    max_age_hours: float = BEHAVIOR_MAX_AGE_HOURS,
) -> BehaviorSignals:
    """Map a retained snapshot onto canonical player ids, or explain why it cannot be.

    The join direction is nflverse-first, exactly as ADR-011 requires and exactly as the
    status artifact does it: iteration runs over canonical players that carry a
    ``sleeper_id``, never over the Sleeper feed. A feed row that reaches no canonical player
    is counted and dropped rather than guessed at.
    """
    if capture is None:
        return BehaviorSignals(available=False, degraded_reason="no retained behaviour capture")
    age = capture.age_hours(as_of)
    if age > max_age_hours:
        return BehaviorSignals(
            available=False,
            source_id=capture.source_id,
            snapshot_at_utc=capture.observed_at_utc,
            lookback_hours=capture.lookback_hours,
            request_limit=capture.request_limit,
            age_hours=age,
            degraded_reason=(
                f"the latest retained snapshot is {age:.1f}h old, beyond the "
                f"{max_age_hours:.0f}h freshness window"
            ),
        )
    if registry is None:
        return BehaviorSignals(
            available=False,
            source_id=capture.source_id,
            snapshot_at_utc=capture.observed_at_utc,
            age_hours=age,
            degraded_reason="no canonical registry, so no feed row can be resolved",
        )

    sleeper_to_canonical: dict[str, str] = {}
    for player_id in sorted(registry.players):
        sleeper_id = registry.players[player_id].crosswalk.sleeper_id
        if sleeper_id:
            sleeper_to_canonical[str(sleeper_id)] = player_id

    def project(source: Mapping[str, int]) -> tuple[dict[str, int], int]:
        mapped: dict[str, int] = {}
        unresolved = 0
        for external, count in source.items():
            canonical = sleeper_to_canonical.get(external)
            if canonical is None:
                unresolved += 1
                continue
            mapped[canonical] = count
        return mapped, unresolved

    add_counts, add_unresolved = project(capture.counts(BehaviorType.ADD))
    drop_counts, drop_unresolved = project(capture.counts(BehaviorType.DROP))
    add_ranks, _ = project(capture.ranks(BehaviorType.ADD))
    drop_ranks, _ = project(capture.ranks(BehaviorType.DROP))

    return BehaviorSignals(
        available=True,
        source_id=capture.source_id,
        snapshot_at_utc=capture.observed_at_utc,
        lookback_hours=capture.lookback_hours,
        request_limit=capture.request_limit,
        age_hours=age,
        add_counts=add_counts,
        drop_counts=drop_counts,
        add_ranks=add_ranks,
        drop_ranks=drop_ranks,
        matched_players=len(set(add_counts) | set(drop_counts)),
        unresolved_rows=add_unresolved + drop_unresolved,
    )


def build_opportunity_records(
    *,
    ros_records: Sequence[Mapping[str, Any]],
    full_board: Sequence[Mapping[str, Any]],
    context: Mapping[str, Mapping[str, Any]],
    signals: BehaviorSignals,
    build_id: str,
    season: int,
    through_week: int,
    gate: QualityGate,
    tier_depth: int | None = None,
) -> tuple[list[dict[str, Any]], list[SurfaceUniverse], dict[str, Any]]:
    """Assemble the Opportunity Board for every published block.

    ``ros_records`` are the published rest-of-season tier records; every intrinsic column
    below is copied from them. ``full_board`` is the untruncated fair-ranked board, which is
    what makes a rescue possible: a player cut at the publication depth is still in it, with
    the fair rank the model gave him.
    """
    depth = tier_depth if tier_depth is not None else TIER_DEPTH_RULE.depth
    published: dict[tuple[str, str, str], Mapping[str, Any]] = {
        (
            str(record["league_preset_id"]),
            str(record["scoring_preset"]),
            str(record["player_id"]),
        ): record
        for record in ros_records
    }
    blocks: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for row in full_board:
        key = (str(row["league_preset_id"]), str(row["scoring_preset"]))
        blocks.setdefault(key, []).append(row)

    records: list[dict[str, Any]] = []
    universes: list[SurfaceUniverse] = []
    surfaced_total = 0

    for (league_preset_id, scoring_preset), board in sorted(blocks.items()):
        memberships = _memberships(
            board=board,
            scoring_preset=scoring_preset,
            signals=signals,
            context=context,
        )
        universe = build_surface_universe(
            board,
            scoring_preset=scoring_preset,
            league_preset_id=league_preset_id,
            memberships=memberships,
            tier_depth=depth,
            board_is_complete=True,
        )
        universes.append(universe)
        by_player = {str(row["player_id"]): row for row in board}

        for player_id, entry in sorted(
            universe.entries.items(),
            key=lambda item: item[1].fair_rank,
        ):
            board_row = by_player.get(player_id)
            if board_row is None:
                continue
            record = published.get((league_preset_id, scoring_preset, player_id))
            player_context = context.get(player_id, {})
            if entry.outside_tier_board:
                surfaced_total += 1
            records.append(
                _opportunity_record(
                    player_id=player_id,
                    board_row=board_row,
                    published=record,
                    player_context=player_context,
                    signals=signals,
                    entry_reasons=[str(reason) for reason in entry.reasons],
                    outside_tier_board=entry.outside_tier_board,
                    build_id=build_id,
                    season=season,
                    through_week=through_week,
                    league_preset_id=league_preset_id,
                    scoring_preset=scoring_preset,
                ),
            )

    gate.extend(signals.checks())
    gate.add(
        QualityCheck.ok(
            "opportunity.surface",
            stage="opportunity",
            message=(
                "current role and behaviour evidence decided visibility only; every "
                "intrinsic column is copied from the published rest-of-season board"
            ),
            observed=(
                f"{len(records)} row(s) across {len(universes)} block(s); "
                f"{surfaced_total} surfaced from beyond tier depth {depth}"
            ),
        ),
    )
    diagnostics = {
        "method_version": OPPORTUNITY_METHOD_VERSION,
        "surface_rule_version": SURFACE_RULE_VERSION,
        "tier_depth": depth,
        "rows": len(records),
        "surfaced_beyond_depth": surfaced_total,
        "behavior": signals.to_dict(),
        "surface_add_count_minimum": SURFACE_ADD_COUNT_MINIMUM,
        "surface_snap_share_minimum": SURFACE_SNAP_SHARE_MINIMUM,
        "blocks": [universe.to_dict() for universe in universes],
    }
    return records, universes, diagnostics


def _memberships(
    *,
    board: Sequence[Mapping[str, Any]],
    scoring_preset: str,
    signals: BehaviorSignals,
    context: Mapping[str, Mapping[str, Any]],
) -> list[SurfaceMembership]:
    """The in-season populations that justify visibility beyond the intrinsic depth."""
    on_board = {str(row["player_id"]) for row in board}
    memberships: list[SurfaceMembership] = []

    if signals.available:
        trending_adds = frozenset(
            player_id
            for player_id, count in signals.add_counts.items()
            if count >= SURFACE_ADD_COUNT_MINIMUM and player_id in on_board
        )
        if trending_adds:
            memberships.append(
                SurfaceMembership(
                    reason=SurfaceReason.SLEEPER_TRENDING_ADD,
                    scoring_preset=scoring_preset,
                    resolved=trending_adds,
                    source_id=signals.source_id or "",
                    signal_type="behavior_add_count",
                ),
            )

    promoted = frozenset(
        player_id
        for player_id, row in context.items()
        if player_id in on_board and _snap_share(row) >= SURFACE_SNAP_SHARE_MINIMUM
    )
    if promoted:
        memberships.append(
            SurfaceMembership(
                reason=SurfaceReason.CURRENT_DEPTH_PROMOTION,
                scoring_preset=scoring_preset,
                resolved=promoted,
                source_id="nflverse",
                signal_type="recent_snap_share",
            ),
        )
    return memberships


def _snap_share(row: Mapping[str, Any]) -> float:
    value = row.get("snap_pct_last3")
    try:
        return 0.0 if value is None else float(value)
    except (TypeError, ValueError):
        return 0.0


def _opportunity_record(
    *,
    player_id: str,
    board_row: Mapping[str, Any],
    published: Mapping[str, Any] | None,
    player_context: Mapping[str, Any],
    signals: BehaviorSignals,
    entry_reasons: Sequence[str],
    outside_tier_board: bool,
    build_id: str,
    season: int,
    through_week: int,
    league_preset_id: str,
    scoring_preset: str,
) -> dict[str, Any]:
    """One row. Every intrinsic field is copied, never recomputed.

    A player inside the published depth has a ``ros_tiers`` record and every intrinsic column
    comes from it verbatim. A surfaced player has none — that is what being outside the
    published depth means — so the fair rank comes from the same board the tier artifact was
    cut from, his tier is null rather than invented, and the distributional columns that only
    the published record carries are null too.
    """
    add_count = signals.add_counts.get(player_id, 0) if signals.available else None
    drop_count = signals.drop_counts.get(player_id, 0) if signals.available else None
    return {
        "schema_version": "1.0",
        "build_id": build_id,
        "season": season,
        "through_week": through_week,
        "league_preset_id": league_preset_id,
        "scoring_preset": scoring_preset,
        "player_id": player_id,
        "display_name": str(
            (published or {}).get("display_name") or board_row.get("display_name") or player_id,
        ),
        "team": (published or {}).get("team") or board_row.get("team"),
        "position": str((published or {}).get("position") or board_row.get("position") or ""),
        "ros_fair_rank": int((published or board_row)["ros_fair_rank"])
        if published
        else int(board_row["fair_rank"]),
        "ros_position_rank": int(published["ros_position_rank"])
        if published
        else int(board_row.get("position_rank") or 0) or 1,
        "ros_expected_vorp": float(published["ros_expected_vorp"]) if published else 0.0,
        "ros_expected_points": float(published["ros_expected_points"]) if published else None,
        "ros_expected_games": float(published["ros_expected_games"]) if published else None,
        "ros_uncertainty": float(published["ros_uncertainty"]) if published else 0.0,
        "ros_tier": (None if outside_tier_board or published is None else published["ros_tier"]),
        "behavior_source_id": signals.source_id,
        "behavior_available": signals.available,
        "behavior_snapshot_at_utc": (
            signals.snapshot_at_utc.isoformat().replace("+00:00", "Z")
            if signals.snapshot_at_utc and signals.available
            else None
        ),
        "behavior_lookback_hours": signals.lookback_hours if signals.available else None,
        "behavior_request_limit": signals.request_limit if signals.available else None,
        "add_count": add_count,
        "drop_count": drop_count,
        "net_add_count": (
            None if add_count is None or drop_count is None else add_count - drop_count
        ),
        "add_rank": signals.add_ranks.get(player_id) if signals.available else None,
        "drop_rank": signals.drop_ranks.get(player_id) if signals.available else None,
        "long_absence": bool((published or {}).get("long_absence", False)),
        "weeks_since_last_game": _optional_float(
            published.get("weeks_since_last_game")
            if published is not None
            else player_context.get("weeks_since_last_game"),
        )
        or 0.0,
        "games_played_to_date": _optional_float(player_context.get("games_to_date")),
        "snap_share_last3": _optional_float(player_context.get("snap_pct_last3")),
        "target_share_last3": _optional_float(player_context.get("target_share_last3")),
        "current_status": (published or {}).get("current_status")
        or player_context.get("current_status"),
        "outside_tier_board": outside_tier_board,
        "surface_reasons": sorted(set(entry_reasons)),
        "quality_flags": sorted(set((published or {}).get("quality_flags", ()))),
    }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
