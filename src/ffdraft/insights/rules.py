"""``insights_v1`` and ``insights_select_v1``: every constant the story generator uses.

Constants are **editable heuristics declared before any story was generated**, not tuned to a
player's outcome. Where an existing rule already defines a quantity, it is reused rather than
redefined: the calendar window is ``recent_form_v1``'s Last 3, the strong-week bands and role
thresholds are ``breakout_v1``'s, appearances and points are ``season_actuals_v1``'s, shares are
pooled as ``usage_signals_v1`` pools them. The whole rule is published in
``ros_build_metadata.insights.rule`` so a page explains a story from the artifact.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ffdraft.signals.recent import BREAKOUT_RULE, RECENT_FORM_RULE

__all__ = [
    "FAMILIES",
    "FAMILY_SHORT",
    "FORBIDDEN_PHRASES",
    "INSIGHTS_RULE_VERSION",
    "INSIGHT_DEFINITIONS",
    "INSIGHT_LIMITATIONS",
    "INSIGHT_RULE",
    "PRESCREEN_DESIGNATIONS",
    "PRESCREEN_EMPLOYMENT",
    "PRESCREEN_ROSTER_CODES",
    "SELECTION_RULE",
    "SELECTION_RULE_VERSION",
    "UNSUPPORTED_CLAIMS",
    "VARIANTS",
    "InsightRule",
    "SelectionRule",
]

INSIGHTS_RULE_VERSION = "insights_v1"
SELECTION_RULE_VERSION = "insights_select_v1"

#: The six families, in editorial priority order (the lead selection walks them in this order).
FAMILIES: tuple[str, ...] = (
    "weekly_upside",
    "opportunity_opening",
    "volume_vs_results",
    "streak_watch",
    "role_battle",
    "pace_perspective",
)

#: Each family's variants, in the order their stories interleave inside the family.
VARIANTS: Mapping[str, tuple[str, ...]] = {
    "weekly_upside": ("ceiling",),
    "opportunity_opening": ("prospective", "observed"),
    "volume_vs_results": ("lagging", "shrinking"),
    "streak_watch": ("breakout", "production_without_role", "quiet_role_growth"),
    "role_battle": ("backfield", "receiving"),
    "pace_perspective": ("per_game_hidden", "overlooked"),
}

#: The prefix of a story id: ``{short}-{subject}``.
FAMILY_SHORT: Mapping[str, str] = {
    "weekly_upside": "upside",
    "opportunity_opening": "opening",
    "volume_vs_results": "volume",
    "streak_watch": "streak",
    "role_battle": "role",
    "pace_perspective": "pace",
}

#: The build-time pre-screen for a ``this_week`` story (ADR-116). A strict SUBSET of the
#: availability policy's exclusions (ADR-101, ``web/src/data/availability.ts``): it can only
#: remove a player the policy would also refuse, so a lead slot is not spent on him. The page
#: re-applies the full policy at the reader's clock and is authoritative.
PRESCREEN_DESIGNATIONS: frozenset[str] = frozenset({"Out", "Doubtful"})
PRESCREEN_ROSTER_CODES: frozenset[str] = frozenset(
    {"RES", "PUP", "NFI", "SUS", "EXE", "CUT", "RET"}
)
PRESCREEN_EMPLOYMENT: frozenset[str] = frozenset({"unsigned", "retired"})


def _bands() -> dict[str, int]:
    return dict(BREAKOUT_RULE.bands)


def _volume_gap() -> dict[str, int]:
    # Places between workload rank and production rank: half a 12-team starter band.
    return {"RB": 12, "WR": 12, "TE": 6}


def _share_metric() -> dict[str, str]:
    # The team share each position's role is read through: breakout_v1's pooled measures.
    return {"RB": "carry_share", "WR": "target_share", "TE": "target_share"}


def _role_floor() -> dict[str, float]:
    # breakout_v1's *emerging* level: a meaningful role, for a baseline or for a riser. A
    # quarterback's (his share of his team's pass attempts) is half: he is taking the snaps.
    return {"QB": 0.50, "RB": 0.30, "WR": 0.16, "TE": 0.13}


def _role_step() -> dict[str, float]:
    # breakout_v1's *increase*: a material change in a share, in either direction. A
    # quarterback's is a backup becoming the passer.
    return {"QB": 0.40, "RB": 0.15, "WR": 0.06, "TE": 0.05}


def _absent_floor() -> dict[str, float]:
    # breakout_v1's *substantial* level: a teammate whose absence is worth a story. A
    # quarterback's is the starter's share of his team's pass attempts.
    return {"carry_share": 0.45, "target_share": 0.18, "pass_share": 0.80}


@dataclass(frozen=True, slots=True)
class InsightRule:
    """``insights_v1``. Every number a family's qualification, effect or ordering reads."""

    version: str = INSIGHTS_RULE_VERSION
    #: The window: recent_form_v1's default Last-N, the same calendar weeks for everyone.
    window_weeks: int = RECENT_FORM_RULE.default_window
    #: Appearances inside the window and before it for a comparison to exist at all.
    min_window_games: int = 2
    min_baseline_games: int = 2
    #: Strong-week bands and the 12-team starter band (breakout_v1).
    bands: Mapping[str, int] = field(default_factory=_bands)
    #: volume_vs_results.
    volume_positions: tuple[str, ...] = ("RB", "WR", "TE")
    volume_gap_places: Mapping[str, int] = field(default_factory=_volume_gap)
    #: "Workload holds": window opportunities per game at least this percentage of baseline.
    volume_hold_percent: int = 90
    share_metric: Mapping[str, str] = field(default_factory=_share_metric)
    #: Thresholds shared by shrinking roles, role battles, openings and quiet growth.
    role_floor: Mapping[str, float] = field(default_factory=_role_floor)
    role_step: Mapping[str, float] = field(default_factory=_role_step)
    #: weekly_upside: ESPN roster ceilings, percent rostered strictly below.
    upside_ceilings: tuple[int, ...] = (50, 25, 10)
    upside_default_ceiling: int = 50
    upside_per_position: int = 3
    upside_role_games: int = 2
    #: opportunity_opening: the absent teammate's season share floor, and his minimum games.
    absent_floor: Mapping[str, float] = field(default_factory=_absent_floor)
    absent_min_games: int = 2
    opening_rows: int = 3
    #: streak_watch: touchdown points at or above this share of window points is TD-led.
    td_led_percent: int = 50
    #: pace_perspective: the per-game cohort's minimum appearances, and the hidden-rank gap.
    pace_min_games: int = 3
    pace_hidden_gap_places: int = 8
    pace_games: int = 17
    #: role_battle: rows shown per room.
    room_rows: int = 4
    #: Red zone and inside the five, as drive_breadth and the Skill Tree define them.
    red_zone_yardline: int = 20
    inside_five_yardline: int = 5
    #: Stories published per family variant per preset (beyond the lead), before dedup.
    variant_cap: int = 8

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "window_weeks": self.window_weeks,
            "min_window_games": self.min_window_games,
            "min_baseline_games": self.min_baseline_games,
            "bands": dict(self.bands),
            "volume_positions": list(self.volume_positions),
            "volume_gap_places": dict(self.volume_gap_places),
            "volume_hold_percent": self.volume_hold_percent,
            "share_metric": dict(self.share_metric),
            "role_floor": dict(self.role_floor),
            "role_step": dict(self.role_step),
            "upside_ceilings": list(self.upside_ceilings),
            "upside_default_ceiling": self.upside_default_ceiling,
            "upside_per_position": self.upside_per_position,
            "upside_role_games": self.upside_role_games,
            "upside_role_rule": BREAKOUT_RULE.version,
            "absent_floor": dict(self.absent_floor),
            "absent_min_games": self.absent_min_games,
            "opening_rows": self.opening_rows,
            "td_led_percent": self.td_led_percent,
            "pace_min_games": self.pace_min_games,
            "pace_hidden_gap_places": self.pace_hidden_gap_places,
            "pace_games": self.pace_games,
            "room_rows": self.room_rows,
            "red_zone_yardline": self.red_zone_yardline,
            "inside_five_yardline": self.inside_five_yardline,
            "variant_cap": self.variant_cap,
            "prescreen": {
                "designations": sorted(PRESCREEN_DESIGNATIONS),
                "roster_codes": sorted(PRESCREEN_ROSTER_CODES),
                "employment": sorted(PRESCREEN_EMPLOYMENT),
            },
        }


INSIGHT_RULE = InsightRule()


def _caps() -> dict[str, int]:
    return {
        "weekly_upside": 3,
        "opportunity_opening": 2,
        "volume_vs_results": 3,
        "streak_watch": 2,
        "role_battle": 2,
        "pace_perspective": 1,
    }


@dataclass(frozen=True, slots=True)
class SelectionRule:
    """``insights_select_v1``: the lead, by editorial priority and diversity — never a score.

    One story per player overall (the first in family order keeps him; the rest are listed in
    its ``also_qualifies``). The lead walks the families round-robin in :data:`FAMILIES` order,
    each pass taking each family's next story that keeps every cap; a pass that adds nothing
    ends it. Within a family stories interleave by variant, then by ``family_rank``.
    """

    version: str = SELECTION_RULE_VERSION
    lead_max: int = 12
    family_caps: Mapping[str, int] = field(default_factory=_caps)
    #: Lead stories per NFL team.
    team_cap: int = 2
    #: weekly_upside interleaves positions in this order inside the family.
    upside_positions: tuple[str, ...] = ("WR", "RB", "TE", "QB")

    def to_dict(self) -> dict[str, Any]:
        return {
            "lead_max": self.lead_max,
            "family_order": list(FAMILIES),
            "family_caps": dict(self.family_caps),
            "team_cap": self.team_cap,
            "one_story_per_player": True,
        }


SELECTION_RULE = SelectionRule()

#: The sentences that travel with the stories (``ros_build_metadata.insights.definitions``).
INSIGHT_DEFINITIONS: Mapping[str, str] = {
    "window": (
        "The last three completed regular-season weeks ending at the cutoff, the same calendar "
        "weeks for every player (recent form's Last 3). The baseline is every earlier week."
    ),
    "appearance": (
        "A week with a stats row or an offensive snap. A bye (B) and a game his team played "
        "without him (D) are not games and are never zeros."
    ),
    "opportunity": (
        "Targets for a receiver or tight end; carries plus targets for a running back. A "
        "team share pools his total over his team's total in the games he played."
    ),
    "ceiling": (
        "P90 of the weekly start/sit model's distribution of his points given that he plays: "
        "one week in ten at or above it. Not a 90% chance of a big game, and not a ranking of "
        "boom probabilities."
    ),
    "typical_week": (
        "The weekly model's own account of the same player in a typical week (his team's "
        "average lines, half at home, equal rest, a league-average defense). The difference is "
        "the matchup's modelled effect, counted once."
    ),
    "espn_rostered": (
        "ESPN's public share of ESPN leagues rostering him. It describes ESPN leagues, not "
        "yours; an unknown reading is not 0%."
    ),
    "pace": "Points per game × 17: arithmetic extrapolation, not a projection.",
    "snap_share": (
        "His share of his team's offensive snaps. Teammates share the field, so snap shares "
        "overlap and never add to 100%."
    ),
    "red_zone": (
        "Carries and targets on plays snapped at the opponent's 20 or closer (inside the five: "
        "the 5 or closer), counted from nflverse play-by-play."
    ),
}

INSIGHT_LIMITATIONS: tuple[str, ...] = (
    "Stories describe completed weeks and the published weekly distribution; none is a "
    "forecast of a result, and none says a player is due.",
    "No expected-points estimate is published (ADR-086), so a gap between workload and "
    "scoring is described, never quantified as luck.",
    "Snaps are not routes and a target is not a first read: no route, route-tree or coverage "
    "claim is made.",
    "ESPN roster share describes ESPN leagues; a low share does not mean a player is "
    "available in your league.",
    "League size changes nothing here: no story reads a replacement level or a VORP.",
)

#: Claims the generator deliberately does not make, with the reason the page prints.
UNSUPPORTED_CLAIMS: tuple[tuple[str, str], ...] = (
    (
        "Route participation, targets per route run, first-read share, route-tree fit",
        "No current-season route or participation source is available (the participation "
        "feed refuses 2026; ADR-107).",
    ),
    (
        "Expected fantasy points, xFP share, points over expected",
        "ffopportunity is a model input whose per-player publication is undecided (ADR-086, "
        "ADR-091).",
    ),
    (
        "Situational snaps (third down, two-minute, short yardage)",
        "Snap counts are per game; no participation data places a player on a given play.",
    ),
    (
        "Quarterback–receiver compatibility",
        "Not measurable from the available data; average depth of target is not a route tree.",
    ),
    (
        "Historical positional comparisons",
        "The in-season build loads the current season only; no comparable historical cohort "
        "is published.",
    ),
    (
        "Below-projection claims",
        "Archived pregame projections are not retained per week, so a current number is never "
        "presented as a past expectation.",
    ),
)

#: Stems the validator refuses in any printed text, names removed first: case-insensitive, from
#: a word boundary, any ending ("route" also refuses "routes"; "due" also "overdue"), a space
#: matching a space or hyphen ("expected points", "expected-points").
FORBIDDEN_PHRASES: tuple[str, ...] = (
    "due",
    "regress",
    "unlucky",
    "luck",
    "xfp",
    "expected points",
    "expected fantasy",
    "over expected",
    "route",
    "first read",
    "tprr",
    "per route",
    "coverage",
    "confiden",
    "guarantee",
    "lock",
    "boom score",
)
