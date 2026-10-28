"""Story wording: predictable templates over a story's structured evidence, and nothing else.

Every function here reads only the ``evidence`` dict a family built (plus the story's fixed
labels), so a story's words can never say something its numbers do not. Numbers are printed
with three formatters — points to one decimal, shares as whole percentages, counts and ranks
as integers — and the validator (``insights.text_number_not_in_evidence``) checks that every
number in a headline, dek, fact, counterpoint or caveat is one of the evidence's own values in
one of those formats. Observed statistics, model outputs and ESPN readings are tagged in each
fact's ``basis``; the dek is the editorial reading and the page labels it so.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["pct", "pts", "render", "window_label"]


def pts(value: float | None) -> str:
    """Points (or a per-game rate) to one decimal."""
    return "—" if value is None else f"{float(value):.1f}"


def pct(share: float | None) -> str:
    """A share in [0, 1] as a whole percentage."""
    return "—" if share is None else f"{round(float(share) * 100)}%"


def count(value: float | int | None) -> str:
    return "—" if value is None else f"{round(float(value))}"


def rostered(value: float | None) -> str:
    """ESPN's percent rostered: whole numbers from 10%, one decimal below (0.3% is not 0%)."""
    if value is None:
        return "—"
    return f"{round(float(value))}%" if float(value) >= 10 else f"{float(value):.1f}%"


def window_label(first: int, last: int) -> str:
    return f"W{first}" if first == last else f"W{first}–W{last}"


def _games(n: int) -> str:
    return f"{n} game" if n == 1 else f"{n} games"


def _metric_name(metric: str) -> str:
    return {
        "target_share": "target share",
        "carry_share": "carry share",
        "snap_share": "snap share",
        "pass_attempts": "pass attempts a game",
        "opportunity_share": "share of team carries and targets",
    }.get(metric, metric.replace("_", " "))


def _measure(metric: str, value: float | None) -> str:
    return pts(value) if metric == "pass_attempts" else pct(value)


def _unit(position: str) -> str:
    return "opportunities" if position == "RB" else "targets"


def _direction(before: float, after: float) -> str:
    """'down from', 'up from' or 'level at …' — the words follow the numbers."""
    if round(after, 1) < round(before, 1):
        return "down from"
    if round(after, 1) > round(before, 1):
        return "up, though his share fell, from"
    return "unchanged, though his share fell, from"


def _signed(value: float) -> str:
    return f"+{pts(value)}" if value >= 0 else f"−{pts(abs(value))}"


TERM_NAMES: Mapping[str, str] = {
    "lines": "the betting lines",
    "home": "home field",
    "rest": "rest",
    "roof": "the roof",
    "opponent": "the opponent",
}


# --------------------------------------------------------------------------- families


def _volume_lagging(e: Mapping[str, Any]) -> dict[str, Any]:
    pos, wl, unit = e["position"], e["window_label"], _unit(e["position"])
    facts = [
        {
            "label": f"{unit.capitalize()} a game, {wl}",
            "value": f"{pts(e['window_opportunities_per_game'])} ({pos}{e['workload_rank']})",
            "basis": "observed",
        },
        {
            "label": f"Points a game, {wl}",
            "value": f"{pts(e['window_points_per_game'])} ({pos}{e['production_rank']})",
            "basis": "observed",
        },
    ]
    if e.get("window_share") is not None:
        facts.append(
            {
                "label": f"{_metric_name(e['share_metric']).capitalize()}, {wl}",
                "value": pct(e["window_share"]),
                "basis": "observed",
            },
        )
    if e.get("red_zone_opportunities") is not None and e.get("team_red_zone_opportunities"):
        facts.append(
            {
                "label": f"Red-zone {unit}, {wl}",
                "value": (
                    f"{count(e['red_zone_opportunities'])} of "
                    f"{count(e['team_red_zone_opportunities'])}"
                ),
                "basis": "observed",
            },
        )
    else:
        facts.append(
            {
                "label": f"Touchdown points, {wl}",
                "value": f"{pts(e['window_td_points'])} of {pts(e['window_points'])}",
                "basis": "observed",
            },
        )
    counterpoint = None
    ypo, median = e.get("yards_per_opportunity"), e.get("cohort_median_yards_per_opportunity")
    if ypo is not None and median is not None and ypo < median:
        counterpoint = (
            f"His {pts(ypo)} yards per {'opportunity' if pos == 'RB' else 'target'} trail the "
            f"{pos} median of {pts(median)} in these weeks, so the gap is not only touchdowns."
        )
    elif e["window_opportunities_per_game"] < e["baseline_opportunities_per_game"]:
        counterpoint = (
            f"His {pts(e['window_opportunities_per_game'])} {unit} a game are below the "
            f"{pts(e['baseline_opportunities_per_game'])} he averaged before {wl}."
        )
    return {
        "headline": (
            f"{e['name']}: {pts(e['window_opportunities_per_game'])} {unit} a game "
            f"({pos}{e['workload_rank']}), {pts(e['window_points_per_game'])} points a game "
            f"({pos}{e['production_rank']})"
        ),
        "dek": (
            f"Over {wl} his workload ranks {pos}{e['workload_rank']} of {e['cohort_size']} "
            f"{pos}s, but his scoring ranks {pos}{e['production_rank']}. The role has held; "
            "the results have trailed it, which is a reason for patience rather than a cut."
        ),
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": (
            "Three weeks of usage and scoring, described rather than forecast: a workload gap "
            "is not a promise of points."
        ),
    }


def _volume_shrinking(e: Mapping[str, Any]) -> dict[str, Any]:
    wl, unit = e["window_label"], _unit(e["position"])
    before, after = e["baseline_opportunities_per_game"], e["window_opportunities_per_game"]
    metric = _metric_name(e["share_metric"])
    facts = [
        {
            "label": f"{metric.capitalize()}, before → {wl}",
            "value": f"{pct(e['baseline_share'])} → {pct(e['window_share'])}",
            "basis": "observed",
        },
        {
            "label": f"{unit.capitalize()} a game, before → {wl}",
            "value": (
                f"{pts(e['baseline_opportunities_per_game'])} → "
                f"{pts(e['window_opportunities_per_game'])}"
            ),
            "basis": "observed",
        },
        {
            "label": f"Points a game, before → {wl}",
            "value": f"{pts(e['baseline_points_per_game'])} → {pts(e['window_points_per_game'])}",
            "basis": "observed",
        },
    ]
    if e.get("snap_share_window") is not None and e.get("snap_share_baseline") is not None:
        facts.append(
            {
                "label": f"Snap share, before → {wl}",
                "value": f"{pct(e['snap_share_baseline'])} → {pct(e['snap_share_window'])}",
                "basis": "observed",
            },
        )
    counterpoint = None
    if e["window_games"] <= 2:
        counterpoint = (
            f"{_games(e['window_games']).capitalize()} in the window: one game script can move "
            "a share."
        )
    elif (
        e.get("snap_share_window") is not None
        and e.get("snap_share_baseline") is not None
        and abs(e["snap_share_window"] - e["snap_share_baseline"]) < 0.05
    ):
        counterpoint = (
            f"His snap share held at {pct(e['snap_share_window'])}: he is still on the field, "
            "with fewer of the looks."
        )
    return {
        "headline": (
            f"{e['name']}'s {metric} fell from {pct(e['baseline_share'])} to "
            f"{pct(e['window_share'])} over {wl}"
        ),
        "dek": (
            "A shrinking share is a smaller role, not a cold streak: 'he still gets the ball' "
            f"no longer holds for these weeks, with {unit} a game "
            f"{_direction(before, after)} "
            f"{pts(e['baseline_opportunities_per_game'])} to "
            f"{pts(e['window_opportunities_per_game'])}."
        ),
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": (
            "Shares pool his games against his team's; three weeks against his earlier games "
            "is a small sample."
        ),
    }


def _upside(e: Mapping[str, Any]) -> dict[str, Any]:
    pos, ceiling = e["position"], e["ceiling"]
    delta = e.get("matchup_delta_q90")
    if delta is None:
        matchup = "The model has no typical-week account for this game."
    elif abs(delta) < 0.5:
        matchup = "The matchup changes his ceiling little against his typical week."
    else:
        terms = e.get("terms_q90") or {}
        top = max(terms, key=lambda key: (abs(float(terms[key])), key)) if terms else None
        driver = f", mostly {TERM_NAMES.get(top, top)}" if top else ""
        matchup = (
            f"The matchup moves his ceiling {_signed(delta)} against his typical week{driver}."
        )
    role = (
        f"{_metric_name(e['role_metric']).capitalize()}, last {e['role_games']} games"
        if e["role_metric"] != "pass_attempts"
        else f"Pass attempts a game, last {e['role_games']} games"
    )
    facts = [
        {
            "label": "Ceiling / median / floor (P90 / P50 / P10)",
            "value": f"{pts(e['q90'])} / {pts(e['q50'])} / {pts(e['q10'])}",
            "basis": "model",
        },
        {"label": role, "value": _measure(e["role_metric"], e["role_level"]), "basis": "observed"},
        {"label": "Rostered on ESPN", "value": rostered(e["espn_rostered"]), "basis": "market"},
    ]
    if delta is not None:
        facts.append(
            {"label": "Matchup vs typical week (P90)", "value": _signed(delta), "basis": "model"}
        )
    injury = e.get("injury") or {}
    if injury.get("designation") == "Questionable":
        counterpoint = f"Listed Questionable for week {e['target_week']} on the official report."
    elif e["q10"] <= 2.0:
        counterpoint = f"His floor (P10) is {pts(e['q10'])} points: one week in ten at or below it."
    else:
        counterpoint = (
            f"His median week is {pts(e['q50'])} points: this is a ceiling bet, not a safe start."
        )
    return {
        "headline": (
            f"{e['name']}: a {pts(e['q90'])}-point ceiling at "
            f"{rostered(e['espn_rostered'])} rostered"
        ),
        "dek": (
            f"No. {e['ceiling_rank']} by week-{e['target_week']} ceiling of {e['eligible']} {pos}s "
            f"with a confirmed role and under {ceiling}% rostered on ESPN. {matchup}"
        ),
        "facts": facts,
        "counterpoint": counterpoint,
        "caveat": (
            f"P{e['ceiling_level']}: one week in ten at or above it, per the weekly model — not "
            f"a {e['ceiling_level']}% chance. ESPN share describes ESPN leagues, not yours."
        ),
    }


def _opening(e: Mapping[str, Any], variant: str) -> dict[str, Any]:
    unit = {"target_share": "targets", "carry_share": "carries", "pass_share": "pass attempts"}[
        e["metric"]
    ]
    absent, focal, team = e["absent_name"], e["name"], e["team"]
    # His own games without the absent player, and his club's: a different count whenever he
    # missed one of them too.
    n_without = e["games_without"]
    team_without = e["team_games_without"]
    rose = e.get("share_with") is not None and e.get("share_without") is not None
    facts = [
        {
            "label": f"{absent}'s share of {team} {unit}",
            "value": f"{pct(e['absent_share'])} over {_games(e['absent_games'])}",
            "basis": "observed",
        },
    ]
    if n_without:
        facts.append(
            {
                "label": f"{focal} without him",
                "value": f"{pct(e['share_without'])} ({_games(n_without)})",
                "basis": "observed",
            },
        )
    if e.get("games_with"):
        facts.append(
            {
                "label": f"{focal} with him",
                "value": f"{pct(e['share_with'])} ({_games(e['games_with'])})",
                "basis": "observed",
            },
        )
    if len(facts) < 3 and e.get("latest_share") is not None:
        facts.append(
            {
                "label": f"{focal}'s share, {e['window_label']}",
                "value": pct(e["latest_share"]),
                "basis": "observed",
            },
        )
    if e.get("espn_rostered") is not None and len(facts) < 4:
        facts.append(
            {"label": "Rostered on ESPN", "value": rostered(e["espn_rostered"]), "basis": "market"}
        )
    if team_without == 0:
        counterpoint = (
            f"{team} has not played without him this season, so how his "
            f"{pts(e['absent_per_game'])} {unit} a game will move is unknown."
        )
    elif n_without == 0:
        counterpoint = (
            f"{focal} has not played in {team}'s {_games(team_without)} without him, so his "
            "share without him is not known."
        )
    elif n_without <= 2:
        counterpoint = (
            f"{_games(n_without).capitalize()} without him: opponents and game script move shares "
            "as much as an absence does."
        )
    else:
        counterpoint = None
    played = (
        f"{team}'s {_games(team_without)} without him"
        if n_without == team_without
        else f"the {_games(n_without)} he played of {team}'s {team_without} without him"
    )
    if variant == "prospective":
        headline = f"{absent} ({pct(e['absent_share'])} of {team} {unit}) is {e['absent_reason']}"
        if n_without:
            dek = (
                f"In {played}, {focal} took {pct(e['share_without'])} of the {unit}"
                + (f", against {pct(e['share_with'])} with him." if rose else ".")
                + (" Who absorbs the rest is not known." if e["share_without"] < 0.95 else "")
            )
        else:
            dek = (
                f"That leaves {pts(e['absent_per_game'])} {unit} a game unassigned. {focal} has "
                f"{pct(e['latest_share'])} of them over {e['window_label']}; who absorbs the rest "
                "is not known."
            )
    else:
        headline = (
            f"Without {absent}, {focal}'s share of {team} {unit} rose to {pct(e['share_without'])}"
            if rose
            else f"Without {absent}, {focal} has {pct(e['share_without'])} of {team} {unit}"
        )
        dek = (
            f"{absent} {e['absent_reason']}. In {played}, {focal} took "
            f"{pct(e['share_without'])} of the {unit}"
            + (f", against {pct(e['share_with'])} alongside him." if rose else ".")
        )
    return {
        "headline": headline,
        "dek": dek,
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": (
            "This shows what happened in games he missed, or who is next by share; vacated "
            "work is not assigned to anyone."
        ),
    }


def _role(e: Mapping[str, Any]) -> dict[str, Any]:
    unit = e["metric"]
    room = "backfield" if unit == "carries" else "receiving room"
    wl, team = e["window_label"], e["team"]
    facts = [
        {
            "label": f"{e['name']}, {wl}",
            "value": f"{count(e['riser_count'])} of {count(e['team_count'])} {unit}",
            "basis": "observed",
        },
        {
            "label": f"{e['name']}'s share, before → {wl}",
            "value": f"{pct(e['riser_share_baseline'])} → {pct(e['riser_share'])}",
            "basis": "observed",
        },
    ]
    if e.get("other_name"):
        facts.append(
            {
                "label": f"{e['other_name']}, {wl}",
                "value": f"{count(e['other_count'])} of {count(e['team_count'])} {unit}",
                "basis": "observed",
            },
        )
    if e.get("riser_snap_share") is not None:
        facts.append(
            {
                "label": f"{e['name']}'s snap share, {wl}",
                "value": pct(e["riser_snap_share"]),
                "basis": "observed",
            },
        )
    counterpoint = None
    if e.get("absent_member"):
        counterpoint = (
            f"{e['absent_member']} played {e['absent_member_games']} of {team}'s "
            f"{_games(e['team_games'])} in {wl}, so part of the shift is his absence."
        )
    elif e["riser_games"] <= 2:
        counterpoint = f"{e['name']} has {_games(e['riser_games'])} in the window: a small sample."
    other = f"; {e['other_name']} took {count(e['other_count'])}" if e.get("other_name") else ""
    return {
        "headline": (
            f"{team} {room}: {e['name']}'s share of {unit} rose from "
            f"{pct(e['riser_share_baseline'])} to {pct(e['riser_share'])}"
        ),
        "dek": (
            f"Over {wl}, {e['name']} took {count(e['riser_count'])} of {team}'s "
            f"{count(e['team_count'])} {unit}{other}. A change in who gets the ball shows "
            "in the share before it shows in a season total."
        ),
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": (
            f"Shares are of {team}'s {unit} in its games. Snap shares overlap — players share "
            "the field — so they do not add to 100%."
        ),
    }


def _streak(e: Mapping[str, Any], variant: str) -> dict[str, Any]:
    pos, wl, band = e["position"], e["window_label"], e["band"]
    measure = _metric_name(e["measure"]) if e.get("measure") else None
    facts = [
        {
            "label": f"Points rank, {wl} → season",
            "value": f"{pos}{e['window_rank']} → {pos}{e['season_rank']}"
            if e.get("season_rank")
            else f"{pos}{e['window_rank']}",
            "basis": "observed",
        },
        {
            "label": f"Points a game, {wl}",
            "value": pts(e["window_points_per_game"]),
            "basis": "observed",
        },
    ]
    if measure and e.get("level") is not None:
        value = _measure(e["measure"], e["level"])
        if e.get("baseline") is not None:
            value = f"{_measure(e['measure'], e['baseline'])} → {value}"
        facts.append(
            {"label": f"{measure.capitalize()}, before → {wl}", "value": value, "basis": "observed"}
        )
    if e.get("td_share") is not None:
        facts.append(
            {
                "label": f"Points from touchdowns, {wl}",
                "value": f"{e['td_share']}%",
                "basis": "observed",
            },
        )
    td_led = e.get("td_share") is not None and e["td_share"] >= e["td_led_percent"]
    if variant == "breakout":
        category = str(e["category"]).capitalize()
        headline = f"{e['name']}: {e['streak']} straight top-{band} {pos} weeks"
        dek = (
            f"{category} (breakout_v1): {pos}{e['window_rank']} over {wl}"
            + (f" after {pos}{e['season_rank']} for the season" if e.get("season_rank") else "")
            + (
                f", with his {measure} at {_measure(e['measure'], e['level'])} in those games."
                if measure and e.get("level") is not None
                else "."
            )
        )
        counterpoint = (
            f"{e['td_share']}% of his {wl} points came from touchdowns." if td_led else None
        )
    elif variant == "production_without_role":
        headline = (
            f"{e['name']}: {e['streak']} top-{band} {pos} weeks in a row, but his {measure} is "
            f"{_measure(e['measure'], e['level'])}"
        )
        dek = "Production jumped; usage did not reach breakout_v1's role bar. " + (
            f"{e['td_share']}% of his {wl} points came from touchdowns."
            if td_led
            else "Repeating it rests on efficiency rather than a bigger role."
        )
        counterpoint = "His role may still be growing: two or three games is a short read on usage."
    else:
        headline = (
            f"{e['name']}'s {measure} rose from {_measure(e['measure'], e['baseline'])} to "
            f"{_measure(e['measure'], e['level'])} before the points did"
        )
        dek = (
            f"Over {wl} his role passed breakout_v1's growth bar while his scoring ranks "
            f"{pos}{e['window_rank']}. The points have not followed the role yet."
        )
        counterpoint = (
            f"{_games(e['window_games']).capitalize()} in the window: a small sample."
            if e["window_games"] <= 2
            else None
        )
    return {
        "headline": headline,
        "dek": dek,
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": "A descriptive reading from fixed thresholds over three weeks; not a prediction.",
    }


def _pace(e: Mapping[str, Any], variant: str) -> dict[str, Any]:
    pos = e["position"]
    facts = [
        {
            "label": "Points a game",
            "value": f"{pts(e['points_per_game'])} ({pos}{e['ppg_rank']})",
            "basis": "observed",
        },
        {
            "label": "Games played",
            "value": f"{e['games']} of {e['team_games']}",
            "basis": "observed",
        },
        {
            "label": f"{e['pace_games']}-game pace (PPG × {e['pace_games']})",
            "value": pts(e["pace"]),
            "basis": "observed",
        },
    ]
    if variant == "overlooked":
        facts.append(
            {"label": "Rostered on ESPN", "value": rostered(e["espn_rostered"]), "basis": "market"}
        )
        headline = (
            f"{e['name']} is {pos}{e['ppg_rank']} in points a game and "
            f"{rostered(e['espn_rostered'])} rostered"
        )
        dek = (
            f"{pts(e['points_per_game'])} points a game over {_games(e['games'])} ranks "
            f"{pos}{e['ppg_rank']} of {e['cohort_size']} {pos}s with "
            f"{e['cohort_min_games']}+ games, "
            "yet most ESPN leagues leave him unrostered."
        )
        counterpoint = (
            f"{_games(e['games']).capitalize()} is a small sample." if e["games"] <= 4 else None
        )
    else:
        facts.append(
            {
                "label": "Season points",
                "value": f"{pts(e['points'])} ({pos}{e['total_rank']})",
                "basis": "observed",
            },
        )
        headline = (
            f"{e['name']}: {pos}{e['ppg_rank']} in points a game, {pos}{e['total_rank']} in total"
        )
        dek = (
            f"He has played {e['games']} of his team's {e['team_games']} games. Among "
            f"{e['cohort_size']} {pos}s with {e['cohort_min_games']}+ games he averages "
            f"{pts(e['points_per_game'])}; the total rank reflects the games he missed."
        )
        counterpoint = (
            f"He missed {e['missed_games']} of his team's games: availability is part of "
            "a season's value."
        )
    return {
        "headline": headline,
        "dek": dek,
        "facts": facts[:4],
        "counterpoint": counterpoint,
        "caveat": (
            f"Pace is arithmetic (points a game × {e['pace_games']}), not a projection; it assumes "
            "games he may not play."
        ),
    }


def render(family: str, variant: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Headline, dek, facts, counterpoint and caveat for one story, from its evidence alone."""
    if family == "volume_vs_results":
        return _volume_lagging(evidence) if variant == "lagging" else _volume_shrinking(evidence)
    if family == "weekly_upside":
        return _upside(evidence)
    if family == "opportunity_opening":
        return _opening(evidence, variant)
    if family == "role_battle":
        return _role(evidence)
    if family == "streak_watch":
        return _streak(evidence, variant)
    if family == "pace_perspective":
        return _pace(evidence, variant)
    raise ValueError(f"unknown family {family!r}")
