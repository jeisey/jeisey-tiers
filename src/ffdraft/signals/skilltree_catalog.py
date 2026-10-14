"""The Skill Tree's metric catalogue and per-position trees (ADR-107, ``skill_tree_v1``).

**One place for every word.** Each metric's definition, formula, sample, cohort rule,
interpretation and limitation is written here once and published in
``skill_tree_definitions.json``; the card prints what the artifact says and paraphrases
nothing. The trees below are ADR-107's tables, in order.

Nothing in this module computes; :mod:`ffdraft.signals.skilltree` does. Splitting the two keeps
the catalogue reviewable as a document and lets a test pin it against the ADR.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

__all__ = [
    "BRANCHES",
    "Branch",
    "CATALOG",
    "COMBINE_METRIC",
    "Kind",
    "Metric",
    "Node",
    "PRESENCE_METRIC",
    "SKILL_TREE_POSITIONS",
    "Source",
    "TREES",
    "metric_ids_for",
]

Kind = Literal["volume", "share", "rate", "context"]
Direction = Literal["higher", "lower", "neutral"]
Unit = Literal["count", "fraction", "pp", "yards", "epa", "seconds"]
#: Which cohort a metric ranks within (ADR-107 "cohorts").
Cohort = Literal["appearing", "games", "minimum", "ngs", "combine", "none"]
Source = Literal["player_stats", "snap_counts", "play_by_play", "next_gen_stats", "combine"]

SKILL_TREE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: The registry/attribution name of each source, as the definitions print it.
SOURCE_LABELS: Mapping[Source, str] = {
    "player_stats": "nflverse weekly player stats (official box score)",
    "snap_counts": "nflverse snap counts (Pro Football Reference)",
    "play_by_play": "nflverse play-by-play (nflfastR)",
    "next_gen_stats": "NFL Next Gen Stats via nflverse (season summary)",
    "combine": "NFL Scouting Combine via nflverse",
}


@dataclass(frozen=True, slots=True)
class Metric:
    """One statistic: what it is, how it is counted and against whom it is ranked."""

    id: str
    label: str
    #: Fits a node (≤ 16 characters).
    short_label: str
    kind: Kind
    direction: Direction
    unit: Unit
    #: Published precision of ``value``.
    decimals: int
    source: Source
    source_fields: tuple[str, ...]
    formula: str
    definition: str
    interpretation: str
    limitations: str
    cohort: Cohort
    #: The per-player column holding the numerator (for a total, the value).
    num: str
    #: The per-player column holding the denominator, or None for a total / NGS / combine.
    den: str | None = None
    numerator_label: str | None = None
    denominator_label: str | None = None
    #: The denominator a rate needs before it is ranked (``cohort == "minimum"``).
    minimum: float | None = None
    minimum_unit: str | None = None


@dataclass(frozen=True, slots=True)
class Node:
    metric: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Branch:
    id: str
    label: str
    nodes: tuple[Node, ...] = field(default_factory=tuple)


_SEASON = "Regular season through the board's cutoff week, summed over the games he played."
_OFFICIAL = "Official nflverse box-score total."
_NOISY_EARLY = (
    "Efficiency rates are noisy early in a season: in 2023-2025 the weeks 1-5 rate of this kind "
    "related only weakly to the rest of the same season (EDA 2026-10-14). It describes his games "
    "so far, not what comes next."
)
_SHARE_GAMES = (
    "Pooled over the games he played: his total divided by his team's total in those games, "
    "keyed by the club he played for that week."
)


_m = Metric


PRESENCE_METRIC = _m(
    id="appearances",
    label="Games played",
    short_label="Games",
    kind="volume",
    direction="higher",
    unit="count",
    decimals=0,
    source="player_stats",
    source_fields=("player_stats rows", "snap_counts.offense_snaps"),
    formula="regular-season weeks with a weekly stats row or at least one offensive snap",
    definition=(
        "A game played is a regular-season week with a weekly stats row or at least one "
        "offensive snap (the usage layer's and season actuals' definition)."
    ),
    interpretation="Every other number in the tree is counted over these games only.",
    limitations="Byes and missed weeks are not games; a game is counted however few snaps.",
    cohort="appearing",
    num="games",
)

COMBINE_METRIC = _m(
    id="combine_forty",
    label="Combine 40-yard dash",
    short_label="Combine 40",
    kind="context",
    direction="lower",
    unit="seconds",
    decimals=2,
    source="combine",
    source_fields=("combine.forty", "combine.season", "combine.pos", "combine.pfr_id"),
    formula="his recorded 40-yard dash at the NFL Scouting Combine",
    definition=(
        "His 40-yard dash time at the NFL Scouting Combine, in the year he tested, ranked among "
        "every tester at the same combine position since 2000 with a recorded time (faster "
        "ranks first)."
    ),
    interpretation=(
        "Historical athletic context from before his NFL career. It is not a measurement of "
        "his current on-field speed."
    ),
    limitations=(
        "Linked only through nflverse's PFR-to-GSIS identity bridge; players who did not run "
        "at the combine, or whose combine row cannot be linked unambiguously, have no time. "
        "Pro-day times are not included."
    ),
    cohort="combine",
    num="combine_forty",
)

_CATALOG_LIST: tuple[Metric, ...] = (
    # ---------------------------------------------------------------- passing (QB)
    _m(
        id="pass_attempts",
        label="Pass attempts",
        short_label="Attempts",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("attempts",),
        formula="sum(attempts)",
        definition=f"Official pass attempts. {_OFFICIAL} Spikes count; sacks do not.",
        interpretation="Passing workload.",
        limitations=_SEASON,
        cohort="appearing",
        num="att",
    ),
    _m(
        id="completions",
        label="Completions",
        short_label="Completions",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("completions",),
        formula="sum(completions)",
        definition=f"Official completions. {_OFFICIAL}",
        interpretation="Passing workload completed.",
        limitations=_SEASON,
        cohort="appearing",
        num="cmp",
    ),
    _m(
        id="passing_yards",
        label="Passing yards",
        short_label="Pass yards",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("passing_yards",),
        formula="sum(passing_yards)",
        definition=f"Official passing yards. {_OFFICIAL}",
        interpretation="Passing production.",
        limitations=_SEASON,
        cohort="appearing",
        num="pass_yds",
    ),
    _m(
        id="passing_tds",
        label="Passing touchdowns",
        short_label="Pass TDs",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("passing_tds",),
        formula="sum(passing_tds)",
        definition=f"Official passing touchdowns. {_OFFICIAL}",
        interpretation="Passing scoring.",
        limitations=_SEASON,
        cohort="appearing",
        num="pass_td",
    ),
    _m(
        id="passing_td_rate",
        label="Touchdown rate",
        short_label="TD rate",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("passing_tds", "attempts"),
        formula="sum(passing_tds) / sum(attempts)",
        definition="Passing touchdowns per pass attempt.",
        interpretation="How often an attempt became a touchdown.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="pass_td",
        den="att",
        numerator_label="touchdowns",
        denominator_label="attempts",
        minimum=50,
        minimum_unit="attempts",
    ),
    _m(
        id="cpoe",
        label="Completion % over expected",
        short_label="CPOE",
        kind="rate",
        direction="higher",
        unit="pp",
        decimals=2,
        source="play_by_play",
        source_fields=("cpoe", "pass_attempt", "sack", "two_point_attempt", "passer_player_id"),
        formula="sum(cpoe) / attempts carrying a cpoe value (percentage points)",
        definition=(
            "Completion percentage over expected (CPOE): his completions minus the completion "
            "probability nflfastR's model gave each attempt, in percentage points, pooled over "
            "every attempt that has a probability (throwaways and spikes have none)."
        ),
        interpretation="Positive means he completed more than the throws' difficulty predicts.",
        limitations=(
            "nflfastR's completion model, not Next Gen Stats'. Pooled over attempts, not the "
            f"average of weekly values (which differ by up to 34 points). {_NOISY_EARLY}"
        ),
        cohort="minimum",
        num="cpoe_sum",
        den="cpoe_n",
        denominator_label="attempts with a completion probability",
        minimum=50,
        minimum_unit="attempts with a completion probability",
    ),
    _m(
        id="completion_pct",
        label="Completion %",
        short_label="Comp %",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("completions", "attempts"),
        formula="sum(completions) / sum(attempts)",
        definition="Official completions per official pass attempt.",
        interpretation="Raw accuracy, not adjusted for how difficult the throws were.",
        limitations=(
            "Rewards short, easy throws; read it beside CPOE and intended air yards. "
            + _NOISY_EARLY
        ),
        cohort="minimum",
        num="cmp",
        den="att",
        numerator_label="completions",
        denominator_label="attempts",
        minimum=50,
        minimum_unit="attempts",
    ),
    _m(
        id="yards_per_attempt",
        label="Yards per attempt",
        short_label="Yds / att",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("passing_yards", "attempts"),
        formula="sum(passing_yards) / sum(attempts)",
        definition="Official passing yards per official pass attempt (sacks excluded).",
        interpretation="Yardage gained per throw.",
        limitations="Sacks are not attempts here; see sack rate. " + _NOISY_EARLY,
        cohort="minimum",
        num="pass_yds",
        den="att",
        numerator_label="passing yards",
        denominator_label="attempts",
        minimum=50,
        minimum_unit="attempts",
    ),
    _m(
        id="intended_air_yards",
        label="Intended air yards per attempt",
        short_label="Air yds / att",
        kind="context",
        direction="neutral",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("passing_air_yards", "attempts"),
        formula="sum(passing_air_yards) / sum(attempts)",
        definition=(
            "How far downfield his passes travel on average, completed or not: official "
            "passing air yards per attempt."
        ),
        interpretation=(
            "A style reading, not a quality: deeper throws complete less often and gain more "
            "when they do."
        ),
        limitations="Includes incomplete passes and throwaways (official air yards).",
        cohort="minimum",
        num="pass_air",
        den="att",
        numerator_label="air yards",
        denominator_label="attempts",
        minimum=50,
        minimum_unit="attempts",
    ),
    _m(
        id="pass_epa_per_dropback",
        label="EPA per dropback",
        short_label="EPA / dropback",
        kind="rate",
        direction="higher",
        unit="epa",
        decimals=3,
        source="player_stats",
        source_fields=("passing_epa", "attempts", "sacks_suffered"),
        formula="sum(passing_epa) / (sum(attempts) + sum(sacks_suffered))",
        definition=(
            "Expected points added per dropback: nflverse's passing EPA (which credits the "
            "quarterback up to a receiver's fumble) over pass attempts plus sacks. Scrambles "
            "are not included. The same definition as the card's in-season usage reading."
        ),
        interpretation="How much each dropback moved his team's expected score.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="pass_epa",
        den="dropbacks",
        numerator_label="EPA",
        denominator_label="dropbacks (attempts + sacks)",
        minimum=50,
        minimum_unit="dropbacks",
    ),
    _m(
        id="dropback_success_rate",
        label="Dropback success rate",
        short_label="Success",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("epa", "pass_attempt", "two_point_attempt", "passer_player_id"),
        formula="dropbacks with EPA > 0 / dropbacks",
        definition=(
            "Share of his dropbacks (pass attempts and sacks, as play-by-play flags them) with "
            "positive expected points added. EPA > 0, not a down-and-distance rule."
        ),
        interpretation="How consistently his dropbacks helped, regardless of size.",
        limitations=(
            "Same plays as EPA per dropback; success uses each play's own EPA. " + _NOISY_EARLY
        ),
        cohort="minimum",
        num="db_success",
        den="db_pbp",
        numerator_label="successful dropbacks",
        denominator_label="dropbacks",
        minimum=50,
        minimum_unit="dropbacks",
    ),
    _m(
        id="sack_rate",
        label="Sack rate",
        short_label="Sack rate",
        kind="rate",
        direction="lower",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("sacks_suffered", "attempts"),
        formula="sum(sacks_suffered) / (sum(attempts) + sum(sacks_suffered))",
        definition="Sacks taken per dropback (pass attempts plus sacks).",
        interpretation="Lower is better. Blocking, play design and the quarterback all share it.",
        limitations="Not a measure of the quarterback alone. " + _NOISY_EARLY,
        cohort="minimum",
        num="sacks",
        den="dropbacks",
        numerator_label="sacks",
        denominator_label="dropbacks",
        minimum=50,
        minimum_unit="dropbacks",
    ),
    _m(
        id="avg_time_to_throw",
        label="Time to throw",
        short_label="Time to throw",
        kind="context",
        direction="neutral",
        unit="seconds",
        decimals=2,
        source="next_gen_stats",
        source_fields=("avg_time_to_throw", "attempts", "week == 0", "season_type == REG"),
        formula="Next Gen Stats season summary: average seconds from snap to throw",
        definition=(
            "Average time from the snap to the throw on his pass attempts (sacks excluded), "
            "from the Next Gen Stats regular-season summary."
        ),
        interpretation=(
            "A style reading: a quick release and a long one each have costs. Neither is better."
        ),
        limitations=(
            "Only for passers Next Gen Stats qualifies, and only when its season summary "
            "matches his official attempts through the cutoff."
        ),
        cohort="ngs",
        num="ngs_time_to_throw",
        den="ngs_attempts",
        denominator_label="attempts (Next Gen Stats)",
    ),
    _m(
        id="interception_rate",
        label="Interception rate",
        short_label="INT rate",
        kind="rate",
        direction="lower",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("passing_interceptions", "attempts"),
        formula="sum(passing_interceptions) / sum(attempts)",
        definition="Interceptions thrown per pass attempt.",
        interpretation="Lower is better.",
        limitations=(
            "Interceptions are rare: in 2023-2025 a weeks 1-5 interception rate did not "
            "anticipate the rest of the season at all (EDA 2026-10-14)."
        ),
        cohort="minimum",
        num="int",
        den="att",
        numerator_label="interceptions",
        denominator_label="attempts",
        minimum=50,
        minimum_unit="attempts",
    ),
    _m(
        id="designed_rushes",
        label="Designed rushes",
        short_label="Designed runs",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "qb_scramble", "play_type", "rusher_player_id"),
        formula="his carries with qb_scramble = 0, kneels and two-point tries excluded",
        definition=(
            "Runs he carried that were not scrambles: rush attempts with no scramble flag, "
            "kneel-downs and two-point tries excluded. nflverse has no designed-run flag; this "
            "is the derivation."
        ),
        interpretation="How often the offence calls his number as a runner.",
        limitations=(
            "Includes sneaks and option keepers; a broken pass play that nflverse does not "
            "flag as a scramble would count here."
        ),
        cohort="appearing",
        num="designed",
    ),
    _m(
        id="scrambles",
        label="Scrambles",
        short_label="Scrambles",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "qb_scramble", "rusher_player_id"),
        formula="his rush attempts with qb_scramble = 1",
        definition="Dropbacks he turned into runs, as nflverse flags them (qb_scramble).",
        interpretation="Improvised rushing volume.",
        limitations=_SEASON,
        cohort="appearing",
        num="scrambles",
    ),
    _m(
        id="scramble_rate",
        label="Scramble rate",
        short_label="Scramble rate",
        kind="context",
        direction="neutral",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("qb_scramble", "pass_attempt", "sack"),
        formula="scrambles / (dropbacks + scrambles)",
        definition="Share of his dropbacks, scrambles included, that became scrambles.",
        interpretation="A style reading: escaping pressure or extending plays.",
        limitations="Neither a high nor a low rate is better in itself.",
        cohort="minimum",
        num="scrambles",
        den="db_all",
        numerator_label="scrambles",
        denominator_label="dropbacks including scrambles",
        minimum=50,
        minimum_unit="dropbacks",
    ),
    _m(
        id="rushing_yards",
        label="Rushing yards",
        short_label="Rush yards",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("rushing_yards",),
        formula="sum(rushing_yards)",
        definition=f"Official rushing yards, kneel-downs included. {_OFFICIAL}",
        interpretation="Rushing production.",
        limitations=_SEASON,
        cohort="appearing",
        num="rush_yds",
    ),
    _m(
        id="rushing_tds",
        label="Rushing touchdowns",
        short_label="Rush TDs",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("rushing_tds",),
        formula="sum(rushing_tds)",
        definition=f"Official rushing touchdowns. {_OFFICIAL}",
        interpretation="Rushing scoring.",
        limitations="Touchdowns are rare events; small differences are noise.",
        cohort="appearing",
        num="rush_td",
    ),
    _m(
        id="red_zone_rushes",
        label="Red-zone rushes",
        short_label="RZ rushes",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "rusher_player_id"),
        formula="his non-kneel rush attempts snapped at yardline_100 <= 20",
        definition=(
            "Rushes he carried inside the opponent's 20-yard line, designed runs and scrambles "
            "alike; kneel-downs and two-point tries excluded."
        ),
        interpretation="His rushing role where touchdowns are scored.",
        limitations="A count; it depends on how often his team reaches the red zone.",
        cohort="appearing",
        num="rz_rush",
    ),
    _m(
        id="goal_line_rushes",
        label="Goal-line rushes",
        short_label="GL rushes",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "rusher_player_id"),
        formula="his non-kneel rush attempts snapped at yardline_100 <= 5",
        definition="Rushes he carried inside the opponent's 5-yard line (sneaks included).",
        interpretation="Short-yardage scoring role.",
        limitations="Very small counts; one drive can change it.",
        cohort="appearing",
        num="gl_rush",
    ),
    _m(
        id="red_zone_dropbacks",
        label="Red-zone dropbacks",
        short_label="RZ dropbacks",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("pass_attempt", "yardline_100", "passer_player_id"),
        formula="his dropbacks snapped at yardline_100 <= 20",
        definition="Pass attempts and sacks he had inside the opponent's 20-yard line.",
        interpretation="His passing role where touchdowns are scored.",
        limitations="Tracks his team's red-zone trips closely.",
        cohort="appearing",
        num="rz_db",
    ),
    # ---------------------------------------------------------------- rushing (RB)
    _m(
        id="carries",
        label="Carries",
        short_label="Carries",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("carries",),
        formula="sum(carries)",
        definition=f"Official rush attempts. {_OFFICIAL}",
        interpretation="Rushing workload.",
        limitations=_SEASON,
        cohort="appearing",
        num="car",
    ),
    _m(
        id="carry_share",
        label="Share of team carries",
        short_label="Carry share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("carries", "team"),
        formula="all his carries / all his team's official carries in his games",
        definition=(
            "His share of all his team's official carries in the games he played — every "
            "position, quarterback scrambles and kneel-downs included (the usage layer's "
            "definition). " + _SHARE_GAMES
        ),
        interpretation="How much of his team's running he gets when he plays.",
        limitations=(
            "Kneel-downs and quarterback runs sit in the denominator; leaving kneels out moved "
            "the 2026 week-5 share by a median 0.3 points (max 4.5)."
        ),
        cohort="games",
        num="car",
        den="team_car",
        numerator_label="his carries",
        denominator_label="team carries in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="offense_snap_share",
        label="Offensive snap share",
        short_label="Snap share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="snap_counts",
        source_fields=("offense_snaps", "offense_pct"),
        formula="all his offensive snaps / all his team's offensive snaps in his games",
        definition=(
            "His share of his team's offensive snaps in the games he played, pooled over "
            "snaps. Team snaps are taken from the player on the field for the most snaps."
        ),
        interpretation="How much of the game he is on the field for.",
        limitations=(
            "Snaps are not routes or touches. A game the snap file has no row for him in is "
            "left out of both sides. Differs from the usage rails' per-game average."
        ),
        cohort="games",
        num="snaps",
        den="team_snaps",
        numerator_label="his offensive snaps",
        denominator_label="team offensive snaps in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="yards_per_carry",
        label="Yards per carry",
        short_label="Yds / carry",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("rushing_yards", "carries"),
        formula="sum(rushing_yards) / sum(carries)",
        definition="Official rushing yards per official carry.",
        interpretation="Yards gained per run, before any context.",
        limitations="Driven by blocking and a few long runs. " + _NOISY_EARLY,
        cohort="minimum",
        num="rush_yds",
        den="car",
        numerator_label="rushing yards",
        denominator_label="carries",
        minimum=25,
        minimum_unit="carries",
    ),
    _m(
        id="rush_epa_per_carry",
        label="Rushing EPA per carry",
        short_label="EPA / carry",
        kind="rate",
        direction="higher",
        unit="epa",
        decimals=3,
        source="play_by_play",
        source_fields=("epa", "rush_attempt", "play_type", "rusher_player_id"),
        formula="sum(epa) / his non-kneel carries",
        definition=(
            "Expected points added per carry, kneel-downs and two-point tries excluded. "
            "Counts first downs, touchdowns and fumbles, not just yards."
        ),
        interpretation="How much each carry moved his team's expected score.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="rush_epa",
        den="car_nk",
        numerator_label="EPA",
        denominator_label="carries (kneels excluded)",
        minimum=25,
        minimum_unit="carries",
    ),
    _m(
        id="rush_success_rate",
        label="Rushing success rate",
        short_label="Success",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("epa", "rush_attempt", "play_type", "rusher_player_id"),
        formula="non-kneel carries with EPA > 0 / non-kneel carries",
        definition="Share of his carries with positive expected points added (EPA > 0).",
        interpretation="How often a carry helped, however small the gain.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="rush_success",
        den="car_nk",
        numerator_label="successful carries",
        denominator_label="carries (kneels excluded)",
        minimum=25,
        minimum_unit="carries",
    ),
    _m(
        id="explosive_run_rate",
        label="10+ yard run rate",
        short_label="10+ yd runs",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("rushing_yards", "rush_attempt", "play_type", "rusher_player_id"),
        formula="non-kneel carries gaining >= 10 yards / non-kneel carries",
        definition="Share of his carries that gained 10 or more yards.",
        interpretation="Big-play frequency on the ground.",
        limitations="Play-level yards (laterals excluded). " + _NOISY_EARLY,
        cohort="minimum",
        num="run10",
        den="car_nk",
        numerator_label="10+ yard carries",
        denominator_label="carries (kneels excluded)",
        minimum=25,
        minimum_unit="carries",
    ),
    _m(
        id="explosive_runs",
        label="10+ yard runs",
        short_label="10+ yd runs",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rushing_yards", "rush_attempt", "rusher_player_id"),
        formula="his non-kneel carries gaining >= 10 yards",
        definition="Carries that gained 10 or more yards.",
        interpretation="Big plays on the ground, as a count.",
        limitations=_SEASON,
        cohort="appearing",
        num="run10",
    ),
    _m(
        id="rush_yards_over_expected_per_att",
        label="Rush yards over expected per attempt",
        short_label="RYOE / att",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="next_gen_stats",
        source_fields=("rush_yards_over_expected_per_att", "rush_attempts", "week == 0"),
        formula="Next Gen Stats season summary: rush yards over expected per attempt",
        definition=(
            "Average rushing yards above what Next Gen Stats' tracking model expected from "
            "each carry's blockers and defenders, from its regular-season summary."
        ),
        interpretation="Yards gained beyond what the blocking and defence gave him.",
        limitations=(
            "Only for rushers Next Gen Stats qualifies (about 30+ attempts by week 5) and only "
            "when its season summary matches his official carries through the cutoff. "
            + _NOISY_EARLY
        ),
        cohort="ngs",
        num="ngs_ryoe",
        den="ngs_rush_attempts",
        denominator_label="rush attempts (Next Gen Stats)",
    ),
    # ---------------------------------------------------------------- receiving
    _m(
        id="targets",
        label="Targets",
        short_label="Targets",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("targets",),
        formula="sum(targets)",
        definition=f"Official targets: passes thrown to him. {_OFFICIAL}",
        interpretation="Receiving workload.",
        limitations=_SEASON,
        cohort="appearing",
        num="tgt",
    ),
    _m(
        id="receptions",
        label="Receptions",
        short_label="Receptions",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("receptions",),
        formula="sum(receptions)",
        definition=f"Official receptions. {_OFFICIAL}",
        interpretation="Catches.",
        limitations=_SEASON,
        cohort="appearing",
        num="rec",
    ),
    _m(
        id="receiving_yards",
        label="Receiving yards",
        short_label="Rec yards",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("receiving_yards",),
        formula="sum(receiving_yards)",
        definition=f"Official receiving yards. {_OFFICIAL}",
        interpretation="Receiving production.",
        limitations=_SEASON,
        cohort="appearing",
        num="rec_yds",
    ),
    _m(
        id="receiving_tds",
        label="Receiving touchdowns",
        short_label="Rec TDs",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="player_stats",
        source_fields=("receiving_tds",),
        formula="sum(receiving_tds)",
        definition=f"Official receiving touchdowns. {_OFFICIAL}",
        interpretation="Receiving scoring.",
        limitations="Touchdowns are rare events; small differences are noise.",
        cohort="appearing",
        num="rec_td",
    ),
    _m(
        id="target_share",
        label="Target share",
        short_label="Target share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("targets", "team"),
        formula="all his targets / all his team's targets in his games",
        definition=(
            "His share of his team's targets in the games he played (the usage layer's "
            "definition). " + _SHARE_GAMES
        ),
        interpretation="How much of the passing game is aimed at him when he plays.",
        limitations="Counts targets, not routes; a decoy on the field is not in it.",
        cohort="games",
        num="tgt",
        den="team_tgt",
        numerator_label="his targets",
        denominator_label="team targets in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="air_yards_share",
        label="Air-yard share",
        short_label="Air-yd share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("receiving_air_yards", "team"),
        formula="all his receiving air yards / all his team's air yards in his games",
        definition=(
            "His share of the air yards his team's passes travelled toward targets, in the "
            "games he played (the usage layer's definition). " + _SHARE_GAMES
        ),
        interpretation="How much of the downfield passing game runs through him.",
        limitations="Negative air yards (behind the line) reduce both sides.",
        cohort="games",
        num="rec_air",
        den="team_air",
        numerator_label="his air yards",
        denominator_label="team air yards in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="catch_rate",
        label="Catch rate",
        short_label="Catch rate",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="player_stats",
        source_fields=("receptions", "targets"),
        formula="sum(receptions) / sum(targets)",
        definition=(
            "Receptions per target — not his share of the team's catches. Uncatchable throws "
            "count as targets."
        ),
        interpretation="How often a throw to him became a catch.",
        limitations="Depends on depth and throw quality. " + _NOISY_EARLY,
        cohort="minimum",
        num="rec",
        den="tgt",
        numerator_label="receptions",
        denominator_label="targets",
        minimum=15,
        minimum_unit="targets",
    ),
    _m(
        id="yards_per_target",
        label="Yards per target",
        short_label="Yds / target",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("receiving_yards", "targets"),
        formula="sum(receiving_yards) / sum(targets)",
        definition="Official receiving yards per target.",
        interpretation="Yardage produced per throw his way.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="rec_yds",
        den="tgt",
        numerator_label="receiving yards",
        denominator_label="targets",
        minimum=15,
        minimum_unit="targets",
    ),
    _m(
        id="yards_per_reception",
        label="Yards per reception",
        short_label="Yds / catch",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("receiving_yards", "receptions"),
        formula="sum(receiving_yards) / sum(receptions)",
        definition="Official receiving yards per reception.",
        interpretation="How much each catch gains; rises with depth and yards after the catch.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="rec_yds",
        den="rec",
        numerator_label="receiving yards",
        denominator_label="receptions",
        minimum=10,
        minimum_unit="receptions",
    ),
    _m(
        id="adot",
        label="Average depth of target",
        short_label="aDOT",
        kind="context",
        direction="neutral",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("receiving_air_yards", "targets"),
        formula="sum(receiving_air_yards) / sum(targets)",
        definition=(
            "How far past the line of scrimmage passes to him travel on average, caught or "
            "not (official receiving air yards per target)."
        ),
        interpretation="A role reading: deep threat or underneath target. Neither is better.",
        limitations="Includes incomplete and uncatchable throws.",
        cohort="minimum",
        num="rec_air",
        den="tgt",
        numerator_label="air yards",
        denominator_label="targets",
        minimum=15,
        minimum_unit="targets",
    ),
    _m(
        id="yac_per_reception",
        label="Yards after catch per reception",
        short_label="YAC / catch",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="player_stats",
        source_fields=("receiving_yards_after_catch", "receptions"),
        formula="sum(receiving_yards_after_catch) / sum(receptions)",
        definition="Yards gained after the catch, per reception (nflverse's unofficial YAC).",
        interpretation="What he adds once the ball is in his hands.",
        limitations=(
            "Short, schemed throws inflate it; see YAC over expected where Next Gen Stats "
            "covers him. " + _NOISY_EARLY
        ),
        cohort="minimum",
        num="yac",
        den="rec",
        numerator_label="yards after catch",
        denominator_label="receptions",
        minimum=10,
        minimum_unit="receptions",
    ),
    _m(
        id="rec_epa_per_target",
        label="Receiving EPA per target",
        short_label="EPA / target",
        kind="rate",
        direction="higher",
        unit="epa",
        decimals=3,
        source="play_by_play",
        source_fields=("epa", "pass_attempt", "sack", "receiver_player_id"),
        formula="total EPA on his targets / his targets",
        definition=(
            "Expected points added per target: catches, first downs, touchdowns, drops and "
            "interceptions on throws to him all count."
        ),
        interpretation="How much each throw to him moved his team's expected score.",
        limitations="Shared with the quarterback and the play call. " + _NOISY_EARLY,
        cohort="minimum",
        num="rec_epa",
        den="tgt_pbp",
        numerator_label="EPA",
        denominator_label="targets",
        minimum=15,
        minimum_unit="targets",
    ),
    _m(
        id="explosive_catches",
        label="20+ yard catches",
        short_label="20+ yd catches",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("receiving_yards", "complete_pass", "receiver_player_id"),
        formula="his completed targets gaining >= 20 yards",
        definition="Receptions that gained 20 or more yards.",
        interpretation="Big plays in the passing game, as a count.",
        limitations="Play-level yards (laterals excluded).",
        cohort="appearing",
        num="catch20",
    ),
    _m(
        id="explosive_catch_rate",
        label="20+ yard catches per target",
        short_label="20+ yd rate",
        kind="rate",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("receiving_yards", "complete_pass", "receiver_player_id"),
        formula="his 20+ yard receptions / his targets",
        definition="Share of his targets that became a reception of 20 or more yards.",
        interpretation="Big-play frequency per throw his way.",
        limitations=_NOISY_EARLY,
        cohort="minimum",
        num="catch20",
        den="tgt_pbp",
        numerator_label="20+ yard catches",
        denominator_label="targets",
        minimum=15,
        minimum_unit="targets",
    ),
    _m(
        id="yac_over_expected",
        label="YAC over expected",
        short_label="YACOE",
        kind="rate",
        direction="higher",
        unit="yards",
        decimals=2,
        source="next_gen_stats",
        source_fields=("avg_yac_above_expectation", "receptions", "targets", "week == 0"),
        formula="Next Gen Stats season summary: YAC minus expected YAC, per reception",
        definition=(
            "Yards after the catch beyond what Next Gen Stats' tracking model expected from "
            "where defenders were at the catch, per reception."
        ),
        interpretation="What he gains after the catch that the situation did not give him.",
        limitations=(
            "Only for receivers Next Gen Stats qualifies (wide receivers and tight ends) and "
            "only when its season summary matches his official targets through the cutoff."
        ),
        cohort="ngs",
        num="ngs_yacoe",
        den="ngs_receptions",
        denominator_label="receptions (Next Gen Stats)",
    ),
    _m(
        id="avg_separation",
        label="Separation at the catch point",
        short_label="Separation",
        kind="context",
        direction="neutral",
        unit="yards",
        decimals=2,
        source="next_gen_stats",
        source_fields=("avg_separation", "targets", "week == 0"),
        formula="Next Gen Stats season summary: average yards to the nearest defender",
        definition=(
            "Average distance to the nearest defender at the moment of the catch or the "
            "incompletion, on his targets only."
        ),
        interpretation=(
            "Context, not a skill score: deep and contested targets carry less separation by "
            "design, and it says nothing about routes that were not thrown to."
        ),
        limitations=(
            "Targets only, not every route; not proof of isolated receiver skill. Only for "
            "receivers Next Gen Stats qualifies."
        ),
        cohort="ngs",
        num="ngs_separation",
        den="ngs_targets",
        denominator_label="targets (Next Gen Stats)",
    ),
    _m(
        id="avg_cushion",
        label="Cushion at the snap",
        short_label="Cushion",
        kind="context",
        direction="neutral",
        unit="yards",
        decimals=2,
        source="next_gen_stats",
        source_fields=("avg_cushion", "targets", "week == 0"),
        formula="Next Gen Stats season summary: average yards to the aligned defender",
        definition=(
            "Average distance between him and the defender lined up on him at the snap, on "
            "his targets."
        ),
        interpretation="How defences play him at the snap: press or off.",
        limitations="Targets only; a coverage description, not a skill.",
        cohort="ngs",
        num="ngs_cushion",
        den="ngs_targets",
        denominator_label="targets (Next Gen Stats)",
    ),
    # ---------------------------------------------------------------- scoring role
    _m(
        id="red_zone_carries",
        label="Red-zone carries",
        short_label="RZ carries",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "rusher_player_id"),
        formula="his non-kneel carries snapped at yardline_100 <= 20",
        definition="Carries inside the opponent's 20-yard line (kneels and two-point tries out).",
        interpretation="His running role where touchdowns are scored.",
        limitations="A count; it depends on how often his team reaches the red zone.",
        cohort="appearing",
        num="rz_car",
    ),
    _m(
        id="red_zone_carry_share",
        label="Share of team red-zone carries",
        short_label="RZ carry share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "posteam"),
        formula="his red-zone carries / his team's red-zone carries in his games",
        definition=(
            "His share of all his team's non-kneel carries inside the 20 — every position, "
            "quarterback runs included — in the games he played."
        ),
        interpretation="Who gets the ball on the ground near the goal.",
        limitations="Small denominators early in the season.",
        cohort="games",
        num="rz_car",
        den="team_rz_car",
        numerator_label="his red-zone carries",
        denominator_label="team red-zone carries in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="goal_line_carries",
        label="Goal-line carries",
        short_label="GL carries",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "rusher_player_id"),
        formula="his non-kneel carries snapped at yardline_100 <= 5",
        definition="Carries inside the opponent's 5-yard line.",
        interpretation="The short-yardage scoring role.",
        limitations=(
            "Sparse: 79 of 134 running backs had none through week 5 of 2026. A zero is a "
            "real zero."
        ),
        cohort="appearing",
        num="gl_car",
    ),
    _m(
        id="goal_line_carry_share",
        label="Share of team goal-line carries",
        short_label="GL carry share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("rush_attempt", "yardline_100", "play_type", "posteam"),
        formula="his goal-line carries / his team's goal-line carries in his games",
        definition=(
            "His share of his team's non-kneel carries inside the 5, every position included, "
            "in the games he played."
        ),
        interpretation="Who gets the ball at the goal line.",
        limitations="Very small denominators; a team with none in his games has no share.",
        cohort="games",
        num="gl_car",
        den="team_gl_car",
        numerator_label="his goal-line carries",
        denominator_label="team goal-line carries in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="red_zone_targets",
        label="Red-zone targets",
        short_label="RZ targets",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("pass_attempt", "sack", "yardline_100", "receiver_player_id"),
        formula="his targets snapped at yardline_100 <= 20",
        definition="Targets on plays snapped inside the opponent's 20-yard line.",
        interpretation="His receiving role where touchdowns are scored.",
        limitations="A count; it depends on how often his team reaches the red zone.",
        cohort="appearing",
        num="rz_tgt",
    ),
    _m(
        id="red_zone_target_share",
        label="Share of team red-zone targets",
        short_label="RZ tgt share",
        kind="share",
        direction="higher",
        unit="fraction",
        decimals=4,
        source="play_by_play",
        source_fields=("pass_attempt", "sack", "yardline_100", "posteam"),
        formula="his red-zone targets / his team's red-zone targets in his games",
        definition="His share of his team's targets inside the 20 in the games he played.",
        interpretation="How much of the red-zone passing game is aimed at him.",
        limitations="Small denominators early in the season.",
        cohort="games",
        num="rz_tgt",
        den="team_rz_tgt",
        numerator_label="his red-zone targets",
        denominator_label="team red-zone targets in his games",
        minimum=2,
        minimum_unit="games",
    ),
    _m(
        id="end_zone_targets",
        label="End-zone targets",
        short_label="End-zone tgts",
        kind="volume",
        direction="higher",
        unit="count",
        decimals=0,
        source="play_by_play",
        source_fields=("air_yards", "yardline_100", "receiver_player_id"),
        formula="his targets with air_yards >= yardline_100",
        definition=(
            "Targets thrown far enough to reach the goal line (air yards at least the distance "
            "to the end zone). Derived; nflverse has no end-zone flag."
        ),
        interpretation="Throws aimed at a touchdown.",
        limitations="Air yards are measured to where the ball was caught or targeted.",
        cohort="appearing",
        num="ez_tgt",
    ),
)

CATALOG: Mapping[str, Metric] = {
    metric.id: metric for metric in (*_CATALOG_LIST, PRESENCE_METRIC, COMBINE_METRIC)
}


def _branch(branch_id: str, label: str, *nodes: Node) -> Branch:
    return Branch(id=branch_id, label=label, nodes=tuple(nodes))


#: ADR-107's trees, in reading order.
TREES: Mapping[str, tuple[Branch, ...]] = {
    "QB": (
        _branch(
            "passing_volume",
            "Passing volume",
            Node("pass_attempts", ("completions",)),
            Node("passing_yards"),
            Node("passing_tds", ("passing_td_rate",)),
        ),
        _branch(
            "accuracy_depth",
            "Accuracy & depth",
            Node("cpoe", ("completion_pct",)),
            Node("yards_per_attempt"),
            Node("intended_air_yards"),
        ),
        _branch(
            "efficiency_security",
            "Efficiency & ball security",
            Node("pass_epa_per_dropback", ("dropback_success_rate",)),
            Node("sack_rate", ("avg_time_to_throw",)),
            Node("interception_rate"),
        ),
        _branch(
            "legs_scoring",
            "Legs & scoring",
            Node("designed_rushes"),
            Node("scrambles", ("scramble_rate",)),
            Node("rushing_yards", ("rushing_tds",)),
            Node("red_zone_rushes", ("goal_line_rushes", "red_zone_dropbacks")),
        ),
    ),
    "RB": (
        _branch(
            "ground_workload",
            "Ground workload",
            Node("carries", ("rushing_yards", "rushing_tds")),
            Node("carry_share"),
            Node("offense_snap_share"),
        ),
        _branch(
            "rushing_efficiency",
            "Rushing efficiency",
            Node("yards_per_carry", ("rush_epa_per_carry",)),
            Node("rush_success_rate"),
            Node("explosive_run_rate", ("explosive_runs",)),
            Node("rush_yards_over_expected_per_att"),
        ),
        _branch(
            "receiving",
            "Receiving",
            Node("targets", ("receptions", "catch_rate")),
            Node("receiving_yards", ("receiving_tds", "yards_per_target")),
            Node("target_share"),
        ),
        _branch(
            "scoring_role",
            "Scoring role",
            Node("red_zone_carries", ("red_zone_carry_share",)),
            Node("goal_line_carries", ("goal_line_carry_share",)),
            Node("red_zone_targets", ("red_zone_target_share",)),
        ),
    ),
    "WR": (
        _branch(
            "target_earning",
            "Target earning",
            Node("targets", ("receptions",)),
            Node("target_share", ("air_yards_share",)),
            Node("receiving_yards", ("receiving_tds",)),
            Node("offense_snap_share"),
        ),
        _branch(
            "depth_big_plays",
            "Depth & big plays",
            Node("adot"),
            Node("yards_per_reception"),
            Node("explosive_catches", ("explosive_catch_rate",)),
        ),
        _branch(
            "catch_contribution",
            "Catch & contribution",
            Node("catch_rate"),
            Node("rec_epa_per_target", ("yards_per_target",)),
            Node("yac_per_reception"),
            Node("yac_over_expected"),
            Node("avg_separation", ("avg_cushion",)),
        ),
        _branch(
            "scoring_role",
            "Scoring role",
            Node("red_zone_targets", ("red_zone_target_share",)),
            Node("end_zone_targets"),
        ),
    ),
    "TE": (
        _branch(
            "usage",
            "Usage",
            Node("offense_snap_share"),
            Node("target_share", ("air_yards_share",)),
            Node("targets", ("receptions",)),
        ),
        _branch(
            "reliability",
            "Reliability",
            Node("catch_rate"),
            Node("yards_per_target"),
            Node("yac_per_reception"),
            Node("yac_over_expected"),
        ),
        _branch(
            "production",
            "Production",
            Node("receiving_yards", ("receiving_tds",)),
            Node("rec_epa_per_target"),
        ),
        _branch(
            "scoring_depth",
            "Scoring & depth",
            Node("red_zone_targets", ("red_zone_target_share",)),
            Node("end_zone_targets"),
            Node("adot"),
            Node("avg_separation"),
        ),
    ),
}

#: A position's branches, for the definitions' branch order.
BRANCHES: Mapping[str, tuple[str, ...]] = {
    position: tuple(branch.id for branch in branches) for position, branches in TREES.items()
}

#: Running backs rank receiving rates from 10 targets, not 15 (ADR-107 RB table).
POSITION_MINIMUMS: Mapping[tuple[str, str], float] = {
    ("RB", "catch_rate"): 10,
    ("RB", "yards_per_target"): 10,
}


def metric_ids_for(position: str) -> tuple[str, ...]:
    """Every metric in a position's tree — nodes, then their details — in reading order."""
    ids: list[str] = []
    for branch in TREES[position]:
        for node in branch.nodes:
            for metric_id in (node.metric, *node.details):
                if metric_id not in ids:
                    ids.append(metric_id)
    return tuple(ids)


def minimum_for(position: str, metric: Metric) -> float | None:
    return POSITION_MINIMUMS.get((position, metric.id), metric.minimum)
