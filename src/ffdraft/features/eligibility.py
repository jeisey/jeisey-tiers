"""The preseason player universe (ADR-021).

The hardest leakage trap in a historical fantasy dataset is not a feature - it is the row
list. A player-season row exists only if something said the player was in the league. If
that "something" is the target season's final roster, its weekly participation record, or
any dataset assembled after the season, then the universe itself encodes who turned out to
matter, and every model trained on it is quietly told the answer.

So the universe is built **only from evidence that existed before the anchor**:

``prior_season_roster``
    The player appeared on an NFL roster in season Y-1. That season ended in January of
    year Y; the anchor is in September. Nothing about it is in doubt at the anchor.

``draft_class``
    The player was selected in the season-Y NFL draft, held in late April. Draft capital is
    the canonical preseason signal for a rookie.

``depth_snapshot_pre_anchor``
    The player appeared on a timestamped depth-chart snapshot with
    ``observed_at <= anchor``. This is a genuine point-in-time observation of the current
    season's roster - but nflverse only publishes such snapshots from 2025 onward
    (ADR-015), so it widens the universe for those seasons and no others.

What is deliberately **not** used: ``load_rosters(Y)``, ``load_rosters_weekly(Y)`` week 1,
target-season statistics, and anything else describing season Y after it began. The week-1
roster is a particularly tempting near-miss - final cuts happen before a typical late-August
draft - but nflverse publishes it as a week-indexed record with no observation timestamp, so
there is no evidence it was settled by the anchor, and ADR-018 already refuses the analogous
argument for week-1 depth charts. Roster membership and depth rank are different questions,
but both need a defensible availability rule, and week-1 rosters have none.

**The consequence is an era boundary, and it is reported rather than hidden.** Seasons
before 2025 draw on lagged evidence alone, so undrafted rookies - who have no prior roster
season and no draft pick - are absent from those universes. That is a coverage limitation,
not a leak, and it errs in the conservative direction. The quality report breaks eligibility
down by season, position and basis precisely so the boundary is visible to anyone choosing
an evaluation window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

import polars as pl

from ffdraft.anchors import SeasonAnchor
from ffdraft.contracts.enums import CORE_POSITIONS, DepthChartEra, Position
from ffdraft.sources.nflverse import collided_gsis_ids

__all__ = [
    "CORE_POSITION_NAMES",
    "DepthContextState",
    "EligibilityBasis",
    "ExclusionReason",
    "PreseasonUniverse",
    "TeamAtAnchorSource",
    "UniverseEra",
    "build_preseason_universe",
    "latest_pre_anchor_depth",
]

CORE_POSITION_NAMES: tuple[str, ...] = tuple(sorted(str(position) for position in CORE_POSITIONS))


class EligibilityBasis(StrEnum):
    """Pre-anchor evidence that a player belonged to the season's universe."""

    PRIOR_SEASON_ROSTER = "prior_season_roster"
    DRAFT_CLASS = "draft_class"
    DEPTH_SNAPSHOT_PRE_ANCHOR = "depth_snapshot_pre_anchor"


class UniverseEra(StrEnum):
    """Which kinds of evidence a season's universe could draw on."""

    #: Prior-season rosters and the draft class only - every season before 2025.
    LAGGED_ONLY = "lagged_only"
    #: Those plus genuine pre-anchor depth snapshots - 2025 onward.
    SNAPSHOT_2025_PLUS = "snapshot_2025_plus"

    @classmethod
    def for_season(cls, season: int) -> UniverseEra:
        return (
            cls.SNAPSHOT_2025_PLUS
            if DepthChartEra.for_season(season).supports_point_in_time_anchor
            else cls.LAGGED_ONLY
        )


class DepthContextState(StrEnum):
    """ADR-018's three-state depth contract, carried on every row."""

    DEPTH_OBSERVED_AT_ANCHOR = "depth_observed_at_anchor"
    PRIOR_SEASON_ROLE_PROXY = "prior_season_role_proxy"
    DEPTH_UNAVAILABLE = "depth_unavailable"


class TeamAtAnchorSource(StrEnum):
    """Where a row's ``team_at_anchor`` came from, or that it has none."""

    DEPTH_SNAPSHOT_PRE_ANCHOR = "depth_snapshot_pre_anchor"
    DRAFT_TEAM = "draft_team"
    UNAVAILABLE = "unavailable"


class ExclusionReason(StrEnum):
    """Why a candidate was dropped. Every exclusion is counted in the quality report."""

    NON_CORE_POSITION = "non_core_position"
    POSITION_UNKNOWN_AT_ANCHOR = "position_unknown_at_anchor"
    NO_CANONICAL_ID = "no_canonical_id"
    #: The GSIS id names two different players upstream, so every lookup through it fails
    #: closed rather than picking a winner (ADR-019).
    AMBIGUOUS_IDENTITY = "ambiguous_identity"


class PositionSource(StrEnum):
    """Which pre-anchor evidence supplied a candidate's position."""

    DEPTH_SNAPSHOT_PRE_ANCHOR = "depth_snapshot_pre_anchor"
    PRIOR_SEASON_ROSTER = "prior_season_roster"
    DRAFT_CLASS = "draft_class"


@dataclass(frozen=True, slots=True)
class PreseasonUniverse:
    """One season's eligible rows plus the ledger of what was excluded and why."""

    season: int
    era: UniverseEra
    members: pl.DataFrame
    exclusions: pl.DataFrame

    @property
    def size(self) -> int:
        return self.members.height


#: Schema of the per-season universe frame. Declared here because the historical builder
#: joins onto it and a silent column rename would be a silent join failure.
_UNIVERSE_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int32,
    "gsis_id": pl.String,
    "position": pl.String,
    "position_source": pl.String,
    "eligibility_basis": pl.String,
    "universe_era": pl.String,
    "display_name": pl.String,
    "team_at_anchor": pl.String,
    "team_at_anchor_source": pl.String,
    "depth_rank_at_anchor": pl.Int32,
    "depth_observed_at_utc": pl.Datetime(time_unit="us", time_zone="UTC"),
}

_EXCLUSION_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "season": pl.Int32,
    "gsis_id": pl.String,
    "reason": pl.String,
    "detail": pl.String,
}


def latest_pre_anchor_depth(
    depth: pl.DataFrame,
    anchor: SeasonAnchor,
) -> pl.DataFrame:
    """The most recent depth-chart snapshot that existed at ``anchor``.

    Weekly-era rows are dropped outright: they carry no observation timestamp, so there is
    no way to establish they predate the anchor, and ADR-018 forbids treating week 1 as a
    preseason reading. Snapshot-era rows are filtered to ``observed_at <= anchor`` and then
    narrowed to the single latest timestamp, which is what "the depth chart as it stood at
    the anchor" means.
    """
    if depth.is_empty():
        return depth
    usable = depth.filter(
        (pl.col("era") == str(DepthChartEra.SNAPSHOT_2025_PLUS))
        & pl.col("observed_at_utc").is_not_null()
        & (pl.col("observed_at_utc") <= anchor.anchor_at_utc),
    )
    if usable.is_empty():
        return usable
    latest = usable.get_column("observed_at_utc").max()
    return usable.filter(pl.col("observed_at_utc") == latest)


def _best_depth_row_per_player(snapshot: pl.DataFrame) -> pl.DataFrame:
    """One row per player: the shallowest **core-position** slot he is listed in.

    Restricting to QB/RB/WR/TE before choosing matters. A depth chart lists the same player
    in several slots - a receiver is often also the punt returner, a back the kick returner -
    and those special-teams slots carry their own rank 1. Choosing the globally shallowest
    rank would report a receiver as a rank-1 *returner*, which is a depth rank for a
    position this project does not model. Ties within the core positions break on position
    name and team so the choice is deterministic.
    """
    if snapshot.is_empty():
        return snapshot
    core = snapshot.filter(
        pl.col("gsis_id").is_not_null()
        & pl.col("position").str.strip_chars().str.to_uppercase().is_in(list(CORE_POSITION_NAMES)),
    )
    return (
        core.with_columns(pl.col("depth_rank").fill_null(99).alias("_rank_for_sort"))
        .sort(["gsis_id", "_rank_for_sort", "position", "team"])
        .unique(subset=["gsis_id"], keep="first", maintain_order=True)
        .drop("_rank_for_sort")
    )


def _normalize_position(raw: str | None) -> str | None:
    parsed = Position.parse(raw)
    return str(parsed) if parsed is not None else None


def build_preseason_universe(
    season: int,
    *,
    anchor: SeasonAnchor,
    prior_roster: pl.DataFrame,
    draft_picks: pl.DataFrame,
    depth_chart: pl.DataFrame,
    player_master: pl.DataFrame,
) -> PreseasonUniverse:
    """Assemble the eligible ``(season, player)`` rows from pre-anchor evidence only.

    ``prior_roster`` must be the **previous** season's roster frame; passing the target
    season's roster would defeat the entire construction, so the caller's slice is the one
    place that must be right and the leakage suite asserts it from the built dataset.
    """
    era = UniverseEra.for_season(season)
    snapshot = _best_depth_row_per_player(latest_pre_anchor_depth(depth_chart, anchor))
    rookies = draft_picks.filter(pl.col("draft_year") == season)
    # A GSIS id that names two different players upstream cannot safely identify either of
    # them, so it is barred from the universe entirely rather than resolved by guesswork.
    poisoned = collided_gsis_ids(prior_roster)

    candidates: dict[str, dict[str, object]] = {}
    exclusions: list[dict[str, object]] = []

    def register(
        gsis_id: str | None,
        *,
        basis: EligibilityBasis,
        position: str | None,
        raw_position: str | None,
        position_source: PositionSource,
        display_name: str | None,
        team: str | None = None,
        team_source: TeamAtAnchorSource = TeamAtAnchorSource.UNAVAILABLE,
        depth_rank: int | None = None,
        observed_at: datetime | None = None,
    ) -> None:
        if not gsis_id:
            exclusions.append(
                {
                    "season": season,
                    "gsis_id": None,
                    "reason": str(ExclusionReason.NO_CANONICAL_ID),
                    "detail": str(basis),
                },
            )
            return
        entry = candidates.get(gsis_id)
        if entry is None:
            entry = {
                "season": season,
                "gsis_id": gsis_id,
                "position": None,
                "raw_position": None,
                "position_source": None,
                "bases": [],
                "universe_era": str(era),
                "display_name": None,
                "team_at_anchor": None,
                "team_at_anchor_source": str(TeamAtAnchorSource.UNAVAILABLE),
                "depth_rank_at_anchor": None,
                "depth_observed_at_utc": None,
            }
            candidates[gsis_id] = entry
        bases = entry["bases"]
        assert isinstance(bases, list)
        if str(basis) not in bases:
            bases.append(str(basis))
        if entry["position"] is None and position is not None:
            entry["position"] = position
            entry["position_source"] = str(position_source)
        if entry["raw_position"] is None and raw_position:
            entry["raw_position"] = raw_position
        if entry["display_name"] is None and display_name:
            entry["display_name"] = display_name
        if entry["team_at_anchor"] is None and team:
            entry["team_at_anchor"] = team
            entry["team_at_anchor_source"] = str(team_source)
        if entry["depth_rank_at_anchor"] is None and depth_rank is not None:
            entry["depth_rank_at_anchor"] = depth_rank
        if entry["depth_observed_at_utc"] is None and observed_at is not None:
            entry["depth_observed_at_utc"] = observed_at

    # Precedence for position and team is "most recent pre-anchor evidence first": a depth
    # snapshot taken days before the anchor beats last season's roster, which beats the
    # April draft class. Registering in that order lets the first writer win.
    for row in snapshot.iter_rows(named=True):
        register(
            row.get("gsis_id"),
            basis=EligibilityBasis.DEPTH_SNAPSHOT_PRE_ANCHOR,
            position=_normalize_position(row.get("position")),
            raw_position=row.get("position"),
            position_source=PositionSource.DEPTH_SNAPSHOT_PRE_ANCHOR,
            display_name=row.get("player_name"),
            team=row.get("team"),
            team_source=TeamAtAnchorSource.DEPTH_SNAPSHOT_PRE_ANCHOR,
            depth_rank=row.get("depth_rank"),
            observed_at=row.get("observed_at_utc"),
        )

    for row in prior_roster.iter_rows(named=True):
        register(
            row.get("gsis_id"),
            basis=EligibilityBasis.PRIOR_SEASON_ROSTER,
            position=_normalize_position(row.get("position"))
            or _normalize_position(row.get("depth_chart_position")),
            raw_position=row.get("position") or row.get("depth_chart_position"),
            position_source=PositionSource.PRIOR_SEASON_ROSTER,
            display_name=row.get("display_name"),
        )

    for row in rookies.iter_rows(named=True):
        register(
            row.get("gsis_id"),
            basis=EligibilityBasis.DRAFT_CLASS,
            position=_normalize_position(row.get("position")),
            raw_position=row.get("position"),
            position_source=PositionSource.DRAFT_CLASS,
            display_name=row.get("player_name"),
            team=row.get("draft_team"),
            team_source=TeamAtAnchorSource.DRAFT_TEAM,
        )

    names = dict(
        player_master.select("gsis_id", "display_name").drop_nulls().iter_rows(),
    )

    members: list[dict[str, object]] = []
    for gsis_id, entry in candidates.items():
        if gsis_id in poisoned:
            exclusions.append(
                {
                    "season": season,
                    "gsis_id": gsis_id,
                    "reason": str(ExclusionReason.AMBIGUOUS_IDENTITY),
                    "detail": "gsis id names more than one player in the prior-season roster",
                },
            )
            continue
        position = entry["position"]
        raw_position = entry["raw_position"]
        if position is None:
            # A raw position that simply is not QB/RB/WR/TE - a guard, a safety, a punter -
            # is a *known* position this project does not model. Recording it as "unknown"
            # would bury tens of thousands of correctly excluded linemen in a bucket meant
            # for genuine evidence gaps, and make the ledger useless for spotting one.
            reason = (
                ExclusionReason.NON_CORE_POSITION
                if raw_position
                else ExclusionReason.POSITION_UNKNOWN_AT_ANCHOR
            )
            exclusions.append(
                {
                    "season": season,
                    "gsis_id": gsis_id,
                    "reason": str(reason),
                    "detail": str(raw_position) if raw_position else "|".join(entry["bases"]),  # type: ignore[arg-type]
                },
            )
            continue
        if position not in CORE_POSITION_NAMES:
            exclusions.append(
                {
                    "season": season,
                    "gsis_id": gsis_id,
                    "reason": str(ExclusionReason.NON_CORE_POSITION),
                    "detail": str(position),
                },
            )
            continue
        bases = entry["bases"]
        assert isinstance(bases, list)
        members.append(
            {
                "season": season,
                "gsis_id": gsis_id,
                "position": position,
                "position_source": entry["position_source"],
                "eligibility_basis": "|".join(sorted(bases)),
                "universe_era": str(era),
                "display_name": entry["display_name"] or names.get(gsis_id) or gsis_id,
                "team_at_anchor": entry["team_at_anchor"],
                "team_at_anchor_source": entry["team_at_anchor_source"],
                "depth_rank_at_anchor": entry["depth_rank_at_anchor"],
                "depth_observed_at_utc": entry["depth_observed_at_utc"],
            },
        )

    member_frame = (
        pl.DataFrame(members, schema=_UNIVERSE_SCHEMA, orient="row").sort("gsis_id")
        if members
        else pl.DataFrame(schema=_UNIVERSE_SCHEMA)
    )
    exclusion_frame = (
        pl.DataFrame(exclusions, schema=_EXCLUSION_SCHEMA, orient="row").sort(
            ["reason", "gsis_id"],
            nulls_last=True,
        )
        if exclusions
        else pl.DataFrame(schema=_EXCLUSION_SCHEMA)
    )
    return PreseasonUniverse(
        season=season,
        era=era,
        members=member_frame,
        exclusions=exclusion_frame,
    )


def depth_context_state(
    *,
    depth_rank_observed: bool,
    prior_role_known: bool,
) -> DepthContextState:
    """Resolve ADR-018's three states for one row.

    An observed pre-anchor snapshot wins. Failing that, a lagged usage-derived role estimate
    is the honest fallback for a veteran. A player with neither - a pre-2025 rookie, or
    anyone whose prior season left no usable role signal - gets ``depth_unavailable`` and
    keeps null depth features. Nothing here ever invents a rank.
    """
    if depth_rank_observed:
        return DepthContextState.DEPTH_OBSERVED_AT_ANCHOR
    if prior_role_known:
        return DepthContextState.PRIOR_SEASON_ROLE_PROXY
    return DepthContextState.DEPTH_UNAVAILABLE


def universe_summary(universes: Sequence[PreseasonUniverse]) -> Mapping[int, int]:
    return {universe.season: universe.size for universe in universes}
