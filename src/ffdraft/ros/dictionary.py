"""The rest-of-season feature dictionary.

Every Phase-11 model input is declared here with an **availability rule**, and the rule is
the thing that decides whether a column may exist at all. `docs/RELEASE2_ROADMAP.md` 11.3
states it as a design rule:

> "Useful today" is not enough. A feature must be reproducible at equivalent historical
> cutoffs or be annotation-only.

The dictionary is built in two blocks, and the split is deliberate.

**The preseason block is inherited, not re-derived.** Every column of Phase 3's frozen
``intrinsic_core_v1`` selection is a Phase-11 input under exactly its Phase-2 declaration.
Those columns were built from evidence dated before the season's draft anchor, so they are
available at *every* in-season cutoff by construction, and re-declaring them here would
create a second definition that could drift from the first. Their leakage argument, their
forbidden-feature audit and their source lineage all carry over unchanged.

**The in-season block is new, and every column of it is a cumulative read of weeks at or
before the cutoff.** :mod:`ffdraft.ros.panel` is the only place those sums are computed, and
:mod:`ffdraft.ros.leakage` proves the window by rebuilding a snapshot from a panel whose
post-cutoff weeks have been deleted and asserting the features are byte-identical.

Two categories are deliberately absent.

*Injury and practice-report status.* nflverse publishes weekly injury reports, but this
repository has never ingested them, has no measured historical coverage for them and has no
production capture path for them. Admitting them on the strength of "the current data
exists" is exactly the move 11.3 forbids. The football-only proxies - ``weeks_since_last_game``,
``consecutive_weeks_missed``, ``games_share_to_date`` - carry the same information the
schedule can support, and the gap is recorded rather than papered over (ADR-070).

*Anything market-derived.* The intrinsic firewall is unchanged and is audited by the same
:func:`ffdraft.quality.audit_intrinsic_feature_names` the preseason model uses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import polars as pl

from ffdraft.features.dictionary import (
    ALL_CORE_POSITIONS,
    Availability,
    FeatureRole,
    FeatureSpec,
    dictionary_by_name,
    feature_schema_hash,
)
from ffdraft.modeling.features import core_feature_selection

__all__ = [
    "ROS_FEATURE_SCHEMA_VERSION",
    "ROS_FEATURE_SET_VERSION",
    "RosFeatureSelection",
    "ros_feature_dictionary",
    "ros_feature_names",
    "ros_feature_schema_hash",
    "ros_feature_selection",
    "ros_in_season_features",
    "ros_dictionary_markdown",
]

#: Bump when a column is added, removed or re-meaninged.
ROS_FEATURE_SCHEMA_VERSION = "ros_features_v1"

#: The versioned model-input view. Separate from the schema version because a future phase
#: may narrow the inputs without changing what the dataset carries.
ROS_FEATURE_SET_VERSION = "ros_core_v1"

_NFLVERSE = "nflreadpy"
_FFOPPORTUNITY = "ffopportunity"
_DERIVED = "ffdraft.ros.panel"


def _cutoff(name: str, dtype: Any, unit: str, definition: str) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=dtype,
        unit=unit,
        definition=definition,
        availability=Availability.CUTOFF_DERIVED,
        family="cutoff",
        sources=(_DERIVED,),
        missing_semantics="never missing; derived from the snapshot key alone",
        nullable=False,
    )


def _in_season(
    name: str,
    dtype: Any,
    unit: str,
    definition: str,
    family: str,
    *,
    sources: tuple[str, ...] = (_NFLVERSE,),
    positions: tuple[str, ...] = ALL_CORE_POSITIONS,
    minimum_denominator: int | None = None,
    missing_semantics: str = "missing means the cutoff window contains no qualifying evidence",
    nullable: bool = True,
    role: FeatureRole = FeatureRole.FEATURE,
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=dtype,
        unit=unit,
        definition=definition,
        availability=Availability.IN_SEASON_TO_DATE,
        family=family,
        sources=sources,
        positions=positions,
        minimum_denominator=minimum_denominator,
        missing_semantics=missing_semantics,
        nullable=nullable,
        role=role,
    )


#: Snap-share and expected-point rates need enough games behind them to mean anything. The
#: values are small and predeclared: one game for a per-game mean, and a volume floor for a
#: ratio whose denominator can be zero for a legitimate reason.
_MIN_TARGETS = 5
_MIN_CARRIES = 5
_MIN_OPPORTUNITIES = 10

_CUTOFF_FEATURES: tuple[FeatureSpec, ...] = (
    _cutoff(
        "through_week",
        pl.Int32,
        "week",
        "The snapshot cutoff: the last completed regular-season week the row may read.",
    ),
    _cutoff(
        "remaining_horizon_weeks",
        pl.Int32,
        "weeks",
        "Scored horizon weeks after the cutoff, byes included. Calendar weeks, not games.",
    ),
    _cutoff(
        "season_share_remaining",
        pl.Float64,
        "ratio",
        "remaining_horizon_weeks divided by the season's full scored horizon length.",
    ),
)

_AVAILABILITY_FEATURES: tuple[FeatureSpec, ...] = (
    _in_season(
        "games_to_date",
        pl.Int32,
        "games",
        "Scored appearances in weeks 1..through_week.",
        "in_season_availability",
        missing_semantics="never missing; zero means the player has not appeared",
        nullable=False,
    ),
    _in_season(
        "games_share_to_date",
        pl.Float64,
        "ratio",
        "games_to_date divided by through_week: the share of elapsed weeks played.",
        "in_season_availability",
        missing_semantics="never missing; through_week is at least one",
        nullable=False,
    ),
    _in_season(
        "weeks_missed_to_date",
        pl.Int32,
        "weeks",
        "Elapsed weeks in which the player did not appear, byes included.",
        "in_season_availability",
        missing_semantics="never missing",
        nullable=False,
    ),
    _in_season(
        "weeks_since_last_game",
        pl.Int32,
        "weeks",
        "Weeks between the cutoff and the last appearance; 0 means he played in the cutoff week.",
        "in_season_availability",
        missing_semantics="missing means the player has never appeared this season",
    ),
    _in_season(
        "consecutive_weeks_missed",
        pl.Int32,
        "weeks",
        "Unbroken run of missed weeks ending at the cutoff.",
        "in_season_availability",
        missing_semantics="never missing",
        nullable=False,
    ),
    _in_season(
        "active_last_week",
        pl.Boolean,
        "flag",
        "Whether the player appeared in the cutoff week itself.",
        "in_season_availability",
        missing_semantics="never missing",
        nullable=False,
        role=FeatureRole.INDICATOR,
    ),
    _in_season(
        "games_last3",
        pl.Int32,
        "games",
        "Appearances in the three calendar weeks ending at the cutoff.",
        "in_season_availability",
        missing_semantics="never missing",
        nullable=False,
    ),
    _in_season(
        "has_played_this_season",
        pl.Boolean,
        "flag",
        "Whether the player has at least one appearance at or before the cutoff.",
        "in_season_availability",
        missing_semantics="never missing",
        nullable=False,
        role=FeatureRole.INDICATOR,
    ),
    _in_season(
        "in_preseason_universe",
        pl.Boolean,
        "flag",
        (
            "Whether the player was in the season's leakage-safe preseason eligible universe. "
            "False marks an in-season arrival, whose preseason feature block is null."
        ),
        "in_season_availability",
        sources=(_DERIVED,),
        missing_semantics="never missing",
        nullable=False,
        role=FeatureRole.INDICATOR,
    ),
    _in_season(
        "team_remaining_scheduled_games",
        pl.Int32,
        "games",
        (
            "Regular-season games inside the scored horizon still scheduled for the player's "
            "observed team after the cutoff. The schedule is published before Week 1 and is "
            "not an outcome; the team assignment is the last one actually observed."
        ),
        "in_season_availability",
        missing_semantics="missing means no team has been observed at or before the cutoff",
    ),
)

_PRODUCTION_FEATURES: tuple[FeatureSpec, ...] = (
    _in_season(
        "points_to_date",
        pl.Float64,
        "points",
        "Fantasy points in weeks 1..through_week, in the row's own scoring preset.",
        "in_season_production",
        missing_semantics="never missing; zero means no production",
        nullable=False,
    ),
    _in_season(
        "ppg_to_date",
        pl.Float64,
        "points/game",
        "points_to_date divided by games_to_date.",
        "in_season_production",
        minimum_denominator=1,
    ),
    _in_season(
        "points_per_week_to_date",
        pl.Float64,
        "points/week",
        "points_to_date divided by through_week: production per elapsed week, missed weeks "
        "counted as zero. Availability and rate collapsed into one number on purpose.",
        "in_season_production",
        missing_semantics="never missing",
        nullable=False,
    ),
    _in_season(
        "ppg_last3",
        pl.Float64,
        "points/game",
        "Points per appearance over the three calendar weeks ending at the cutoff.",
        "in_season_production",
        minimum_denominator=1,
    ),
    _in_season(
        "ppg_trend",
        pl.Float64,
        "points/game",
        "ppg_last3 minus ppg_to_date. Positive means the recent form is above the season rate.",
        "in_season_production",
    ),
    _in_season(
        "best_week_points_to_date",
        pl.Float64,
        "points",
        "Highest single-week fantasy total at or before the cutoff.",
        "in_season_production",
        minimum_denominator=1,
    ),
    _in_season(
        "points_sd_to_date",
        pl.Float64,
        "points",
        "Sample standard deviation of weekly points across appearances at or before the cutoff.",
        "in_season_production",
        minimum_denominator=2,
    ),
)

_OPPORTUNITY_FEATURES: tuple[FeatureSpec, ...] = (
    _in_season(
        "targets_per_game_to_date",
        pl.Float64,
        "targets/game",
        "Targets per appearance at or before the cutoff.",
        "in_season_opportunity",
        positions=("RB", "WR", "TE"),
        minimum_denominator=1,
    ),
    _in_season(
        "carries_per_game_to_date",
        pl.Float64,
        "carries/game",
        "Rushing attempts per appearance at or before the cutoff.",
        "in_season_opportunity",
        positions=("QB", "RB", "WR"),
        minimum_denominator=1,
    ),
    _in_season(
        "pass_attempts_per_game_to_date",
        pl.Float64,
        "attempts/game",
        "Pass attempts per appearance at or before the cutoff.",
        "in_season_opportunity",
        positions=("QB",),
        minimum_denominator=1,
    ),
    _in_season(
        "touches_per_game_to_date",
        pl.Float64,
        "touches/game",
        "Carries plus receptions per appearance at or before the cutoff.",
        "in_season_opportunity",
        minimum_denominator=1,
    ),
    _in_season(
        "target_share_to_date",
        pl.Float64,
        "ratio",
        (
            "Player targets divided by his team's targets, summed over the weeks he played. "
            "Both halves come from the same weekly rows, so the ratio has one provenance."
        ),
        "in_season_opportunity",
        positions=("RB", "WR", "TE"),
        minimum_denominator=_MIN_TARGETS,
    ),
    _in_season(
        "carry_share_to_date",
        pl.Float64,
        "ratio",
        "Player carries divided by his team's carries over the weeks he played.",
        "in_season_opportunity",
        positions=("QB", "RB", "WR"),
        minimum_denominator=_MIN_CARRIES,
    ),
    _in_season(
        "air_yards_per_game_to_date",
        pl.Float64,
        "yards/game",
        "Receiving air yards per appearance at or before the cutoff.",
        "in_season_opportunity",
        positions=("RB", "WR", "TE"),
        minimum_denominator=1,
    ),
    _in_season(
        "snap_pct_mean_to_date",
        pl.Float64,
        "ratio",
        "Mean share of team offensive snaps across appearances at or before the cutoff.",
        "in_season_opportunity",
        minimum_denominator=1,
    ),
    _in_season(
        "snap_pct_last3",
        pl.Float64,
        "ratio",
        "Mean offensive snap share over the three calendar weeks ending at the cutoff.",
        "in_season_opportunity",
        minimum_denominator=1,
    ),
    _in_season(
        "snap_pct_trend",
        pl.Float64,
        "ratio",
        "snap_pct_last3 minus snap_pct_mean_to_date: a role gaining or losing ground.",
        "in_season_opportunity",
    ),
    _in_season(
        "target_share_last3",
        pl.Float64,
        "ratio",
        "Target share over the three calendar weeks ending at the cutoff.",
        "in_season_opportunity",
        positions=("RB", "WR", "TE"),
        minimum_denominator=1,
    ),
    _in_season(
        "target_share_trend",
        pl.Float64,
        "ratio",
        "target_share_last3 minus target_share_to_date.",
        "in_season_opportunity",
        positions=("RB", "WR", "TE"),
    ),
    _in_season(
        "expected_points_per_game_to_date",
        pl.Float64,
        "points/game",
        "ffopportunity expected fantasy points per appearance at or before the cutoff.",
        "in_season_opportunity",
        sources=(_FFOPPORTUNITY,),
        minimum_denominator=1,
    ),
    _in_season(
        "points_over_expected_per_game_to_date",
        pl.Float64,
        "points/game",
        (
            "Points per game minus expected points per game. Separates a player who is "
            "scoring on volume from one who is scoring on conversion."
        ),
        "in_season_opportunity",
        sources=(_NFLVERSE, _FFOPPORTUNITY),
    ),
)

_EFFICIENCY_FEATURES: tuple[FeatureSpec, ...] = (
    _in_season(
        "yards_per_target_to_date",
        pl.Float64,
        "yards/target",
        "Receiving yards divided by targets at or before the cutoff.",
        "in_season_efficiency",
        positions=("RB", "WR", "TE"),
        minimum_denominator=_MIN_TARGETS,
    ),
    _in_season(
        "yards_per_carry_to_date",
        pl.Float64,
        "yards/carry",
        "Rushing yards divided by carries at or before the cutoff.",
        "in_season_efficiency",
        positions=("QB", "RB", "WR"),
        minimum_denominator=_MIN_CARRIES,
    ),
    _in_season(
        "catch_rate_to_date",
        pl.Float64,
        "ratio",
        "Receptions divided by targets at or before the cutoff.",
        "in_season_efficiency",
        positions=("RB", "WR", "TE"),
        minimum_denominator=_MIN_TARGETS,
    ),
    _in_season(
        "td_per_opportunity_to_date",
        pl.Float64,
        "ratio",
        (
            "Touchdowns divided by opportunities (pass attempts plus carries plus targets). "
            "The most regression-prone quantity in the block, and carried for that reason."
        ),
        "in_season_efficiency",
        minimum_denominator=_MIN_OPPORTUNITIES,
    ),
    _in_season(
        "points_per_opportunity_to_date",
        pl.Float64,
        "points",
        "Fantasy points divided by opportunities at or before the cutoff.",
        "in_season_efficiency",
        minimum_denominator=_MIN_OPPORTUNITIES,
    ),
)

_TEAM_CONTEXT_FEATURES: tuple[FeatureSpec, ...] = (
    _in_season(
        "team_points_per_game_to_date",
        pl.Float64,
        "points/game",
        (
            "Standard-scoring fantasy points scored by the player's team's skill players per "
            "team game at or before the cutoff. Preset-independent by design: this is an "
            "offence-quality measure, not the row's own scoring flavour."
        ),
        "in_season_team_context",
        minimum_denominator=1,
    ),
    _in_season(
        "team_pass_rate_to_date",
        pl.Float64,
        "ratio",
        "Team pass attempts divided by attempts plus carries at or before the cutoff.",
        "in_season_team_context",
        minimum_denominator=1,
    ),
    _in_season(
        "team_plays_per_game_to_date",
        pl.Float64,
        "plays/game",
        "Team pass attempts plus carries per team game at or before the cutoff.",
        "in_season_team_context",
        minimum_denominator=1,
    ),
    _in_season(
        "team_changed_in_season",
        pl.Boolean,
        "flag",
        "Whether more than one team has been observed for the player at or before the cutoff.",
        "in_season_team_context",
        sources=(_DERIVED,),
        missing_semantics="never missing",
        nullable=False,
        role=FeatureRole.INDICATOR,
    ),
)

#: Every Phase-11-specific column, in declaration order.
ROS_IN_SEASON_DICTIONARY: tuple[FeatureSpec, ...] = (
    *_CUTOFF_FEATURES,
    *_AVAILABILITY_FEATURES,
    *_PRODUCTION_FEATURES,
    *_OPPORTUNITY_FEATURES,
    *_EFFICIENCY_FEATURES,
    *_TEAM_CONTEXT_FEATURES,
)


def ros_in_season_features() -> tuple[FeatureSpec, ...]:
    """The new Phase-11 columns only, without the inherited preseason block."""
    return ROS_IN_SEASON_DICTIONARY


def _preseason_specs() -> tuple[FeatureSpec, ...]:
    """Phase 3's frozen core selection, taken from the Phase-2 dictionary unchanged."""
    specs = dictionary_by_name()
    return tuple(specs[name] for name in core_feature_selection().included)


def ros_feature_dictionary() -> tuple[FeatureSpec, ...]:
    """The full Phase-11 dictionary: inherited preseason block, then in-season block."""
    return (*_preseason_specs(), *ROS_IN_SEASON_DICTIONARY)


def ros_feature_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in ros_feature_dictionary() if spec.role.is_model_input)


def ros_feature_schema_hash() -> str:
    """Stable hash of the declared Phase-11 columns and their types."""
    payload = json.dumps(
        {
            "schema_version": ROS_FEATURE_SCHEMA_VERSION,
            "preseason_schema_hash": feature_schema_hash(),
            "columns": [
                {
                    "name": spec.name,
                    "dtype": str(spec.dtype),
                    "availability": str(spec.availability),
                    "role": str(spec.role),
                }
                for spec in ros_feature_dictionary()
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class RosFeatureSelection:
    """The versioned Phase-11 model input view."""

    version: str
    included: tuple[str, ...]
    schema_version: str
    schema_hash: str
    preseason_set_version: str

    @property
    def preseason(self) -> tuple[str, ...]:
        names = {spec.name for spec in _preseason_specs()}
        return tuple(name for name in self.included if name in names)

    @property
    def in_season(self) -> tuple[str, ...]:
        names = {spec.name for spec in ROS_IN_SEASON_DICTIONARY}
        return tuple(name for name in self.included if name in names)

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "version": self.version,
                "schema_version": self.schema_version,
                "schema_hash": self.schema_hash,
                "preseason_set_version": self.preseason_set_version,
                "included": list(self.included),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        specs = {spec.name: spec for spec in ros_feature_dictionary()}
        return {
            "feature_set_version": self.version,
            "feature_set_hash": self.fingerprint(),
            "schema_version": self.schema_version,
            "schema_hash": self.schema_hash,
            "preseason_set_version": self.preseason_set_version,
            "included_count": len(self.included),
            "preseason_count": len(self.preseason),
            "in_season_count": len(self.in_season),
            "included": [
                {
                    "name": name,
                    "family": specs[name].family,
                    "availability": str(specs[name].availability),
                    "dtype": str(specs[name].dtype),
                }
                for name in self.included
            ],
        }


def ros_feature_selection() -> RosFeatureSelection:
    """The frozen Phase-11 model input set."""
    return RosFeatureSelection(
        version=ROS_FEATURE_SET_VERSION,
        included=ros_feature_names(),
        schema_version=ROS_FEATURE_SCHEMA_VERSION,
        schema_hash=ros_feature_schema_hash(),
        preseason_set_version=core_feature_selection().version,
    )


def ros_specs_by_name() -> Mapping[str, FeatureSpec]:
    return {spec.name: spec for spec in ros_feature_dictionary()}


def ros_dictionary_markdown(specs: Iterable[FeatureSpec] | None = None) -> str:
    """The published table. One row per column, availability rule included."""
    rows: Sequence[FeatureSpec] = tuple(specs) if specs is not None else ROS_IN_SEASON_DICTIONARY
    header = "| name | family | availability | unit | definition |\n|---|---|---|---|---|"
    body = "\n".join(
        f"| `{spec.name}` | {spec.family} | {spec.availability} | {spec.unit} | "
        f"{spec.definition.replace(chr(10), ' ')} |"
        for spec in rows
    )
    return f"{header}\n{body}"
