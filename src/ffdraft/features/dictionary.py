"""The feature dictionary.

Every column of the historical modelling table is declared here once, with its formula,
its source lineage and - most importantly - the rule that makes it available at the draft
anchor. Three things read this module rather than restating it:

* :data:`HISTORICAL_FEATURE_CONTRACT` is *built* from the dictionary, so the table and its
  documentation cannot drift apart;
* the leakage suite checks each column's declared availability against how the builder
  actually computed it (`docs/TEST_STRATEGY.md` 2.5);
* the forbidden-feature audit (:mod:`ffdraft.quality.forbidden`) runs over
  :func:`intrinsic_feature_names` and :func:`feature_lineage`, so a market-derived column
  could not be added here without failing a test.

**Availability is the whole point.** A feature is admissible only if one of these holds:

``static_biographical``
    A fact that does not change with time (birth date, draft round, a combine forty). True
    at the anchor because it was true years earlier.

``anchor_derived``
    Computed from the anchor instant and static facts - age at the anchor, seasons since
    the draft. No observation is involved.

``season_lagged``
    An aggregate over seasons strictly before the target season. The declared
    ``lookback_seasons`` are offsets: ``(1,)`` means the previous season only. The builder
    stamps ``max_lagged_source_season`` on every row and a leakage test asserts it is always
    less than ``season``.

``pre_anchor_observation``
    A timestamped observation that satisfied ``observed_at <= anchor_at``. Only the
    2025-onward depth-chart snapshots qualify (ADR-015/ADR-018); the builder stamps
    ``depth_observed_at_utc`` and a leakage test asserts the inequality.

``preseason_universe``
    Membership evidence establishing the player existed in the league's preseason universe,
    itself built only from prior-season rosters, the target season's draft class, and
    pre-anchor depth snapshots (ADR-021).

``anchor_metadata`` / ``label_lineage``
    Keys, the anchor itself, and provenance columns the leakage tests read.

Market and expert signals are absent by construction and may never be added: ADR-002 is not
negotiable, and ``allowed_in_intrinsic`` exists so that even a *context* column carrying
something inadmissible could not silently become a model input.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import polars as pl

from ffdraft.contracts.frames import ColumnSpec, DType, FrameContract

__all__ = [
    "ALL_CORE_POSITIONS",
    "CAREER_LOOKBACK_SEASONS",
    "Availability",
    "FANTASY_LABEL_CONTRACT",
    "FEATURE_DICTIONARY",
    "FEATURE_SCHEMA_VERSION",
    "FeatureRole",
    "FeatureSpec",
    "HISTORICAL_FEATURE_CONTRACT",
    "VORP_LABEL_CONTRACT",
    "feature_lineage",
    "feature_names_by_family",
    "feature_schema_hash",
    "intrinsic_feature_names",
    "lagged_feature_names",
    "spec_for",
    "specs_by_availability",
    "timestamped_feature_names",
    "to_records",
]

#: Bump on any change to the columns, their meaning or their availability rules. Model
#: artifacts record it so an inference-time schema mismatch is detectable (ADR/ARCH 7).
FEATURE_SCHEMA_VERSION = "historical_features_v1"

ALL_CORE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

_NFLVERSE = "nflreadpy"
_FFOPPORTUNITY = "ffopportunity"


class Availability(StrEnum):
    """Why a column is knowable at the draft anchor."""

    ANCHOR_METADATA = "anchor_metadata"
    STATIC_BIOGRAPHICAL = "static_biographical"
    ANCHOR_DERIVED = "anchor_derived"
    SEASON_LAGGED = "season_lagged"
    PRE_ANCHOR_OBSERVATION = "pre_anchor_observation"
    PRESEASON_UNIVERSE = "preseason_universe"
    LABEL_LINEAGE = "label_lineage"
    #: Phase 11 only. Derived from the rest-of-season cutoff itself - the snapshot week and
    #: what it implies about how much season is left - and from nothing observed.
    CUTOFF_DERIVED = "cutoff_derived"
    #: Phase 11 only. Computed from completed weeks at or before the snapshot cutoff of the
    #: season being predicted. Never available to a preseason model, and never permitted to
    #: read a week after its own cutoff (:mod:`ffdraft.ros.cutoff`).
    IN_SEASON_TO_DATE = "in_season_to_date"


class FeatureRole(StrEnum):
    """What a column is for."""

    KEY = "key"
    ANCHOR = "anchor"
    CONTEXT = "context"
    FEATURE = "feature"
    INDICATOR = "indicator"
    LINEAGE = "lineage"

    @property
    def is_model_input(self) -> bool:
        """Only features and their missingness indicators are offered to an estimator."""
        return self in {FeatureRole.FEATURE, FeatureRole.INDICATOR}


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One declared column of the historical feature table."""

    name: str
    dtype: DType
    unit: str
    definition: str
    availability: Availability
    family: str
    sources: tuple[str, ...] = ()
    role: FeatureRole = FeatureRole.FEATURE
    lookback_seasons: tuple[int, ...] = ()
    positions: tuple[str, ...] = ALL_CORE_POSITIONS
    missing_semantics: str = "missing means the input was unavailable"
    missingness_indicator: str | None = None
    allowed_in_intrinsic: bool = True
    nullable: bool = True
    minimum_denominator: int | None = None

    def __post_init__(self) -> None:
        if self.availability is Availability.SEASON_LAGGED and not self.lookback_seasons:
            raise ValueError(f"{self.name}: a season-lagged feature must declare a lookback")
        if self.lookback_seasons and any(offset < 1 for offset in self.lookback_seasons):
            raise ValueError(
                f"{self.name}: lookback offsets must be >= 1; offset 0 would be the "
                "target season itself",
            )
        if self.role.is_model_input and not self.allowed_in_intrinsic:
            raise ValueError(
                f"{self.name}: a column barred from the intrinsic model cannot be a model "
                "input; make it context or remove it",
            )

    @property
    def column(self) -> ColumnSpec:
        return ColumnSpec(
            self.name,
            self.dtype,
            nullable=self.nullable,
            description=self.definition,
        )

    def to_record(self) -> dict[str, object]:
        """The dictionary row published in the documentation and the quality report."""
        return {
            "name": self.name,
            "family": self.family,
            "role": str(self.role),
            "dtype": str(self.dtype),
            "unit": self.unit,
            "definition": self.definition,
            "sources": list(self.sources),
            "positions": list(self.positions),
            "availability": str(self.availability),
            "lookback_seasons": list(self.lookback_seasons),
            "minimum_denominator": self.minimum_denominator,
            "missing_semantics": self.missing_semantics,
            "missingness_indicator": self.missingness_indicator,
            "allowed_in_intrinsic": self.allowed_in_intrinsic,
            "nullable": self.nullable,
        }


def _key(name: str, dtype: DType, definition: str) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=dtype,
        unit="identifier",
        definition=definition,
        availability=Availability.ANCHOR_METADATA,
        family="key",
        role=FeatureRole.KEY,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    )


def _lagged(
    name: str,
    definition: str,
    *,
    unit: str,
    family: str,
    offsets: tuple[int, ...] = (1,),
    sources: tuple[str, ...] = (_NFLVERSE,),
    dtype: DType = pl.Float64,
    positions: tuple[str, ...] = ALL_CORE_POSITIONS,
    missing: str = "missing when the player has no qualifying prior-season rows",
    indicator: str | None = None,
    minimum_denominator: int | None = None,
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=dtype,
        unit=unit,
        definition=definition,
        availability=Availability.SEASON_LAGGED,
        family=family,
        sources=sources,
        lookback_seasons=offsets,
        positions=positions,
        missing_semantics=missing,
        missingness_indicator=indicator,
        minimum_denominator=minimum_denominator,
    )


def _static(
    name: str,
    definition: str,
    *,
    unit: str,
    family: str,
    dtype: DType = pl.Float64,
    missing: str,
    indicator: str | None = None,
    role: FeatureRole = FeatureRole.FEATURE,
) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=dtype,
        unit=unit,
        definition=definition,
        availability=Availability.STATIC_BIOGRAPHICAL,
        family=family,
        sources=(_NFLVERSE,),
        role=role,
        missing_semantics=missing,
        missingness_indicator=indicator,
    )


def _indicator(name: str, definition: str, family: str) -> FeatureSpec:
    return FeatureSpec(
        name=name,
        dtype=pl.Boolean,
        unit="boolean",
        definition=definition,
        availability=Availability.ANCHOR_DERIVED,
        family=family,
        sources=(_NFLVERSE,),
        role=FeatureRole.INDICATOR,
        missing_semantics="never missing; this column *is* the missingness statement",
        nullable=False,
    )


# --------------------------------------------------------------------------------------
# The dictionary
# --------------------------------------------------------------------------------------

_KEYS_AND_ANCHOR: tuple[FeatureSpec, ...] = (
    _key("season", pl.Int32, "Target season the row predicts"),
    _key("player_id", pl.String, "Canonical namespaced player key (ADR-019)"),
    FeatureSpec(
        name="anchor_at_utc",
        dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
        unit="timestamp",
        definition="Draft-time anchor instant for this season (ADR-021)",
        availability=Availability.ANCHOR_METADATA,
        family="anchor",
        role=FeatureRole.ANCHOR,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="feature_cutoff_rule_version",
        dtype=pl.String,
        unit="version",
        definition="Version of the anchor rule that produced anchor_at_utc",
        availability=Availability.ANCHOR_METADATA,
        family="anchor",
        role=FeatureRole.ANCHOR,
        sources=(),
        missing_semantics="never missing",
        nullable=False,
    ),
)

_DESCRIPTIVE: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="gsis_id",
        dtype=pl.String,
        unit="identifier",
        definition="nflverse GSIS id behind player_id",
        availability=Availability.ANCHOR_METADATA,
        family="identity",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="display_name",
        dtype=pl.String,
        unit="text",
        definition="Human-readable name, for inspection only; never a join key (ADR-005)",
        availability=Availability.STATIC_BIOGRAPHICAL,
        family="identity",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="position",
        dtype=pl.String,
        unit="category",
        definition=(
            "Position at the anchor, taken from prior-season roster, the target season's "
            "draft class, or a pre-anchor depth snapshot - never from target-season play"
        ),
        availability=Availability.PRESEASON_UNIVERSE,
        family="identity",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        missing_semantics="never missing; a row without an anchor-safe position is excluded",
        nullable=False,
    ),
    FeatureSpec(
        name="position_source",
        dtype=pl.String,
        unit="category",
        definition="Which anchor-safe evidence supplied `position`",
        availability=Availability.PRESEASON_UNIVERSE,
        family="identity",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="eligibility_basis",
        dtype=pl.String,
        unit="category",
        definition=(
            "Pipe-joined anchor-safe evidence that put the player in the preseason universe: "
            "prior_season_roster, draft_class, depth_snapshot_pre_anchor (ADR-021)"
        ),
        availability=Availability.PRESEASON_UNIVERSE,
        family="eligibility",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="universe_era",
        dtype=pl.String,
        unit="category",
        definition=(
            "Whether the season's universe could also draw on pre-anchor depth snapshots "
            "(`snapshot_2025_plus`) or only on lagged evidence (`lagged_only`)"
        ),
        availability=Availability.PRESEASON_UNIVERSE,
        family="eligibility",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="team_at_anchor",
        dtype=pl.String,
        unit="category",
        definition=(
            "Team as observed before the anchor. Only a pre-anchor depth snapshot (2025+) "
            "or the drafting team of a target-season rookie can supply it; free-agent and "
            "trade movement is unobservable pre-2025, so it is null there"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="team_context",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        missing_semantics="null when no pre-anchor team observation exists for the season",
        missingness_indicator="team_at_anchor_known",
    ),
    FeatureSpec(
        name="team_at_anchor_source",
        dtype=pl.String,
        unit="category",
        definition=(
            "depth_snapshot_pre_anchor | draft_team | unavailable - the evidence behind "
            "team_at_anchor"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="team_context",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="depth_context_state",
        dtype=pl.String,
        unit="category",
        definition=(
            "ADR-018 three-state contract: depth_observed_at_anchor (a real pre-anchor "
            "snapshot), prior_season_role_proxy (a lagged usage-derived role estimate), "
            "depth_unavailable (no depth context at all)"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="depth",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="never missing",
        nullable=False,
    ),
    FeatureSpec(
        name="depth_observed_at_utc",
        dtype=pl.Datetime(time_unit="us", time_zone="UTC"),
        unit="timestamp",
        definition=(
            "Observation time of the depth snapshot behind depth_rank_at_anchor. The "
            "leakage suite asserts this is <= anchor_at_utc on every row that has it"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="depth",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE,),
        missing_semantics="null unless depth_context_state is depth_observed_at_anchor",
    ),
    FeatureSpec(
        name="max_lagged_source_season",
        dtype=pl.Int32,
        unit="season",
        definition=(
            "Newest source season any season-lagged feature on this row consumed. The "
            "leakage suite asserts it is strictly less than `season`"
        ),
        availability=Availability.SEASON_LAGGED,
        family="lineage",
        role=FeatureRole.LINEAGE,
        sources=(_NFLVERSE, _FFOPPORTUNITY),
        lookback_seasons=(1, 2, 3),
        missing_semantics="null for a player with no prior-season data at all",
    ),
    FeatureSpec(
        name="prev1_team",
        dtype=pl.String,
        unit="category",
        definition="Primary team in the previous season, by games played",
        availability=Availability.SEASON_LAGGED,
        family="team_context",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        lookback_seasons=(1,),
        missing_semantics="null when the player recorded no previous-season game",
    ),
)

_CAREER_CONTEXT: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="age_at_anchor",
        dtype=pl.Float64,
        unit="years",
        definition="(anchor_at_utc - birth_date) / 365.25",
        availability=Availability.ANCHOR_DERIVED,
        family="career",
        sources=(_NFLVERSE,),
        missing_semantics="null when nflverse publishes no birth date",
        missingness_indicator="age_at_anchor_known",
    ),
    _indicator("age_at_anchor_known", "Whether a birth date was available", "career"),
    FeatureSpec(
        name="position_age_z",
        dtype=pl.Float64,
        unit="z-score",
        definition="age_at_anchor standardized within (season, position) over eligible rows",
        availability=Availability.ANCHOR_DERIVED,
        family="career",
        sources=(_NFLVERSE,),
        missing_semantics="null when age_at_anchor is null or the cohort has no spread",
    ),
    FeatureSpec(
        name="experience_years",
        dtype=pl.Int32,
        unit="seasons",
        definition=(
            "Completed NFL seasons before the target season: the previous season's roster "
            "`years_exp` plus one, or 0 for a rookie. Never from the target season's "
            "roster, whose value postdates the anchor"
        ),
        availability=Availability.SEASON_LAGGED,
        family="career",
        sources=(_NFLVERSE,),
        lookback_seasons=(1,),
        missing_semantics=(
            "null when the player was on the previous season's roster but nflverse "
            "published no `years_exp` for him - 510 rows of the 2016 roster are like this. "
            "Missing experience is recorded as missing rather than imputed as zero, which "
            "would misclassify an established player as a rookie"
        ),
        missingness_indicator="experience_years_known",
    ),
    _indicator(
        "experience_years_known",
        "True when a previous-season experience count was published",
        "career",
    ),
    _indicator(
        "rookie_flag",
        "True when no pre-anchor evidence shows the player in the NFL before this season - "
        "no previous-season roster row and no prior-window stat line. Derived from evidence "
        "of prior existence rather than from experience_years, which can itself be missing",
        "career",
    ),
    _indicator(
        "has_prior_season_stats",
        "True when the player recorded at least one previous-season regular-season row",
        "career",
    ),
    _static(
        "height_in",
        "Listed height in inches",
        unit="inches",
        family="athletic",
        missing="null when neither the player master nor the combine publishes a height",
    ),
    _static(
        "weight_lb",
        "Listed weight in pounds",
        unit="pounds",
        family="athletic",
        missing="null when neither the player master nor the combine publishes a weight",
    ),
)

_DRAFT_ATHLETIC: tuple[FeatureSpec, ...] = (
    _static(
        "draft_year",
        "Season of the NFL draft the player was selected in",
        unit="season",
        family="draft",
        dtype=pl.Int32,
        missing="null for an undrafted player",
        indicator="drafted_flag",
    ),
    _static(
        "draft_round",
        "Draft round, 1-7",
        unit="round",
        family="draft",
        dtype=pl.Int32,
        missing="null for an undrafted player; missingness is informative, not imputable",
        indicator="drafted_flag",
    ),
    _static(
        "draft_overall",
        "Overall draft pick number",
        unit="pick",
        family="draft",
        dtype=pl.Int32,
        missing="null for an undrafted player",
        indicator="drafted_flag",
    ),
    _indicator("drafted_flag", "True when the player appears in an NFL draft class", "draft"),
    FeatureSpec(
        name="draft_team",
        dtype=pl.String,
        unit="category",
        definition="Team that drafted the player",
        availability=Availability.STATIC_BIOGRAPHICAL,
        family="draft",
        role=FeatureRole.CONTEXT,
        sources=(_NFLVERSE,),
        missing_semantics="null for an undrafted player",
    ),
    FeatureSpec(
        name="seasons_since_draft",
        dtype=pl.Int32,
        unit="seasons",
        definition="season - draft_year",
        availability=Availability.ANCHOR_DERIVED,
        family="draft",
        sources=(_NFLVERSE,),
        missing_semantics="null for an undrafted player",
    ),
    _static(
        "combine_forty",
        "Combine 40-yard dash, seconds",
        unit="seconds",
        family="athletic",
        missing="null when the player has no combine observation; never imputed",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_bench",
        "Combine bench-press repetitions",
        unit="reps",
        family="athletic",
        missing="null when not measured",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_vertical",
        "Combine vertical jump, inches",
        unit="inches",
        family="athletic",
        missing="null when not measured",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_broad_jump",
        "Combine broad jump, inches",
        unit="inches",
        family="athletic",
        missing="null when not measured",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_cone",
        "Combine three-cone drill, seconds",
        unit="seconds",
        family="athletic",
        missing="null when not measured",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_shuttle",
        "Combine 20-yard shuttle, seconds",
        unit="seconds",
        family="athletic",
        missing="null when not measured",
        indicator="combine_observed_flag",
    ),
    _static(
        "combine_speed_score",
        "weight_lb * 200 / combine_forty**4 - a transparent, reproducible size-speed index",
        unit="index",
        family="athletic",
        missing="null unless both a combine forty and a weight exist",
        indicator="combine_observed_flag",
    ),
    _indicator(
        "combine_observed_flag",
        "True when the player has at least one combine measurement",
        "athletic",
    ),
)

_DEPTH_ROLE: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="depth_rank_at_anchor",
        dtype=pl.Int32,
        unit="rank",
        definition=(
            "Positional depth rank from the latest depth-chart snapshot with "
            "`observed_at <= anchor`. Available from 2025 only; ADR-018 forbids using a "
            "week-1 depth chart as a preseason proxy, and no rank is ever fabricated"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="depth",
        sources=(_NFLVERSE,),
        missing_semantics=(
            "null whenever depth_context_state is not depth_observed_at_anchor; the state "
            "column, not an imputed value, carries the meaning"
        ),
        missingness_indicator="depth_rank_observed",
    ),
    _indicator(
        "depth_rank_observed",
        "True when depth_rank_at_anchor came from a real pre-anchor snapshot",
        "depth",
    ),
    _lagged(
        "prior_season_role_rank",
        (
            "Rank within (previous season, previous team, position) by previous-season "
            "offensive snaps - the ADR-018 lagged stand-in for a depth rank"
        ),
        unit="rank",
        family="depth",
        dtype=pl.Int32,
        missing="null when the player has no previous-season snap-count rows",
        indicator="prior_season_role_known",
    ),
    _indicator(
        "prior_season_role_known",
        "True when a prior-season role proxy could be computed",
        "depth",
    ),
    _lagged(
        "prev1_snap_share",
        "Mean share of team offensive snaps across previous-season games played",
        unit="share",
        family="opportunity",
        missing="null without previous-season snap-count rows",
    ),
    _lagged(
        "prev1_offense_snaps_pg",
        "Previous-season offensive snaps per game played",
        unit="snaps/game",
        family="opportunity",
        missing="null without previous-season snap-count rows",
    ),
)

_OPPORTUNITY: tuple[FeatureSpec, ...] = (
    _lagged(
        "prev1_games",
        "Previous-season games with a recorded regular-season stat line, inside the horizon",
        unit="games",
        family="durability",
        dtype=pl.Int32,
        missing="null when the player recorded no previous-season game",
    ),
    _lagged(
        "prev1_team_games",
        "Games the player's previous-season primary team played inside the fantasy horizon",
        unit="games",
        family="durability",
        dtype=pl.Int32,
        missing="null when no previous-season team is known",
    ),
    _lagged(
        "prev1_games_missed",
        "max(0, prev1_team_games - prev1_games) - games the player's team played without him",
        unit="games",
        family="durability",
        dtype=pl.Int32,
        missing="null when either component is missing",
    ),
    _lagged(
        "prev1_fantasy_points_std",
        "Previous-season fantasy points under standard scoring, over the fantasy horizon",
        unit="points",
        family="production",
    ),
    _lagged(
        "prev1_fantasy_points_ppr",
        "Previous-season fantasy points under full PPR, over the fantasy horizon",
        unit="points",
        family="production",
    ),
    _lagged(
        "prev1_fantasy_ppg_std",
        "prev1_fantasy_points_std / prev1_games",
        unit="points/game",
        family="production",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_fantasy_ppg_ppr",
        "prev1_fantasy_points_ppr / prev1_games. Half-PPR is the exact mean of the two",
        unit="points/game",
        family="production",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_carries_pg",
        "Previous-season carries per game",
        unit="carries/game",
        family="opportunity",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_targets_pg",
        "Previous-season targets per game",
        unit="targets/game",
        family="opportunity",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_receptions_pg",
        "Previous-season receptions per game",
        unit="rec/game",
        family="opportunity",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_pass_attempts_pg",
        "Previous-season pass attempts per game",
        unit="attempts/game",
        family="opportunity",
        positions=("QB",),
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_rushing_yards_pg",
        "Previous-season rushing yards per game",
        unit="yards/game",
        family="production",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_receiving_yards_pg",
        "Previous-season receiving yards per game",
        unit="yards/game",
        family="production",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_passing_yards_pg",
        "Previous-season passing yards per game",
        unit="yards/game",
        family="production",
        positions=("QB",),
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_total_tds_pg",
        "Previous-season rushing + receiving touchdowns per game",
        unit="tds/game",
        family="production",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_target_share",
        "Player targets divided by his teams' targets across the games he played",
        unit="share",
        family="opportunity",
        missing="null when the player's teams recorded no targets in his games",
    ),
    _lagged(
        "prev1_rush_share",
        "Player carries divided by his teams' carries across the games he played",
        unit="share",
        family="opportunity",
        missing="null when the player's teams recorded no carries in his games",
    ),
    _lagged(
        "prev1_xfp_pg",
        (
            "Previous-season expected fantasy points per game from ffopportunity, on that "
            "project's own scoring convention. Used as a relative opportunity measure, "
            "never as a label"
        ),
        unit="expected points/game",
        family="opportunity",
        sources=(_FFOPPORTUNITY,),
        missing="null when ffopportunity has no previous-season rows for the player",
        minimum_denominator=1,
    ),
    _lagged(
        "prev1_fp_over_expected_pg",
        "Previous-season actual minus expected fantasy points per game (ffopportunity)",
        unit="points/game",
        family="efficiency",
        sources=(_FFOPPORTUNITY,),
        missing="null when ffopportunity has no previous-season rows for the player",
        minimum_denominator=1,
    ),
)

_EFFICIENCY: tuple[FeatureSpec, ...] = (
    _lagged(
        "prev1_yards_per_carry",
        "Previous-season rushing yards / carries",
        unit="yards/carry",
        family="efficiency",
        missing="null below the minimum denominator; an unstable ratio is worse than a gap",
        indicator="prev1_rush_denominator_met",
        minimum_denominator=20,
    ),
    _indicator(
        "prev1_rush_denominator_met",
        "True when previous-season carries met the minimum for a stable rushing ratio",
        "efficiency",
    ),
    _lagged(
        "prev1_yards_per_target",
        "Previous-season receiving yards / targets",
        unit="yards/target",
        family="efficiency",
        missing="null below the minimum denominator",
        indicator="prev1_target_denominator_met",
        minimum_denominator=20,
    ),
    _lagged(
        "prev1_catch_rate",
        "Previous-season receptions / targets",
        unit="rate",
        family="efficiency",
        missing="null below the minimum denominator",
        indicator="prev1_target_denominator_met",
        minimum_denominator=20,
    ),
    _lagged(
        "prev1_rec_td_rate",
        "Previous-season receiving touchdowns / targets",
        unit="rate",
        family="efficiency",
        missing="null below the minimum denominator",
        indicator="prev1_target_denominator_met",
        minimum_denominator=20,
    ),
    _indicator(
        "prev1_target_denominator_met",
        "True when previous-season targets met the minimum for a stable receiving ratio",
        "efficiency",
    ),
    _lagged(
        "prev1_rush_td_rate",
        "Previous-season rushing touchdowns / carries",
        unit="rate",
        family="efficiency",
        missing="null below the minimum denominator",
        indicator="prev1_rush_denominator_met",
        minimum_denominator=20,
    ),
    _lagged(
        "prev1_yards_per_attempt",
        "Previous-season passing yards / pass attempts",
        unit="yards/attempt",
        family="efficiency",
        positions=("QB",),
        missing="null below the minimum denominator",
        indicator="prev1_pass_denominator_met",
        minimum_denominator=100,
    ),
    _lagged(
        "prev1_completion_pct",
        "Previous-season completions / pass attempts",
        unit="rate",
        family="efficiency",
        positions=("QB",),
        missing="null below the minimum denominator",
        indicator="prev1_pass_denominator_met",
        minimum_denominator=100,
    ),
    _lagged(
        "prev1_pass_td_rate",
        "Previous-season passing touchdowns / pass attempts",
        unit="rate",
        family="efficiency",
        positions=("QB",),
        missing="null below the minimum denominator",
        indicator="prev1_pass_denominator_met",
        minimum_denominator=100,
    ),
    _lagged(
        "prev1_interception_rate",
        "Previous-season interceptions / pass attempts",
        unit="rate",
        family="efficiency",
        positions=("QB",),
        missing="null below the minimum denominator",
        indicator="prev1_pass_denominator_met",
        minimum_denominator=100,
    ),
    _indicator(
        "prev1_pass_denominator_met",
        "True when previous-season pass attempts met the minimum for a stable passing ratio",
        "efficiency",
    ),
)

_DEEPER_LAGS: tuple[FeatureSpec, ...] = tuple(
    spec
    for offset in (2, 3)
    for spec in (
        _lagged(
            f"prev{offset}_games",
            f"Games played {offset} seasons before the target season",
            unit="games",
            family="durability",
            dtype=pl.Int32,
            offsets=(offset,),
        ),
        _lagged(
            f"prev{offset}_fantasy_ppg_ppr",
            f"Full-PPR points per game {offset} seasons before the target season",
            unit="points/game",
            family="production",
            offsets=(offset,),
            minimum_denominator=1,
        ),
        _lagged(
            f"prev{offset}_carries_pg",
            f"Carries per game {offset} seasons before the target season",
            unit="carries/game",
            family="opportunity",
            offsets=(offset,),
            minimum_denominator=1,
        ),
        _lagged(
            f"prev{offset}_targets_pg",
            f"Targets per game {offset} seasons before the target season",
            unit="targets/game",
            family="opportunity",
            offsets=(offset,),
            minimum_denominator=1,
        ),
        _lagged(
            f"prev{offset}_xfp_pg",
            f"Expected fantasy points per game {offset} seasons before the target season",
            unit="expected points/game",
            family="opportunity",
            offsets=(offset,),
            sources=(_FFOPPORTUNITY,),
        ),
    )
)

#: Prior-season window for the "career" aggregates. Fixed at five seasons so the quantity
#: means the same thing for every target season: a genuine career total would cover three
#: prior seasons for the earliest target row and fourteen for the latest, which is a
#: different feature wearing one name.
CAREER_LOOKBACK_SEASONS: tuple[int, ...] = (1, 2, 3, 4, 5)

_CAREER_AGGREGATES: tuple[FeatureSpec, ...] = (
    _lagged(
        "prior5_seasons",
        "Prior seasons, within the fixed five-season window, with at least one "
        "regular-season stat line",
        unit="seasons",
        family="career",
        dtype=pl.Int32,
        offsets=CAREER_LOOKBACK_SEASONS,
        missing="0 for a player with no prior stat line in the window",
    ),
    _lagged(
        "prior5_games",
        "Games played across the fixed five-season prior window",
        unit="games",
        family="career",
        dtype=pl.Int32,
        offsets=CAREER_LOOKBACK_SEASONS,
        missing="0 for a player with no prior stat line in the window",
    ),
    _lagged(
        "prior5_fantasy_ppg_ppr",
        "Full-PPR points per game across the fixed five-season prior window",
        unit="points/game",
        family="career",
        offsets=CAREER_LOOKBACK_SEASONS,
        minimum_denominator=1,
    ),
    _lagged(
        "prior5_carries_pg",
        "Carries per game across the fixed five-season prior window",
        unit="carries/game",
        family="career",
        offsets=CAREER_LOOKBACK_SEASONS,
        minimum_denominator=1,
    ),
    _lagged(
        "prior5_targets_pg",
        "Targets per game across the fixed five-season prior window",
        unit="targets/game",
        family="career",
        offsets=CAREER_LOOKBACK_SEASONS,
        minimum_denominator=1,
    ),
    _lagged(
        "recent3_fantasy_ppg_ppr_w",
        "Recency-weighted full-PPR points per game over prev1/prev2/prev3 with weights "
        "0.6/0.3/0.1, renormalized over the seasons actually present",
        unit="points/game",
        family="career",
        offsets=(1, 2, 3),
    ),
    _lagged(
        "recent3_targets_pg_w",
        "Recency-weighted targets per game over prev1/prev2/prev3 (0.6/0.3/0.1)",
        unit="targets/game",
        family="career",
        offsets=(1, 2, 3),
    ),
    _lagged(
        "recent3_carries_pg_w",
        "Recency-weighted carries per game over prev1/prev2/prev3 (0.6/0.3/0.1)",
        unit="carries/game",
        family="career",
        offsets=(1, 2, 3),
    ),
)


_TEAM_CONTEXT: tuple[FeatureSpec, ...] = (
    _lagged(
        "prev1_team_pass_attempts_pg",
        "Previous-season pass attempts per game by the player's primary previous team",
        unit="attempts/game",
        family="team_context",
    ),
    _lagged(
        "prev1_team_carries_pg",
        "Previous-season carries per game by the player's primary previous team",
        unit="carries/game",
        family="team_context",
    ),
    _lagged(
        "prev1_team_pass_yards_pg",
        "Previous-season passing yards per game by the player's primary previous team",
        unit="yards/game",
        family="team_context",
    ),
    _lagged(
        "prev1_team_rush_yards_pg",
        "Previous-season rushing yards per game by the player's primary previous team",
        unit="yards/game",
        family="team_context",
    ),
    _lagged(
        "prev1_team_offense_tds_pg",
        "Previous-season passing + rushing + receiving touchdowns per game by the player's "
        "primary previous team (receiving and passing touchdowns are the same scores, so "
        "only passing and rushing are summed)",
        unit="tds/game",
        family="team_context",
    ),
    FeatureSpec(
        name="team_change_flag",
        dtype=pl.Boolean,
        unit="boolean",
        definition=(
            "True when team_at_anchor differs from prev1_team. Computable only where a "
            "pre-anchor team observation exists, which pre-2025 means rookies alone"
        ),
        availability=Availability.PRE_ANCHOR_OBSERVATION,
        family="team_context",
        sources=(_NFLVERSE,),
        missing_semantics=(
            "null when no pre-anchor team observation exists; free agency and trades are "
            "unobservable before the 2025 snapshot era, and guessing would leak or lie"
        ),
        missingness_indicator="team_change_known",
    ),
    _indicator(
        "team_at_anchor_known",
        "True when a pre-anchor team observation exists for this row",
        "team_context",
    ),
    _indicator(
        "team_change_known",
        "True when both team_at_anchor and prev1_team were available",
        "team_context",
    ),
)

FEATURE_DICTIONARY: tuple[FeatureSpec, ...] = (
    *_KEYS_AND_ANCHOR,
    *_DESCRIPTIVE,
    *_CAREER_CONTEXT,
    *_DRAFT_ATHLETIC,
    *_DEPTH_ROLE,
    *_OPPORTUNITY,
    *_EFFICIENCY,
    *_DEEPER_LAGS,
    *_CAREER_AGGREGATES,
    *_TEAM_CONTEXT,
)


def _validate_dictionary(specs: Sequence[FeatureSpec]) -> None:
    names = [spec.name for spec in specs]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate feature names in the dictionary: {duplicates}")
    known = set(names)
    for spec in specs:
        if spec.missingness_indicator and spec.missingness_indicator not in known:
            raise ValueError(
                f"{spec.name}: declares missingness indicator "
                f"{spec.missingness_indicator!r}, which is not a declared column",
            )


_validate_dictionary(FEATURE_DICTIONARY)


HISTORICAL_FEATURE_CONTRACT = FrameContract(
    contract_id="historical_features",
    version="1.0",
    primary_key=("season", "player_id"),
    columns=tuple(spec.column for spec in FEATURE_DICTIONARY),
)


FANTASY_LABEL_CONTRACT = FrameContract(
    contract_id="historical_fantasy_labels",
    version="1.0",
    primary_key=("season", "player_id", "scoring_preset"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("player_id", pl.String, nullable=False),
        ColumnSpec("scoring_preset", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False),
        ColumnSpec("actual_fantasy_points", pl.Float64, nullable=False),
        ColumnSpec("actual_games_played", pl.Int32, nullable=False),
        ColumnSpec("actual_points_per_game", pl.Float64),
        ColumnSpec("actual_positional_rank", pl.Int32, nullable=False),
        ColumnSpec("horizon_first_week", pl.Int32, nullable=False),
        ColumnSpec("horizon_last_week", pl.Int32, nullable=False),
        ColumnSpec("scoring_engine_version", pl.String, nullable=False),
    ),
)


VORP_LABEL_CONTRACT = FrameContract(
    contract_id="historical_vorp_labels",
    version="1.0",
    primary_key=("season", "player_id", "scoring_preset", "league_preset_id"),
    columns=(
        ColumnSpec("season", pl.Int32, nullable=False),
        ColumnSpec("player_id", pl.String, nullable=False),
        ColumnSpec("scoring_preset", pl.String, nullable=False),
        ColumnSpec("league_preset_id", pl.String, nullable=False),
        ColumnSpec("position", pl.String, nullable=False),
        ColumnSpec("actual_fantasy_points", pl.Float64, nullable=False),
        ColumnSpec("replacement_points", pl.Float64),
        ColumnSpec("replacement_player_id", pl.String),
        ColumnSpec("actual_vorp", pl.Float64),
        ColumnSpec("actual_vorp_rank", pl.Int32),
        ColumnSpec("started_flag", pl.Boolean, nullable=False),
        ColumnSpec("quality_flags", pl.String),
    ),
)


# --------------------------------------------------------------------------------------
# Queries over the dictionary
# --------------------------------------------------------------------------------------


def spec_for(name: str) -> FeatureSpec:
    for spec in FEATURE_DICTIONARY:
        if spec.name == name:
            return spec
    raise KeyError(f"{name!r} is not a declared feature")


def intrinsic_feature_names() -> tuple[str, ...]:
    """Columns offered to the intrinsic estimator; the forbidden-feature audit runs on these."""
    return tuple(spec.name for spec in FEATURE_DICTIONARY if spec.role.is_model_input)


def feature_lineage() -> dict[str, tuple[str, ...]]:
    """Feature name -> contributing source ids, for the lineage audit."""
    return {spec.name: spec.sources for spec in FEATURE_DICTIONARY if spec.role.is_model_input}


def specs_by_availability(availability: Availability) -> tuple[FeatureSpec, ...]:
    return tuple(spec for spec in FEATURE_DICTIONARY if spec.availability is availability)


def lagged_feature_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in specs_by_availability(Availability.SEASON_LAGGED))


def timestamped_feature_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in specs_by_availability(Availability.PRE_ANCHOR_OBSERVATION))


def feature_names_by_family() -> dict[str, tuple[str, ...]]:
    families: dict[str, list[str]] = {}
    for spec in FEATURE_DICTIONARY:
        families.setdefault(spec.family, []).append(spec.name)
    return {family: tuple(names) for family, names in sorted(families.items())}


def to_records(specs: Iterable[FeatureSpec] = FEATURE_DICTIONARY) -> list[dict[str, object]]:
    return [spec.to_record() for spec in specs]


def feature_schema_hash() -> str:
    """Stable hash of the column contract, recorded in the build manifest.

    A model artifact trained against one schema must refuse to run against another
    (`docs/ARCHITECTURE.md` section 7); this is the value it compares.
    """
    import hashlib
    import json

    payload = json.dumps(
        [
            {
                "name": spec.name,
                "dtype": str(spec.dtype),
                "role": str(spec.role),
                "availability": str(spec.availability),
                "lookback_seasons": list(spec.lookback_seasons),
            }
            for spec in FEATURE_DICTIONARY
        ],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def dictionary_markdown() -> str:
    """Render the dictionary as the Markdown table `docs/MODELING.md` links to."""
    header = (
        "| Feature | Family | Role | Type | Unit | Sources | Availability | Lookback | "
        "Missing semantics | Indicator | Intrinsic |"
    )
    divider = "|" + "|".join(["---"] * 11) + "|"
    lines = [header, divider]
    for spec in FEATURE_DICTIONARY:
        lookback = ", ".join(f"-{offset}" for offset in spec.lookback_seasons) or "-"
        lines.append(
            f"| `{spec.name}` | {spec.family} | {spec.role} | {spec.dtype} | {spec.unit} | "
            f"{', '.join(spec.sources) or '-'} | {spec.availability} | {lookback} | "
            f"{spec.missing_semantics} | "
            f"{f'`{spec.missingness_indicator}`' if spec.missingness_indicator else '-'} | "
            f"{'yes' if spec.allowed_in_intrinsic else 'no'} |",
        )
    return "\n".join(lines)


def positions_for(name: str) -> tuple[str, ...]:
    return spec_for(name).positions


def dictionary_by_name() -> Mapping[str, FeatureSpec]:
    return {spec.name: spec for spec in FEATURE_DICTIONARY}
