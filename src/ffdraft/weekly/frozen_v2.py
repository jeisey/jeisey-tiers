"""``weekly-startsit-v2``, frozen before any evidence about it existed (ADR-099).

v1 (ADR-096) reads his role, form and track record, his offence, the opposing defence's
allowed points and the game's sportsbook lines. The owner asked for the things that also move a
week: **weather at kickoff**, **his offence's health** and **the opposing defence's health**.
v2 is v1 plus whichever of those three feature families earns its place, by a rule declared
here, in this commit, before the development run that reads it.

**v2 is a new model, not a refit.** It has its own version, feature set, configuration hash,
promotion rule and holdout. v1 stays in production, unchanged, until v2 is promoted by the
rule below; until then v2 runs in **shadow**: fitted, served beside v1 into a private record
that the page never reads, and judged prospectively.

**The holdout.** v1 consumed the sealed 2025 season. 2025 is therefore *previously examined
evidence* here: v2's development report scores it and prints it, and nothing is decided by it.
The 2026 weeks already played are not untouched either — they shaped the week-4 build and
this session's probes. v2's untouched holdout is **prospective**: the 2026 games that kick off
after a production refresh running this code has retained, before kickoff, both models'
predictions and every pregame input they read (:data:`PROSPECTIVE_HOLDOUT`). It is evaluated
at most twice, at declared points, and never tuned on: changing anything in this module
after the freeze is a ``weekly-startsit-v3``.

**The decision cutoff** (:data:`DECISION_CUTOFF`) aligns every input to the same instant: the
last production refresh before the game kicks off. What each family can know then, and what
training uses in its place, is stated per family below and in docs/MODELING.md §35.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ffdraft.weekly.frozen import (
    FEATURE_FAMILIES,
    FEATURE_FAMILY_LABELS,
    OPPONENT_SHRINKAGE_GAMES,
    WEEKLY_FEATURES,
    WEEKLY_NUM_BOOST_ROUND,
    WEEKLY_PARAMETERS,
    WEEKLY_QUANTILE_LEVELS,
    WEEKLY_SEED,
    WEEKLY_TARGET_RULE_VERSION,
)

__all__ = [
    "CANDIDATE_VARIANTS",
    "DECISION_CUTOFF",
    "FAMILY_SELECTION_RULE",
    "PROSPECTIVE_HOLDOUT",
    "PROMOTION_RULE_V2",
    "V2_FAMILIES",
    "V2_FAMILY_LABELS",
    "WEATHER_PARITY_RULE",
    "WEEKLY_V2_CONTEXT_RULE_VERSION",
    "WEEKLY_V2_DEVELOPMENT_SEASONS",
    "WEEKLY_V2_FEATURE_SET_VERSION",
    "WEEKLY_V2_FROZEN_AT_UTC",
    "WEEKLY_V2_MODEL_VERSION",
    "WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON",
    "WEEKLY_V2_PROSPECTIVE_SEASON",
    "WEEKLY_V2_PROSPECTIVE_TOKEN",
    "FamilySelectionRule",
    "ProspectiveHoldout",
    "PromotionRuleV2",
    "WeatherParityRule",
    "WeeklySpecV2",
    "v2_spec",
    "variant_families",
]

WEEKLY_V2_MODEL_VERSION = "weekly-startsit-v2"
WEEKLY_V2_FEATURE_SET_VERSION = "weekly_gameday_v1"
WEEKLY_V2_CONTEXT_RULE_VERSION = "weekly_gameday_context_v1"

#: The three candidate families, added to v1's ``weekly_core_v1`` features unchanged.
#:
#: * ``weather`` — the venue's fixed roof type from the versioned venue registry
#:   (``config/venues.yaml``: 0 open air, 1 retractable, 2 fixed dome) and, at an open-air
#:   venue only, wind (mph), temperature (deg F) and whether precipitation is expected at
#:   kickoff. A retractable roof's state is not announced before the game, so its weather
#:   is ``null`` (unknown) in training and in serving alike; a dome's is ``null`` because
#:   no weather reaches the field. Training reads the game book's recorded kickoff weather
#:   through :data:`WEATHER_PARITY_RULE`, so it matches what a forecast would have said.
#: * ``lineup`` — his offence's health (``lagged_starters_v1``, ``ffdraft.weekly.lineup``):
#:   lagged offensive-line starters ruled out (Out or Doubtful) and listed Questionable, the
#:   lagged starting quarterback ruled out, and the recent share of his team's targets and
#:   carries held by ruled-out teammates (and of targets by Questionable ones) — the volume
#:   a teammate's absence redistributes.
#: * ``defense`` — the opposing defence's health by the same rule: lagged starting
#:   cornerbacks, safeties and defensive linemen ruled out, and defensive backs and linemen
#:   listed Questionable.
#:
#: A team whose report carries no game status yet is ``null`` (unknown) on every health
#: input, at training and serving alike (97-99% of historical team-weeks carry one).
V2_FAMILIES: Any = MappingProxyType(
    {
        "weather": ("wx_roof_type", "wx_wind_mph", "wx_temp_f", "wx_precip"),
        "lineup": (
            "own_ol_out",
            "own_ol_questionable",
            "own_qb_out",
            "own_vacated_targets",
            "own_vacated_carries",
            "own_questionable_targets",
        ),
        "defense": (
            "opp_cb_out",
            "opp_s_out",
            "opp_dl_out",
            "opp_db_questionable",
            "opp_dl_questionable",
        ),
    },
)

V2_FAMILY_LABELS: Any = MappingProxyType(
    {
        **dict(FEATURE_FAMILY_LABELS),
        "weather": "Weather at kickoff",
        "lineup": "His offence's health",
        "defense": "Opposing defence's health",
    },
)

#: The development variants, each v1's features plus the named families. ``v1`` is v1's
#: frozen specification refitted per fold, exactly as its own evaluation fitted it.
CANDIDATE_VARIANTS: tuple[str, ...] = (
    "v1",
    "v1+weather",
    "v1+lineup",
    "v1+defense",
    "v1+weather+lineup+defense",
)

WEEKLY_V2_DEVELOPMENT_SEASONS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)

#: Scored and printed, never decisive: v1's sealed holdout, already consumed (ADR-096).
WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON = 2025

WEEKLY_V2_PROSPECTIVE_SEASON = 2026

#: Distinct from every earlier token: opening the prospective holdout must be on purpose.
WEEKLY_V2_PROSPECTIVE_TOKEN = "PROSPECTIVE-WEEKLY-V2-2026"

#: The freeze. A game kicking off at or before this instant is never prospective evidence,
#: whatever was retained about it. Set once, in the freeze commit, and never moved.
WEEKLY_V2_FROZEN_AT_UTC = "2026-10-01T18:00:00Z"

#: The one instant every input is aligned to, at serving and in the prospective holdout.
DECISION_CUTOFF: Any = MappingProxyType(
    {
        "id": "last_refresh_before_kickoff_v1",
        "definition": (
            "For each game, the last production refresh whose build finished before the "
            "game's scheduled kickoff. The prospective holdout scores the shadow record that "
            "refresh retained; a game with no such record is not eligible."
        ),
        "lines": (
            "the total and spread posted on nflverse's schedule at the refresh (training: "
            "the schedule's lines, which are the closing lines)"
        ),
        "injury_report": (
            "the target week's report as nflverse publishes it at the refresh (training: the "
            "file's rows; 2017-2024 rows carry a modification time before kickoff for all but "
            "24 of 44,356; 2025 rows carry none and are unverified; probe 2026-10-01, "
            "docs/source-probes/2026-10-01/injuries)"
        ),
        "weather": (
            "the newest forecast retained by the capture at or before the refresh, valid at "
            "the kickoff hour (training: the game book's recorded kickoff weather, mapped "
            "through weather_training_parity_v1)"
        ),
        "starters": "snap counts through the cutoff week only (lagged_starters_v1)",
        "not_known": (
            "game-day inactives (published about 90 minutes before kickoff) and any roster "
            "move absent from the report"
        ),
    },
)


@dataclass(frozen=True)
class WeatherParityRule:
    """``weather_training_parity_v1``: what training reads so it matches what serving sees.

    A forecast is not the weather. Training rows carry the weather the game book recorded at
    kickoff; serving rows carry a forecast. To train on what serving will see, each recorded
    value ``A`` is replaced by ``a + b * A + e``, where ``a``, ``b`` and the residual pool
    ``e`` are the least-squares map from recorded to forecast measured on the forecast issued
    the day before (Open-Meteo Previous Runs API, ``previous_day1``, at the kickoff hour; the
    2024-2025 open-air games the archive probe reached), and ``e`` is drawn deterministically
    by a hash of the game id. A serving forecast is at most ~14 hours old at the refresh
    before the latest kickoff, so day-before error bounds serving error from above. Recorded
    precipitation becomes "expected" with the measured probabilities ``P(F=1 | O=1)`` and
    ``P(F=1 | O=0)``, ``F`` being a short-lead precipitation probability at or above the
    threshold (the Previous Runs API publishes amounts, not probabilities). The parameters
    (``scripts/weather_error_model.py``) are measured from the source before the freeze and
    committed beside this rule; their digest is part of the configuration hash.
    """

    version: str = "weather_training_parity_v1"
    parameters_file: str = "config/weather-forecast-error-v1.json"
    precipitation_probability_threshold: float = 50.0
    #: A forecast older than this at the refresh, or whose valid interval does not cover the
    #: kickoff hour, is ``null`` (unknown), never a stale number.
    max_forecast_age_hours: float = 12.0
    max_lead_hours: float = 168.0
    #: Plausibility bounds at the kickoff hour: outside them the value is unknown.
    wind_mph_range: tuple[float, float] = (0.0, 60.0)
    temp_f_range: tuple[float, float] = (-30.0, 120.0)
    precipitation_text_rule: str = "game_book_precip_v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "parameters_file": self.parameters_file,
            "precipitation_probability_threshold": self.precipitation_probability_threshold,
            "max_forecast_age_hours": self.max_forecast_age_hours,
            "max_lead_hours": self.max_lead_hours,
            "wind_mph_range": list(self.wind_mph_range),
            "temp_f_range": list(self.temp_f_range),
            "precipitation_text_rule": self.precipitation_text_rule,
        }


WEATHER_PARITY_RULE = WeatherParityRule()


@dataclass(frozen=True)
class FamilySelectionRule:
    """``weekly_family_selection_v1``: a family enters v2 only if it beats noise over v1.

    On the development folds, each family ``f`` is compared with v1 refitted on the same
    folds. It is **selected** when every clause holds:

    1. pooled macro pinball of ``v1+f`` is below v1's;
    2. the week-clustered bootstrap 95% interval of the pooled row-level pinball difference
       (v1 minus ``v1+f``) lies above zero;
    3. ``v1+f`` has the lower pinball in at least four of the five folds;
    4. the start/sit decision does not get worse beyond noise: pooled pairwise accuracy at
       least v1's minus ``accuracy_tolerance`` and pairwise Brier at most v1's plus
       ``brier_tolerance``.

    v2's features are v1's plus every selected family. When two or more are selected their
    union must pass the same four clauses; if it does not, v2 is v1 plus the single selected
    family with the lowest pooled pinball. When none is selected, **v2 is rejected at
    development**: no artifact is fitted and v1 stays, with each family's measured value in
    the report.
    """

    version: str = "weekly_family_selection_v1"
    min_fold_wins: int = 4
    bootstrap_replicates: int = 1000
    bootstrap_level: float = 0.95
    accuracy_tolerance: float = 0.002
    brier_tolerance: float = 0.001

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "min_fold_wins": self.min_fold_wins,
            "bootstrap_replicates": self.bootstrap_replicates,
            "bootstrap_level": self.bootstrap_level,
            "accuracy_tolerance": self.accuracy_tolerance,
            "brier_tolerance": self.brier_tolerance,
        }


FAMILY_SELECTION_RULE = FamilySelectionRule()


@dataclass(frozen=True)
class ProspectiveHoldout:
    """The 2026 games v2 is judged on, and when it may be judged.

    **Eligible rows:** a player-week of the prospective season whose game kicked off after
    the freeze commit, for which a production refresh running v2's code retained a shadow
    record before kickoff (:data:`DECISION_CUTOFF`) carrying both v1's and v2's quantiles and
    every input v2 read with its retrieval time, and in which the player appeared (the target
    is points given an appearance). Records are never backfilled: a prediction made after
    kickoff, or recomputed later from today's files, is not pregame and is not eligible.

    **Minimum evidence:** ``min_weeks`` complete target weeks, ``min_rows`` scored rows over
    the three presets and ``min_pairs`` decision-pool pairs. Until it is met the evaluation
    command prints counts only.

    **Looks:** at most two — the first time the minimum is met (99% interval), and after the
    last scored week of the season (95% interval). Nothing is changed between them.
    """

    season: int = WEEKLY_V2_PROSPECTIVE_SEASON
    min_weeks: int = 8
    min_rows: int = 6000
    min_pairs: int = 40000
    first_look_level: float = 0.99
    final_look_level: float = 0.95

    def to_dict(self) -> dict[str, Any]:
        return {
            "season": self.season,
            "min_weeks": self.min_weeks,
            "min_rows": self.min_rows,
            "min_pairs": self.min_pairs,
            "first_look_level": self.first_look_level,
            "final_look_level": self.final_look_level,
            "eligibility": (
                "kickoff after the freeze; shadow record retained before kickoff by a "
                "production refresh; appeared in the game; never backfilled"
            ),
        }


PROSPECTIVE_HOLDOUT = ProspectiveHoldout()


@dataclass(frozen=True)
class PromotionRuleV2:
    """``weekly_promotion_v2``: when v2 replaces v1, and what counts as a rejection.

    **Development** (2020-2024): v2 passes every development clause of
    ``weekly_promotion_v1`` against the best of B0-B2, and the family-selection clauses
    against v1. **2025** is scored and printed (``consistent`` if v2's pinball is below v1's)
    and decides nothing. **Prospective** (2026, :data:`PROSPECTIVE_HOLDOUT`), at a look:

    * **promote** — pooled pinball below v1's, the week-clustered bootstrap interval of the
      row-level difference (v1 minus v2) above zero at the look's level, P10-P90 coverage in
      ``coverage_80_band``, pairwise Brier at most v1's plus ``brier_tolerance`` and
      pairwise accuracy at least v1's minus ``accuracy_tolerance``;
    * **reject** — the interval lies entirely below zero, or coverage falls outside
      ``reject_coverage_band``, or Brier is worse than v1's by more than
      ``reject_brier_margin``;
    * **insufficient evidence** — anything else, including a minimum not met. v1 stays.

    Insufficient evidence is not a rejection, and the report says which it is.
    """

    version: str = "weekly_promotion_v2"
    coverage_80_band: tuple[float, float] = (0.75, 0.85)
    reject_coverage_band: tuple[float, float] = (0.70, 0.90)
    brier_tolerance: float = 0.001
    accuracy_tolerance: float = 0.002
    reject_brier_margin: float = 0.005

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "development": (
                "weekly_promotion_v1 development clauses vs B0-B2, and "
                "weekly_family_selection_v1 clauses vs v1"
            ),
            "previously_examined_2025": "scored and printed; decides nothing",
            "coverage_80_band": list(self.coverage_80_band),
            "reject_coverage_band": list(self.reject_coverage_band),
            "brier_tolerance": self.brier_tolerance,
            "accuracy_tolerance": self.accuracy_tolerance,
            "reject_brier_margin": self.reject_brier_margin,
            "outcomes": ["promote", "reject", "insufficient_evidence"],
        }


PROMOTION_RULE_V2 = PromotionRuleV2()


def _digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def variant_families(variant: str) -> tuple[str, ...]:
    """``"v1+weather+lineup"`` -> ``("weather", "lineup")``, validated against the families."""
    head, *tail = variant.split("+")
    if head != "v1" or any(name not in V2_FAMILIES for name in tail):
        raise KeyError(f"{variant!r} is not a weekly v2 variant")
    return tuple(name for name in V2_FAMILIES if name in tail)


@dataclass(frozen=True)
class WeeklySpecV2:
    """Everything that decides what a fitted v2 (or development variant) model is."""

    added_families: tuple[str, ...]
    model_version: str = WEEKLY_V2_MODEL_VERSION
    target_rule: str = WEEKLY_TARGET_RULE_VERSION
    context_rule: str = WEEKLY_V2_CONTEXT_RULE_VERSION
    feature_set: str = WEEKLY_V2_FEATURE_SET_VERSION
    levels: tuple[float, ...] = WEEKLY_QUANTILE_LEVELS
    parameters: Any = field(default_factory=lambda: MappingProxyType(dict(WEEKLY_PARAMETERS)))
    num_boost_round: int = WEEKLY_NUM_BOOST_ROUND
    seed: int = WEEKLY_SEED
    calibration: str = "split-conformal additive shift per quantile, last training season"
    opponent_shrinkage_games: float = OPPONENT_SHRINKAGE_GAMES
    lineup_rule: str = "lagged_starters_v1"
    weather_rule: Any = field(default_factory=lambda: WEATHER_PARITY_RULE)
    weather_parameters_digest: str = ""

    @property
    def candidate_version(self) -> str:
        suffix = "+".join(self.added_families) if self.added_families else "none"
        return f"wc2_quantile_gbm_conformal_v1[{suffix}]"

    @property
    def families(self) -> Any:
        merged = dict(FEATURE_FAMILIES)
        for name in self.added_families:
            merged[name] = V2_FAMILIES[name]
        return MappingProxyType(merged)

    @property
    def features(self) -> tuple[str, ...]:
        return (
            *WEEKLY_FEATURES,
            *(name for family in self.added_families for name in V2_FAMILIES[family]),
        )

    def to_dict(self) -> dict[str, Any]:
        families = {key: list(value) for key, value in self.families.items()}
        return {
            "model_version": self.model_version,
            "candidate_version": self.candidate_version,
            "target_rule": self.target_rule,
            "context_rule": self.context_rule,
            "feature_set": self.feature_set,
            "feature_set_hash": _digest(families),
            "base_feature_set": "weekly_core_v1",
            "added_families": list(self.added_families),
            "features": list(self.features),
            "levels": list(self.levels),
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "seed": self.seed,
            "calibration": self.calibration,
            "opponent_shrinkage_games": self.opponent_shrinkage_games,
            "lineup_rule": self.lineup_rule,
            "weather_rule": self.weather_rule.to_dict(),
            "weather_parameters_digest": self.weather_parameters_digest,
            "decision_cutoff": DECISION_CUTOFF["id"],
        }

    def configuration_hash(self) -> str:
        return _digest(self.to_dict())


def v2_spec(families: tuple[str, ...], *, weather_parameters_digest: str) -> WeeklySpecV2:
    """The spec for v1 plus ``families`` (in the declared family order)."""
    ordered = tuple(name for name in V2_FAMILIES if name in families)
    if len(ordered) != len(set(families)):
        raise KeyError(f"unknown family in {families!r}")
    return WeeklySpecV2(added_families=ordered, weather_parameters_digest=weather_parameters_digest)


def frozen_rules() -> dict[str, Any]:
    """Every rule above, as one document: the report and the card both print it."""
    return {
        "model_version": WEEKLY_V2_MODEL_VERSION,
        "feature_set": WEEKLY_V2_FEATURE_SET_VERSION,
        "families": {key: list(value) for key, value in V2_FAMILIES.items()},
        "variants": list(CANDIDATE_VARIANTS),
        "development_seasons": list(WEEKLY_V2_DEVELOPMENT_SEASONS),
        "previously_examined_season": WEEKLY_V2_PREVIOUSLY_EXAMINED_SEASON,
        "decision_cutoff": dict(DECISION_CUTOFF),
        "weather_parity": WEATHER_PARITY_RULE.to_dict(),
        "family_selection": FAMILY_SELECTION_RULE.to_dict(),
        "prospective_holdout": PROSPECTIVE_HOLDOUT.to_dict(),
        "promotion": PROMOTION_RULE_V2.to_dict(),
        "baselines": ["v1 (weekly-startsit-v1, refitted per fold)", "b0", "b1", "b2"],
    }
