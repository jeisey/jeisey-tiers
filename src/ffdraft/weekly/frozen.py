"""The weekly start/sit model, frozen before any evidence about it existed (ADR-095).

Every constant a comparison could be shopped over lives here, and this module is committed
**before** the development experiment that reads it runs, so no result can motivate a
definition after the fact. That is the discipline Phase 3, Phase 4 and Phase 11 each followed,
applied to a new question: not "what is he worth from here" (the rest-of-season model) but
"what will he score in his **next game**, and how sure are we".

**What this model is, and what it is not.**

* It is a **decision-layer** model, like the arbitrage board: it sits downstream of the
  intrinsic models and may read what they may not — here, the sportsbook game environment
  (total, spread and the implied team total) for the game being projected. The owner's
  instruction for in-season work is explicit: any data that improves a start/sit, trade or
  waiver decision is valid to use (ADR-095).
* It is **never** an input to the intrinsic draft model or to ``intrinsic-ros-v1``. Information
  flows one way. ``tests/unit/test_weekly_firewall.py`` asserts that neither of those feature
  sets names a weekly quantity, and that the forbidden-feature guard still refuses sportsbook
  names on both.
* It projects points **given that he plays**. It reads no injury report; the build prints the
  week's report beside the projection instead, with the measured historical rate at which
  players carrying each designation actually appeared.

**The target** (``next_game_points_given_appearance_v1``). For a snapshot at cutoff ``N`` —
exactly the rest-of-season snapshot, the same leakage-audited features — the target is the
player's fantasy points in week ``N + 1`` of the fantasy horizon, in the row's scoring preset,
on rows where he **appeared** in that week (a weekly stats row or an offensive snap). A week
his team was on bye is not a row. A snap-only appearance scores zero, which is the observation
rather than a fill.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

__all__ = [
    "B2_PRIOR_GAMES",
    "BASELINE_IDS",
    "DECISION_POOL_DEPTH",
    "FEATURE_FAMILIES",
    "FEATURE_FAMILY_LABELS",
    "OPPONENT_SHRINKAGE_GAMES",
    "PAIRWISE_GRID_POINTS",
    "PROMOTION_RULE",
    "TAIL_RULE",
    "WEEKLY_CANDIDATE_VERSION",
    "WEEKLY_CONTEXT_RULE_VERSION",
    "WEEKLY_DEVELOPMENT_SEASONS",
    "WEEKLY_DISTRIBUTION_RULE_VERSION",
    "WEEKLY_FEATURES",
    "WEEKLY_FEATURE_SET_VERSION",
    "WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN",
    "WEEKLY_MODEL_VERSION",
    "WEEKLY_NUM_BOOST_ROUND",
    "WEEKLY_PARAMETERS",
    "WEEKLY_POSITIONS",
    "WEEKLY_QUANTILE_LEVELS",
    "WEEKLY_SEALED_SEASON",
    "WEEKLY_SEED",
    "WEEKLY_TARGET_RULE_VERSION",
    "WEEKLY_TRAIN_START_SEASON",
    "PromotionRule",
    "WeeklySpec",
    "feature_family",
    "weekly_feature_set_hash",
]

#: The public model version. Distinct from both intrinsic models, permanently.
WEEKLY_MODEL_VERSION = "weekly-startsit-v1"

#: The one candidate the promotion rule judges. Quantile gradient boosting per position and
#: scoring preset, monotone rearrangement, then a split-conformal additive shift per quantile
#: measured on the last training season (see :mod:`ffdraft.weekly.model`).
WEEKLY_CANDIDATE_VERSION = "wc1_quantile_gbm_conformal_v1"

WEEKLY_TARGET_RULE_VERSION = "next_game_points_given_appearance_v1"
WEEKLY_CONTEXT_RULE_VERSION = "weekly_game_context_v1"
WEEKLY_FEATURE_SET_VERSION = "weekly_core_v1"

#: How a published quantile set becomes a distribution a browser can compare. One definition,
#: implemented twice (Python for the evaluation, TypeScript for the page) and pinned by a
#: shared golden vector so the two cannot drift.
WEEKLY_DISTRIBUTION_RULE_VERSION = "quantile_distribution_v1"

WEEKLY_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: Seven levels. The middle five are the repository's usual five; the outer two exist because
#: a start/sit comparison and a win probability both live in the tails.
WEEKLY_QUANTILE_LEVELS: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

#: The tails beyond the outermost quantiles, as linear extensions of the adjacent segment. The
#: upper tail is twice as long because weekly fantasy points are right-skewed: a 95th
#: percentile is closer to the median than the best game is to the 95th percentile.
TAIL_RULE: Any = MappingProxyType({"lower_factor": 1.0, "upper_factor": 2.0})

#: Probability grid for comparing two distributions: P(A > B) = mean over u_i of
#: F_B(Q_A(u_i)), u_i = (i + 0.5) / M. Deterministic, and identical in both languages.
PAIRWISE_GRID_POINTS = 200

#: Phase 3's W2 era start, inherited as the rest-of-season model inherited it.
WEEKLY_TRAIN_START_SEASON = 2017

#: Expanding-window development folds. The earliest gives three training seasons.
WEEKLY_DEVELOPMENT_SEASONS: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)

#: The sealed season for this model. No weekly-grain metric has ever been computed on it by
#: this project; its season totals and rest-of-season totals have been (ADR-069), so a 2025
#: result is strong but not fully naive evidence, exactly as the ROS holdout was.
WEEKLY_SEALED_SEASON = 2025

#: Distinct from both earlier tokens: opening one holdout must never open another.
WEEKLY_FINAL_EVAL_CONFIRMATION_TOKEN = "RELEASE-WEEKLY-FINAL-HOLDOUT-2025"

WEEKLY_SEED = 20260930

#: Games of league-average defence mixed into a defence's allowed-points rate. Four games is a
#: month of football: in week 2 a defence's one bad afternoon moves the reading by a fifth of
#: its size, by week 10 the defence mostly speaks for itself.
OPPONENT_SHRINKAGE_GAMES = 4.0

#: Which players a start/sit decision is actually made between, per position and week, for
#: the pairwise metrics. Ranked by the neutral B0 baseline so no candidate chooses its own
#: exam. Roughly the rostered starters-and-bench of a twelve-team league.
DECISION_POOL_DEPTH: Any = MappingProxyType({"QB": 24, "RB": 48, "WR": 60, "TE": 24})

#: The three declared baselines. Each gets its predictive distribution the same way: the
#: empirical quantiles of (actual - point) over the training window, per position and scoring
#: preset, added to the point. None of them is fitted beyond that.
#:
#: * ``b0_season_rate`` — points per game this season; before a first appearance, last
#:   season's rate in the preset (HALF is the mean of STD and PPR); else the position's
#:   training median. The neutral baseline that also ranks the decision pool.
#: * ``b1_recent_form`` — points per game over the last three calendar weeks when he played
#:   in any of them, else B0. "Ride the hot hand."
#: * ``b2_rate_x_vegas`` — B0 shrunk toward last season's rate by ``B2_PRIOR_GAMES`` games of
#:   prior, times (implied team points / the training window's mean implied team points).
#:   What a spreadsheet with a sportsbook tab does, and the strongest simple thing to beat.
BASELINE_IDS: tuple[str, ...] = ("b0_season_rate", "b1_recent_form", "b2_rate_x_vegas")
B2_PRIOR_GAMES = 3.0

#: LightGBM settings for every quantile booster. Conservative on purpose: a weekly target is
#: noisy, and a leaf of two hundred player-weeks is the smallest that says something.
WEEKLY_PARAMETERS: Any = MappingProxyType(
    {
        "learning_rate": 0.03,
        "num_leaves": 15,
        "min_data_in_leaf": 200,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 1,
        "lambda_l2": 1.0,
        "max_bin": 127,
        "deterministic": True,
        "force_row_wise": True,
        "num_threads": 4,
        "verbosity": -1,
    },
)
WEEKLY_NUM_BOOST_ROUND = 350

#: The model's inputs, by family. The family is what a reader is shown ("why is he projected
#: here"): grouped TreeSHAP contributions of the median booster, one bar per family.
FEATURE_FAMILIES: Any = MappingProxyType(
    {
        "form": (
            "ppg_to_date",
            "ppg_last3",
            "ppg_trend",
            "best_week_points_to_date",
            "points_sd_to_date",
            "points_per_opportunity_to_date",
            "td_per_opportunity_to_date",
            "points_over_expected_per_game_to_date",
        ),
        "role": (
            "snap_pct_mean_to_date",
            "snap_pct_last3",
            "snap_pct_trend",
            "target_share_to_date",
            "target_share_last3",
            "target_share_trend",
            "carry_share_to_date",
            "targets_per_game_to_date",
            "carries_per_game_to_date",
            "pass_attempts_per_game_to_date",
            "touches_per_game_to_date",
            "air_yards_per_game_to_date",
            "expected_points_per_game_to_date",
        ),
        "availability": (
            "games_to_date",
            "games_last3",
            "active_last_week",
            "weeks_since_last_game",
            "through_week",
        ),
        "offense": (
            "team_points_per_game_to_date",
            "team_pass_rate_to_date",
            "team_plays_per_game_to_date",
            "team_changed_in_season",
        ),
        "game": (
            "game_total_line",
            "game_team_margin",
            "game_team_points",
            "game_is_home",
            "game_rest_advantage",
            "game_indoors",
        ),
        "opponent": (
            "opp_allowed_ppg",
            "opp_allowed_index",
            "opp_allowed_prior_ppg",
            "opp_games_to_date",
        ),
        "prior": (
            "prev1_fantasy_ppg_ppr",
            "prev1_fantasy_ppg_std",
            "prev1_games",
            "prev1_snap_share",
            "prev1_target_share",
            "prev1_targets_pg",
            "prev1_carries_pg",
            "prev1_pass_attempts_pg",
            "prev1_xfp_pg",
            "recent3_fantasy_ppg_ppr_w",
            "prior5_fantasy_ppg_ppr",
            "draft_overall",
            "age_at_anchor",
            "experience_years",
            "rookie_flag",
        ),
    },
)

#: How each family is named on the page.
FEATURE_FAMILY_LABELS: Any = MappingProxyType(
    {
        "form": "Recent production",
        "role": "Role and volume",
        "availability": "Availability",
        "offense": "His offence",
        "game": "Game environment",
        "opponent": "Opponent",
        "prior": "Track record",
    },
)

WEEKLY_FEATURES: tuple[str, ...] = tuple(
    name for family in FEATURE_FAMILIES.values() for name in family
)


def feature_family(name: str) -> str:
    """The family a feature belongs to. Raises for a name the set does not hold."""
    for family, names in FEATURE_FAMILIES.items():
        if name in names:
            return str(family)
    raise KeyError(f"{name!r} is not a {WEEKLY_FEATURE_SET_VERSION} feature")


def weekly_feature_set_hash() -> str:
    """A short digest of the ordered feature list and its family assignment."""
    payload = json.dumps(
        {family: list(names) for family, names in FEATURE_FAMILIES.items()},
        sort_keys=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class PromotionRule:
    """``weekly_promotion_v1``, declared before the evidence.

    Primary metrics and the direction that counts as better:

    * **pinball** — mean pinball loss over the seven quantiles (lower). The whole distribution
      is what a start/sit comparison reads, so the whole distribution is scored.
    * **pairwise accuracy** — among same-position pairs in the week's decision pool, the share
      in which the player with the higher median outscored the other (higher). This is the
      start/sit question itself.
    * **pairwise Brier** — squared error of P(A outscores B) against what happened (lower).
      Accuracy rewards the right call; Brier rewards saying *how* sure, which is what the page
      prints.
    * **coverage** — share of outcomes inside P10-P90 and P25-P75.

    "Best baseline" is taken per metric, so the candidate has to beat the strongest simple
    alternative on each question separately rather than an average of weak ones.
    """

    version: str = "weekly_promotion_v1"
    #: Development: pooled over the five folds, every clause must hold.
    min_pinball_wins: int = 4
    coverage_80_band: tuple[float, float] = (0.75, 0.85)
    coverage_50_band: tuple[float, float] = (0.45, 0.55)
    bootstrap_replicates: int = 1000
    bootstrap_level: float = 0.95
    #: The holdout repeats the pooled clauses on 2025 alone, with point estimates.
    holdout_clauses: tuple[str, ...] = (
        "pinball_below_best_baseline",
        "pairwise_accuracy_above_best_baseline",
        "pairwise_brier_below_best_baseline",
        "coverage_80_in_band",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "development": {
                "pinball_below_best_baseline": "pooled over folds",
                "pinball_wins_min_folds": self.min_pinball_wins,
                "pairwise_accuracy_above_best_baseline": (
                    "pooled, and the week-clustered bootstrap interval of the difference "
                    "excludes zero"
                ),
                "pairwise_brier_below_best_baseline": "pooled over folds",
                "coverage_80_band": list(self.coverage_80_band),
                "coverage_50_band": list(self.coverage_50_band),
                "bootstrap_replicates": self.bootstrap_replicates,
                "bootstrap_level": self.bootstrap_level,
            },
            "holdout": list(self.holdout_clauses),
        }


PROMOTION_RULE = PromotionRule()


@dataclass(frozen=True)
class WeeklySpec:
    """Everything that decides what a fitted weekly model is. Digested into the artifact."""

    model_version: str = WEEKLY_MODEL_VERSION
    candidate_version: str = WEEKLY_CANDIDATE_VERSION
    target_rule: str = WEEKLY_TARGET_RULE_VERSION
    context_rule: str = WEEKLY_CONTEXT_RULE_VERSION
    feature_set: str = WEEKLY_FEATURE_SET_VERSION
    features: tuple[str, ...] = WEEKLY_FEATURES
    levels: tuple[float, ...] = WEEKLY_QUANTILE_LEVELS
    parameters: Any = field(default_factory=lambda: MappingProxyType(dict(WEEKLY_PARAMETERS)))
    num_boost_round: int = WEEKLY_NUM_BOOST_ROUND
    seed: int = WEEKLY_SEED
    calibration: str = "split-conformal additive shift per quantile, last training season"
    opponent_shrinkage_games: float = OPPONENT_SHRINKAGE_GAMES

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "candidate_version": self.candidate_version,
            "target_rule": self.target_rule,
            "context_rule": self.context_rule,
            "feature_set": self.feature_set,
            "feature_set_hash": weekly_feature_set_hash(),
            "features": list(self.features),
            "levels": list(self.levels),
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "seed": self.seed,
            "calibration": self.calibration,
            "opponent_shrinkage_games": self.opponent_shrinkage_games,
        }

    def configuration_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
