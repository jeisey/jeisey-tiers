"""Assembly of the historical feature table.

This is where the anchor, the preseason universe and the lagged aggregates meet. The shape
of the code follows the shape of the leakage argument:

1. derive the season's anchor (:mod:`ffdraft.anchors`);
2. build the eligible rows from pre-anchor evidence only
   (:mod:`ffdraft.features.eligibility`);
3. attach aggregates keyed on ``season - k`` for ``k >= 1``
   (:mod:`ffdraft.features.lagged`);
4. attach static biography, draft capital and combine measurements;
5. attach the ADR-018 depth context;
6. derive the anchor-relative quantities (age, experience, team change).

No step reads a target-season source. The only target-season inputs anywhere in the module
are the schedule - whose Week-1 date is published in May and is not an outcome - and, from
2025, depth-chart snapshots explicitly filtered to ``observed_at <= anchor``.

Every row carries the provenance the leakage suite checks: ``anchor_at_utc``,
``feature_cutoff_rule_version``, ``max_lagged_source_season``, ``depth_observed_at_utc``,
``eligibility_basis`` and ``depth_context_state``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import polars as pl

from ffdraft.anchors import SeasonAnchor, build_season_anchors
from ffdraft.config import AppConfig
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.features.dictionary import (
    CAREER_LOOKBACK_SEASONS,
    HISTORICAL_FEATURE_CONTRACT,
)
from ffdraft.features.eligibility import (
    DepthContextState,
    EligibilityBasis,
    PreseasonUniverse,
    TeamAtAnchorSource,
    build_preseason_universe,
    depth_context_state,
)
from ffdraft.features.lagged import (
    PASS_ATTEMPT_MINIMUM,
    RUSH_ATTEMPT_MINIMUM,
    TARGET_MINIMUM,
    expected_points_by_season,
    player_season_usage,
    role_rank_by_season,
    snap_usage_by_season,
    team_games_by_season,
    team_season_context,
)
from ffdraft.identity.ids import IdNamespace, make_player_id

__all__ = [
    "DEEP_LAG_OFFSETS",
    "RECENCY_WEIGHTS",
    "FeatureBuildResult",
    "HistoricalSources",
    "build_feature_table",
    "pfr_to_gsis_bridge",
]

#: Lag offsets carried as their own light feature block, beyond the detailed prev1 block.
DEEP_LAG_OFFSETS: tuple[int, ...] = (2, 3)

#: Weights for the ``recent3_*_w`` features, renormalized over the seasons present.
RECENCY_WEIGHTS: tuple[float, ...] = (0.6, 0.3, 0.1)

_DAYS_PER_YEAR = 365.25
_SPEED_SCORE_CONSTANT = 200.0


@dataclass(frozen=True, slots=True)
class HistoricalSources:
    """Normalized source frames the builder consumes.

    ``rosters`` and ``depth_charts`` are keyed by season because both are season-scoped
    upstream, and because keeping rosters per season makes the "previous season only" rule
    a dictionary lookup rather than a filter somebody could forget.
    """

    weekly_stats: pl.DataFrame
    schedule: pl.DataFrame
    rosters: Mapping[int, pl.DataFrame]
    depth_charts: Mapping[int, pl.DataFrame]
    snap_counts: pl.DataFrame
    expected_points: pl.DataFrame
    draft_picks: pl.DataFrame
    combine: pl.DataFrame
    player_master: pl.DataFrame


@dataclass
class FeatureBuildResult:
    """The feature table plus everything a quality report needs to explain it."""

    features: pl.DataFrame
    anchors: dict[int, SeasonAnchor]
    universes: list[PreseasonUniverse]
    exclusions: pl.DataFrame
    checks: list[QualityCheck] = field(default_factory=list)

    @property
    def seasons(self) -> tuple[int, ...]:
        return tuple(sorted(self.anchors))


def pfr_to_gsis_bridge(
    player_master: pl.DataFrame,
    rosters: Mapping[int, pl.DataFrame],
) -> dict[str, str]:
    """Map ``pfr_id -> gsis_id`` from nflverse's own data.

    Both the player master and the season rosters publish the pair, so the bridge is built
    from the union and any PFR id claiming two different GSIS ids is dropped entirely -
    the same fail-closed rule ADR-019 applies to market bridges. A poisoned key silently
    attaching one player's snaps to another is exactly the corruption id hygiene exists to
    prevent.
    """
    pairs: dict[str, set[str]] = {}

    def absorb(frame: pl.DataFrame) -> None:
        if frame.is_empty() or "pfr_id" not in frame.columns:
            return
        for pfr, gsis in frame.select("pfr_id", "gsis_id").drop_nulls().iter_rows():
            pairs.setdefault(str(pfr), set()).add(str(gsis))

    absorb(player_master)
    for frame in rosters.values():
        absorb(frame)
    return {pfr: next(iter(gsis)) for pfr, gsis in pairs.items() if len(gsis) == 1}


def _prefixed(frame: pl.DataFrame, prefix: str, *, keep: Sequence[str]) -> pl.DataFrame:
    """Select ``keep`` and prefix every non-key column."""
    return frame.select(
        [pl.col("gsis_id"), *[pl.col(name).alias(f"{prefix}{name}") for name in keep]],
    )


def _ratio(numerator: str, denominator: str, *, minimum: float) -> pl.Expr:
    denom = pl.col(denominator).cast(pl.Float64)
    return (
        pl.when(denom.is_null() | (denom < minimum))
        .then(None)
        .otherwise(pl.col(numerator).cast(pl.Float64) / denom)
        .cast(pl.Float64)
    )


def _weighted_recency(columns: Sequence[str]) -> pl.Expr:
    """Recency-weighted mean over the present values of ``columns``."""
    numerator = pl.lit(0.0)
    denominator = pl.lit(0.0)
    for weight, name in zip(RECENCY_WEIGHTS, columns, strict=True):
        present = pl.col(name).is_not_null()
        numerator = numerator + pl.when(present).then(pl.col(name) * weight).otherwise(0.0)
        denominator = denominator + pl.when(present).then(weight).otherwise(0.0)
    return pl.when(denominator > 0).then(numerator / denominator).otherwise(None).cast(pl.Float64)


def build_feature_table(
    sources: HistoricalSources,
    *,
    config: AppConfig,
    seasons: Sequence[int],
    anchors: Mapping[int, SeasonAnchor] | None = None,
) -> FeatureBuildResult:
    """Build the ``(season, player_id)`` feature table.

    ``anchors`` overrides the ADR-021 rule for callers that have a different, *earlier*
    information cutoff. The only such caller is the current-season production build: it runs
    before the target season's anchor has occurred, so its cutoff is the build timestamp and
    it says so with its own rule version (`ffdraft.pipeline.current`). Historical builds pass
    nothing and get the versioned rule.
    """
    checks: list[QualityCheck] = []
    anchors = (
        dict(anchors)
        if anchors is not None
        else build_season_anchors(
            sources.schedule,
            seasons,
        )
    )

    bridge = pfr_to_gsis_bridge(sources.player_master, sources.rosters)
    usage = player_season_usage(sources.weekly_stats, config.league.scoring)
    snaps = snap_usage_by_season(sources.snap_counts, bridge)
    roles = role_rank_by_season(snaps, usage)
    expected = expected_points_by_season(sources.expected_points)
    team_context = team_season_context(sources.weekly_stats, sources.schedule)
    team_games = team_games_by_season(sources.schedule)
    biography = _biography(sources)
    draft = _draft_capital(sources.draft_picks, bridge)
    athletic = _combine_measures(sources.combine, bridge)

    frames: list[pl.DataFrame] = []
    universes: list[PreseasonUniverse] = []
    exclusion_frames: list[pl.DataFrame] = []

    for season in sorted(anchors):
        anchor = anchors[season]
        universe = build_preseason_universe(
            season,
            anchor=anchor,
            prior_roster=sources.rosters.get(season - 1, _empty_like_roster(sources.rosters)),
            draft_picks=sources.draft_picks,
            depth_chart=sources.depth_charts.get(season, _empty_depth()),
            player_master=sources.player_master,
        )
        universes.append(universe)
        exclusion_frames.append(universe.exclusions)
        if universe.members.is_empty():
            checks.append(
                QualityCheck.fail(
                    "features.empty_universe",
                    stage="features",
                    message=f"{season} produced no eligible players",
                    observed="0 rows",
                    expected="> 0",
                ),
            )
            continue
        frames.append(
            _build_one_season(
                universe=universe,
                anchor=anchor,
                usage=usage,
                snaps=snaps,
                roles=roles,
                expected=expected,
                team_context=team_context,
                team_games=team_games,
                biography=biography,
                draft=draft,
                athletic=athletic,
                prior_roster=sources.rosters.get(season - 1, _empty_like_roster(sources.rosters)),
            ),
        )

    features = pl.concat(frames, how="vertical") if frames else HISTORICAL_FEATURE_CONTRACT.empty()
    features = HISTORICAL_FEATURE_CONTRACT.coerce(features).sort(["season", "player_id"])
    checks.extend(HISTORICAL_FEATURE_CONTRACT.validate(features, stage="features"))
    checks.extend(_bridge_coverage_checks(features, usage, snaps, expected))

    exclusions = (
        pl.concat(exclusion_frames, how="vertical")
        if exclusion_frames
        else pl.DataFrame(
            schema={
                "season": pl.Int32,
                "gsis_id": pl.String,
                "reason": pl.String,
                "detail": pl.String,
            },
        )
    )
    return FeatureBuildResult(
        features=features,
        anchors=anchors,
        universes=universes,
        exclusions=exclusions,
        checks=checks,
    )


def _empty_depth() -> pl.DataFrame:
    from ffdraft.contracts import DEPTH_CHART_CONTRACT

    return DEPTH_CHART_CONTRACT.empty()


def _empty_like_roster(rosters: Mapping[int, pl.DataFrame]) -> pl.DataFrame:
    from ffdraft.contracts import ROSTER_CONTRACT

    for frame in rosters.values():
        return frame.clear()
    return ROSTER_CONTRACT.empty()


def _biography(sources: HistoricalSources) -> pl.DataFrame:
    """Static biography from the player master, with rosters filling its gaps.

    ``load_players`` does not cover every player who appears on a season roster - roughly
    seventy skill-position players a season are absent - and it also keys about a quarter of
    its rows by an ESB identifier rather than a GSIS one, which id hygiene correctly refuses
    (ADR-019). Rosters publish the same birth dates and cover exactly the players the
    universe is built from, so they are the natural fallback.

    Only ``birth_date`` is taken from the roster fallback, and that is safe at any anchor
    because a birth date is time-invariant: which season's roster reported it cannot change
    what it says.
    """
    master = sources.player_master.select(
        "gsis_id",
        pl.col("birth_date").alias("master_birth_date"),
        pl.col("height_in").alias("master_height_in"),
        pl.col("weight_lb").alias("master_weight_lb"),
        pl.col("display_name").alias("master_display_name"),
    )
    roster_frames = [
        frame.select("gsis_id", pl.col("birth_date").alias("roster_birth_date"))
        for frame in sources.rosters.values()
        if not frame.is_empty()
    ]
    if roster_frames:
        roster_births = (
            pl.concat(roster_frames, how="vertical")
            .drop_nulls()
            .sort(["gsis_id", "roster_birth_date"])
            .unique(subset=["gsis_id"], keep="first", maintain_order=True)
        )
        merged = master.join(roster_births, on="gsis_id", how="full", coalesce=True)
    else:
        merged = master.with_columns(pl.lit(None, dtype=pl.Date).alias("roster_birth_date"))
    return merged.with_columns(
        pl.coalesce(pl.col("master_birth_date"), pl.col("roster_birth_date")).alias("birth_date"),
    ).drop("master_birth_date", "roster_birth_date")


def _draft_capital(draft_picks: pl.DataFrame, bridge: Mapping[str, str]) -> pl.DataFrame:
    """One draft row per canonical player, resolving PFR-only rows through the bridge."""
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "gsis_id": pl.String,
        "draft_year": pl.Int32,
        "draft_round": pl.Int32,
        "draft_overall": pl.Int32,
        "draft_team": pl.String,
    }
    if draft_picks.is_empty():
        return pl.DataFrame(schema=schema)
    resolved = draft_picks.with_columns(
        pl.coalesce(
            pl.col("gsis_id"),
            pl.col("pfr_id").replace_strict(dict(bridge), default=None, return_dtype=pl.String),
        ).alias("gsis_id"),
    ).filter(pl.col("gsis_id").is_not_null())
    return (
        resolved.select("gsis_id", "draft_year", "draft_round", "draft_overall", "draft_team")
        # A player can appear once per draft; keeping the earliest is defensive against a
        # duplicated upstream row rather than an expected case.
        .sort(["gsis_id", "draft_year", "draft_overall"])
        .unique(subset=["gsis_id"], keep="first", maintain_order=True)
    )


def _combine_measures(combine: pl.DataFrame, bridge: Mapping[str, str]) -> pl.DataFrame:
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "gsis_id": pl.String,
        "combine_height_in": pl.Float64,
        "combine_weight_lb": pl.Float64,
        "combine_forty": pl.Float64,
        "combine_bench": pl.Float64,
        "combine_vertical": pl.Float64,
        "combine_broad_jump": pl.Float64,
        "combine_cone": pl.Float64,
        "combine_shuttle": pl.Float64,
    }
    if combine.is_empty() or not bridge:
        return pl.DataFrame(schema=schema)
    resolved = combine.with_columns(
        pl.col("pfr_id")
        .replace_strict(dict(bridge), default=None, return_dtype=pl.String)
        .alias("gsis_id"),
    ).filter(pl.col("gsis_id").is_not_null())
    if resolved.is_empty():
        return pl.DataFrame(schema=schema)
    return (
        resolved.select(
            "gsis_id",
            pl.col("height_in").alias("combine_height_in"),
            pl.col("weight_lb").alias("combine_weight_lb"),
            "forty",
            "bench",
            "vertical",
            "broad_jump",
            "cone",
            "shuttle",
        )
        .rename(
            {
                "forty": "combine_forty",
                "bench": "combine_bench",
                "vertical": "combine_vertical",
                "broad_jump": "combine_broad_jump",
                "cone": "combine_cone",
                "shuttle": "combine_shuttle",
            },
        )
        .sort("gsis_id")
        .unique(subset=["gsis_id"], keep="first", maintain_order=True)
    )


_PREV1_USAGE_COLUMNS = (
    "games",
    "fantasy_points_STD",
    "fantasy_points_PPR",
    "carries",
    "targets",
    "receptions",
    "rushing_yards",
    "receiving_yards",
    "passing_yards",
    "pass_attempts",
    "completions",
    "passing_tds",
    "interceptions",
    "rushing_tds",
    "receiving_tds",
    "total_tds",
    "target_share",
    "rush_share",
    "primary_team",
)


def _build_one_season(
    *,
    universe: PreseasonUniverse,
    anchor: SeasonAnchor,
    usage: pl.DataFrame,
    snaps: pl.DataFrame,
    roles: pl.DataFrame,
    expected: pl.DataFrame,
    team_context: pl.DataFrame,
    team_games: pl.DataFrame,
    biography: pl.DataFrame,
    draft: pl.DataFrame,
    athletic: pl.DataFrame,
    prior_roster: pl.DataFrame,
) -> pl.DataFrame:
    season = universe.season
    frame = universe.members

    def lag(source: pl.DataFrame, offset: int, prefix: str, keep: Sequence[str]) -> pl.DataFrame:
        if source.is_empty():
            return pl.DataFrame(
                schema={
                    "gsis_id": pl.String,
                    **{f"{prefix}{name}": pl.Float64 for name in keep},
                },
            )
        sliced = source.filter(pl.col("season") == season - offset).drop("season")
        return _prefixed(sliced, prefix, keep=[name for name in keep if name in sliced.columns])

    frame = frame.join(lag(usage, 1, "prev1_", _PREV1_USAGE_COLUMNS), on="gsis_id", how="left")
    frame = frame.join(
        lag(snaps, 1, "prev1_", ("snap_games", "offense_snaps", "snap_share")),
        on="gsis_id",
        how="left",
    )
    frame = frame.join(lag(roles, 1, "prev1_", ("role_rank",)), on="gsis_id", how="left")
    frame = frame.join(
        lag(expected, 1, "prev1_", ("xfp_games", "expected_points", "points_over_expected")),
        on="gsis_id",
        how="left",
    )

    for offset in DEEP_LAG_OFFSETS:
        frame = frame.join(
            lag(
                usage,
                offset,
                f"prev{offset}_",
                ("games", "fantasy_points_PPR", "carries", "targets"),
            ),
            on="gsis_id",
            how="left",
        )
        frame = frame.join(
            lag(expected, offset, f"prev{offset}_", ("xfp_games", "expected_points")),
            on="gsis_id",
            how="left",
        )

    frame = frame.join(_prior_window(usage, season), on="gsis_id", how="left")
    frame = frame.join(_prior_experience(prior_roster), on="gsis_id", how="left")
    frame = frame.join(biography, on="gsis_id", how="left")
    frame = frame.join(draft, on="gsis_id", how="left")
    frame = frame.join(athletic, on="gsis_id", how="left")

    prev_team_context = (
        team_context.filter(pl.col("season") == season - 1)
        .drop("season")
        .rename(
            {
                "team": "prev1_team",
                "team_pass_attempts_pg": "prev1_team_pass_attempts_pg",
                "team_carries_pg": "prev1_team_carries_pg",
                "team_pass_yards_pg": "prev1_team_pass_yards_pg",
                "team_rush_yards_pg": "prev1_team_rush_yards_pg",
                "team_offense_tds_pg": "prev1_team_offense_tds_pg",
            },
        )
    )
    prev_team_games = (
        team_games.filter(pl.col("season") == season - 1)
        .drop("season")
        .rename({"team": "prev1_team", "team_games": "prev1_team_games"})
    )
    frame = frame.rename({"prev1_primary_team": "prev1_team"})
    frame = frame.join(prev_team_context, on="prev1_team", how="left")
    frame = frame.join(prev_team_games, on="prev1_team", how="left")

    return _derive(frame, anchor=anchor)


def _prior_window(usage: pl.DataFrame, season: int) -> pl.DataFrame:
    """Fixed five-season prior aggregates (``prior5_*``)."""
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "gsis_id": pl.String,
        "prior5_seasons": pl.Int32,
        "prior5_games": pl.Int32,
        "prior5_points_ppr": pl.Float64,
        "prior5_carries": pl.Float64,
        "prior5_targets": pl.Float64,
    }
    if usage.is_empty():
        return pl.DataFrame(schema=schema)
    window = [season - offset for offset in CAREER_LOOKBACK_SEASONS]
    scoped = usage.filter(pl.col("season").is_in(window))
    if scoped.is_empty():
        return pl.DataFrame(schema=schema)
    return scoped.group_by("gsis_id").agg(
        pl.len().cast(pl.Int32).alias("prior5_seasons"),
        pl.col("games").sum().cast(pl.Int32).alias("prior5_games"),
        pl.col("fantasy_points_PPR").sum().alias("prior5_points_ppr"),
        pl.col("carries").sum().alias("prior5_carries"),
        pl.col("targets").sum().alias("prior5_targets"),
    )


def _prior_experience(prior_roster: pl.DataFrame) -> pl.DataFrame:
    """Previous-season ``years_exp``, the anchor-safe basis for experience and rookie status."""
    schema: dict[str, pl.DataType | type[pl.DataType]] = {
        "gsis_id": pl.String,
        "prev1_years_exp": pl.Int32,
    }
    if prior_roster.is_empty():
        return pl.DataFrame(schema=schema)
    return (
        prior_roster.select("gsis_id", pl.col("years_exp").alias("prev1_years_exp"))
        .drop_nulls("gsis_id")
        .sort(["gsis_id", "prev1_years_exp"], descending=[False, True], nulls_last=True)
        .unique(subset=["gsis_id"], keep="first", maintain_order=True)
    )


def _derive(frame: pl.DataFrame, *, anchor: SeasonAnchor) -> pl.DataFrame:
    """Compute the anchor-relative and ratio features, then shape to the contract."""
    season = anchor.season
    anchor_date = anchor.anchor_local.date()

    frame = frame.with_columns(
        pl.lit(anchor.anchor_at_utc)
        .cast(pl.Datetime(time_unit="us", time_zone="UTC"))
        .alias("anchor_at_utc"),
        pl.lit(anchor.rule_version).alias("feature_cutoff_rule_version"),
        pl.col("gsis_id")
        .map_elements(
            lambda value: make_player_id(IdNamespace.GSIS, str(value)),
            return_dtype=pl.String,
        )
        .alias("player_id"),
    )

    # ---- career / biography -----------------------------------------------------------
    frame = frame.with_columns(
        pl.when(pl.col("birth_date").is_not_null())
        .then(
            (pl.lit(anchor_date) - pl.col("birth_date")).dt.total_days().cast(pl.Float64)
            / _DAYS_PER_YEAR,
        )
        .otherwise(None)
        .alias("age_at_anchor"),
        pl.coalesce(pl.col("master_height_in"), pl.col("combine_height_in")).alias("height_in"),
        pl.coalesce(pl.col("master_weight_lb"), pl.col("combine_weight_lb")).alias("weight_lb"),
        pl.col("eligibility_basis")
        .str.contains(str(EligibilityBasis.PRIOR_SEASON_ROSTER), literal=True)
        .alias("_on_prior_roster"),
        (pl.col("draft_year").is_not_null()).alias("drafted_flag"),
        (pl.lit(season) - pl.col("draft_year")).cast(pl.Int32).alias("seasons_since_draft"),
    )
    # Rookie status and experience are separate questions, and conflating them was the
    # bug this shape prevents: nflverse left `years_exp` null on 510 rows of the 2016
    # roster, and treating an absent value as zero would have declared 247 established
    # players rookies in 2017. Being on last season's roster is decisive evidence a player
    # is *not* a rookie even when the league's own experience count is missing, so
    # `rookie_flag` is derived from evidence of prior existence and `experience_years` is
    # allowed to be null when nobody published it.
    frame = frame.with_columns(
        (~pl.col("_on_prior_roster") & (pl.col("prior5_seasons").fill_null(0) == 0)).alias(
            "rookie_flag",
        ),
    )
    frame = frame.with_columns(
        pl.when(pl.col("_on_prior_roster"))
        .then(pl.col("prev1_years_exp") + 1)
        .when(pl.col("rookie_flag"))
        .then(pl.lit(0))
        .otherwise(None)
        .cast(pl.Int32)
        .alias("experience_years"),
    )
    frame = frame.with_columns(
        pl.col("age_at_anchor").is_not_null().alias("age_at_anchor_known"),
        pl.col("experience_years").is_not_null().alias("experience_years_known"),
        pl.col("prev1_games").is_not_null().alias("has_prior_season_stats"),
        (
            pl.when(
                pl.col("combine_forty").is_not_null() & pl.col("weight_lb").is_not_null(),
            )
            .then(
                pl.col("weight_lb") * _SPEED_SCORE_CONSTANT / pl.col("combine_forty").pow(4),
            )
            .otherwise(None)
            .cast(pl.Float64)
            .alias("combine_speed_score")
        ),
        pl.any_horizontal(
            pl.col(name).is_not_null()
            for name in (
                "combine_forty",
                "combine_bench",
                "combine_vertical",
                "combine_broad_jump",
                "combine_cone",
                "combine_shuttle",
            )
        ).alias("combine_observed_flag"),
    )
    frame = frame.with_columns(
        (
            (pl.col("age_at_anchor") - pl.col("age_at_anchor").mean().over("position"))
            / pl.col("age_at_anchor").std().over("position")
        )
        .cast(pl.Float64)
        .alias("position_age_z"),
    )

    # ---- depth / role -----------------------------------------------------------------
    frame = frame.with_columns(
        (
            pl.col("depth_rank_at_anchor").is_not_null()
            & pl.col("depth_observed_at_utc").is_not_null()
        ).alias("depth_rank_observed"),
        pl.col("prev1_role_rank").cast(pl.Int32).alias("prior_season_role_rank"),
    )
    frame = frame.with_columns(
        pl.col("prior_season_role_rank").is_not_null().alias("prior_season_role_known"),
    )
    frame = frame.with_columns(
        pl.struct(["depth_rank_observed", "prior_season_role_known"])
        .map_elements(
            lambda row: str(
                depth_context_state(
                    depth_rank_observed=bool(row["depth_rank_observed"]),
                    prior_role_known=bool(row["prior_season_role_known"]),
                ),
            ),
            return_dtype=pl.String,
        )
        .alias("depth_context_state"),
    )

    # ---- opportunity / production -----------------------------------------------------
    frame = frame.with_columns(
        pl.col("prev1_games").cast(pl.Int32),
        pl.col("prev1_fantasy_points_STD").alias("prev1_fantasy_points_std"),
        pl.col("prev1_fantasy_points_PPR").alias("prev1_fantasy_points_ppr"),
        pl.col("prev1_snap_share"),
    )
    frame = frame.with_columns(
        _ratio("prev1_fantasy_points_std", "prev1_games", minimum=1).alias(
            "prev1_fantasy_ppg_std",
        ),
        _ratio("prev1_fantasy_points_ppr", "prev1_games", minimum=1).alias(
            "prev1_fantasy_ppg_ppr",
        ),
        _ratio("prev1_carries", "prev1_games", minimum=1).alias("prev1_carries_pg"),
        _ratio("prev1_targets", "prev1_games", minimum=1).alias("prev1_targets_pg"),
        _ratio("prev1_receptions", "prev1_games", minimum=1).alias("prev1_receptions_pg"),
        _ratio("prev1_pass_attempts", "prev1_games", minimum=1).alias("prev1_pass_attempts_pg"),
        _ratio("prev1_rushing_yards", "prev1_games", minimum=1).alias("prev1_rushing_yards_pg"),
        _ratio("prev1_receiving_yards", "prev1_games", minimum=1).alias(
            "prev1_receiving_yards_pg",
        ),
        _ratio("prev1_passing_yards", "prev1_games", minimum=1).alias("prev1_passing_yards_pg"),
        _ratio("prev1_total_tds", "prev1_games", minimum=1).alias("prev1_total_tds_pg"),
        _ratio("prev1_offense_snaps", "prev1_snap_games", minimum=1).alias(
            "prev1_offense_snaps_pg",
        ),
        _ratio("prev1_expected_points", "prev1_xfp_games", minimum=1).alias("prev1_xfp_pg"),
        _ratio("prev1_points_over_expected", "prev1_xfp_games", minimum=1).alias(
            "prev1_fp_over_expected_pg",
        ),
        # Null when either component is missing, which is what the dictionary declares.
        # `max_horizontal` alone would return 0 for a player with no previous season, and a
        # fabricated "missed no games" reads as perfect durability for exactly the rows that
        # have no durability evidence at all - the same mistake as imputing years_exp = 0.
        pl.when(pl.col("prev1_team_games").is_null() | pl.col("prev1_games").is_null())
        .then(None)
        .otherwise(
            pl.max_horizontal(
                pl.lit(0),
                pl.col("prev1_team_games").cast(pl.Int32) - pl.col("prev1_games").cast(pl.Int32),
            ),
        )
        .cast(pl.Int32)
        .alias("prev1_games_missed"),
    )

    # ---- efficiency, with minimum denominators ----------------------------------------
    frame = frame.with_columns(
        (pl.col("prev1_carries").fill_null(0.0) >= RUSH_ATTEMPT_MINIMUM).alias(
            "prev1_rush_denominator_met",
        ),
        (pl.col("prev1_targets").fill_null(0.0) >= TARGET_MINIMUM).alias(
            "prev1_target_denominator_met",
        ),
        (pl.col("prev1_pass_attempts").fill_null(0.0) >= PASS_ATTEMPT_MINIMUM).alias(
            "prev1_pass_denominator_met",
        ),
    )
    frame = frame.with_columns(
        _ratio("prev1_rushing_yards", "prev1_carries", minimum=RUSH_ATTEMPT_MINIMUM).alias(
            "prev1_yards_per_carry",
        ),
        _ratio("prev1_rushing_tds", "prev1_carries", minimum=RUSH_ATTEMPT_MINIMUM).alias(
            "prev1_rush_td_rate",
        ),
        _ratio("prev1_receiving_yards", "prev1_targets", minimum=TARGET_MINIMUM).alias(
            "prev1_yards_per_target",
        ),
        _ratio("prev1_receptions", "prev1_targets", minimum=TARGET_MINIMUM).alias(
            "prev1_catch_rate",
        ),
        _ratio("prev1_receiving_tds", "prev1_targets", minimum=TARGET_MINIMUM).alias(
            "prev1_rec_td_rate",
        ),
        _ratio("prev1_passing_yards", "prev1_pass_attempts", minimum=PASS_ATTEMPT_MINIMUM).alias(
            "prev1_yards_per_attempt",
        ),
        _ratio("prev1_completions", "prev1_pass_attempts", minimum=PASS_ATTEMPT_MINIMUM).alias(
            "prev1_completion_pct",
        ),
        _ratio("prev1_passing_tds", "prev1_pass_attempts", minimum=PASS_ATTEMPT_MINIMUM).alias(
            "prev1_pass_td_rate",
        ),
        _ratio("prev1_interceptions", "prev1_pass_attempts", minimum=PASS_ATTEMPT_MINIMUM).alias(
            "prev1_interception_rate",
        ),
    )

    # ---- deeper lags and prior-window aggregates --------------------------------------
    deep: list[pl.Expr] = []
    for offset in DEEP_LAG_OFFSETS:
        deep.extend(
            [
                pl.col(f"prev{offset}_games").cast(pl.Int32).alias(f"prev{offset}_games"),
                _ratio(f"prev{offset}_fantasy_points_PPR", f"prev{offset}_games", minimum=1).alias(
                    f"prev{offset}_fantasy_ppg_ppr",
                ),
                _ratio(f"prev{offset}_carries", f"prev{offset}_games", minimum=1).alias(
                    f"prev{offset}_carries_pg",
                ),
                _ratio(f"prev{offset}_targets", f"prev{offset}_games", minimum=1).alias(
                    f"prev{offset}_targets_pg",
                ),
                _ratio(
                    f"prev{offset}_expected_points",
                    f"prev{offset}_xfp_games",
                    minimum=1,
                ).alias(f"prev{offset}_xfp_pg"),
            ],
        )
    frame = frame.with_columns(deep)
    frame = frame.with_columns(
        pl.col("prior5_seasons").fill_null(0).cast(pl.Int32),
        pl.col("prior5_games").fill_null(0).cast(pl.Int32),
        _ratio("prior5_points_ppr", "prior5_games", minimum=1).alias("prior5_fantasy_ppg_ppr"),
        _ratio("prior5_carries", "prior5_games", minimum=1).alias("prior5_carries_pg"),
        _ratio("prior5_targets", "prior5_games", minimum=1).alias("prior5_targets_pg"),
    )
    frame = frame.with_columns(
        _weighted_recency(
            ["prev1_fantasy_ppg_ppr", "prev2_fantasy_ppg_ppr", "prev3_fantasy_ppg_ppr"],
        ).alias("recent3_fantasy_ppg_ppr_w"),
        _weighted_recency(
            ["prev1_targets_pg", "prev2_targets_pg", "prev3_targets_pg"],
        ).alias("recent3_targets_pg_w"),
        _weighted_recency(
            ["prev1_carries_pg", "prev2_carries_pg", "prev3_carries_pg"],
        ).alias("recent3_carries_pg_w"),
    )

    # ---- team context -----------------------------------------------------------------
    frame = frame.with_columns(
        pl.col("team_at_anchor").is_not_null().alias("team_at_anchor_known"),
    )
    frame = frame.with_columns(
        (pl.col("team_at_anchor_known") & pl.col("prev1_team").is_not_null()).alias(
            "team_change_known",
        ),
    )
    frame = frame.with_columns(
        pl.when(pl.col("team_change_known"))
        .then(pl.col("team_at_anchor") != pl.col("prev1_team"))
        .otherwise(None)
        .alias("team_change_flag"),
    )

    # ---- lineage ----------------------------------------------------------------------
    prev1_present = pl.any_horizontal(
        pl.col("prev1_games").is_not_null(),
        pl.col("prev1_snap_games").is_not_null(),
        pl.col("prev1_xfp_games").is_not_null(),
        pl.col("prev1_years_exp").is_not_null(),
    )
    prev2_present = pl.any_horizontal(
        pl.col("prev2_games").is_not_null(),
        pl.col("prev2_xfp_games").is_not_null(),
    )
    prev3_present = pl.any_horizontal(
        pl.col("prev3_games").is_not_null(),
        pl.col("prev3_xfp_games").is_not_null(),
    )
    frame = frame.with_columns(
        pl.when(prev1_present)
        .then(pl.lit(season - 1))
        .when(prev2_present)
        .then(pl.lit(season - 2))
        .when(prev3_present)
        .then(pl.lit(season - 3))
        .otherwise(None)
        .cast(pl.Int32)
        .alias("max_lagged_source_season"),
    )

    # ADR-018: a row without a genuine pre-anchor depth observation keeps a null depth rank.
    # The state column carries the meaning; an imputed rank would not.
    frame = frame.with_columns(
        pl.when(pl.col("depth_context_state") == str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR))
        .then(pl.col("depth_rank_at_anchor"))
        .otherwise(None)
        .cast(pl.Int32)
        .alias("depth_rank_at_anchor"),
        pl.when(pl.col("depth_context_state") == str(DepthContextState.DEPTH_OBSERVED_AT_ANCHOR))
        .then(pl.col("depth_observed_at_utc"))
        .otherwise(None)
        .alias("depth_observed_at_utc"),
        pl.coalesce(pl.col("display_name"), pl.col("master_display_name"), pl.col("gsis_id")).alias(
            "display_name",
        ),
        pl.col("team_at_anchor_source").fill_null(str(TeamAtAnchorSource.UNAVAILABLE)),
    )
    return HISTORICAL_FEATURE_CONTRACT.coerce(frame)


def _bridge_coverage_checks(
    features: pl.DataFrame,
    usage: pl.DataFrame,
    snaps: pl.DataFrame,
    expected: pl.DataFrame,
) -> list[QualityCheck]:
    """Report how well the non-GSIS joins actually landed.

    The canonical key is GSIS by construction, so "identity coverage" would be trivially
    100% if measured on the key. The joins that can genuinely fail are the ones through
    another id space - snap counts via ``pfr_id`` - and through another project's player
    table - ffopportunity. Those are the numbers worth a threshold.
    """
    del usage
    checks: list[QualityCheck] = []
    if features.is_empty():
        return checks
    veterans = features.filter(pl.col("has_prior_season_stats"))
    if veterans.is_empty():
        return checks
    total = veterans.height
    for column, check_id, label, source in (
        ("prev1_snap_share", "identity.snap_bridge_coverage", "snap counts", "pfr_id bridge"),
        ("prev1_xfp_pg", "identity.expected_points_coverage", "ffopportunity", "gsis join"),
    ):
        resolved = int(veterans.filter(pl.col(column).is_not_null()).height)
        ratio = resolved / total if total else 0.0
        checks.append(
            QualityCheck.ok(
                check_id,
                stage="features",
                message=f"{label} resolved for {ratio:.1%} of rows with prior-season stats",
                observed=f"{resolved}/{total} via {source}",
            ),
        )
    del snaps, expected
    return checks


def coverage_ratio(features: pl.DataFrame, column: str) -> float:
    """Share of rows where ``column`` is populated. Used by the quality report."""
    if features.is_empty():
        return 0.0
    return float(features.filter(pl.col(column).is_not_null()).height) / float(features.height)


def apply_severity(check: QualityCheck, severity: Severity) -> QualityCheck:
    """Return ``check`` with a different severity, for callers that own the policy."""
    return QualityCheck(
        check_id=check.check_id,
        severity=severity,
        status=check.status,
        stage=check.stage,
        message=check.message,
        observed=check.observed,
        expected=check.expected,
    )
