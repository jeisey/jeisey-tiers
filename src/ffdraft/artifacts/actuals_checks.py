"""Validation of ``season_actuals`` (ADR-105): re-derive what can be re-derived, and agree.

The artifact publishes every appearing QB/RB/WR/TE, so its ranks are checkable from its own
rows: a rank that is not the competition rank of the published points over the published
population cannot pass, and neither can a rate that is not points over games. The
cross-artifact checks then hold it to the numbers the boards print beside it — the same
points to date, the same position, a record for every board player — and the four columns the
in-season boards' CSVs carry are proved to be copies of it.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ffdraft.artifacts.csv_flatten import (
    CSV_COMPANION_ARTIFACTS,
    SEASON_ACTUALS_CSV_COLUMNS,
    actuals_index,
)
from ffdraft.contracts import QualityCheck
from ffdraft.signals.actuals import ACTUALS_POSITIONS, competition_ranks

__all__ = [
    "actuals_csv_checks",
    "actuals_cross_checks",
    "actuals_metadata_checks",
    "actuals_record_checks",
]

#: The published points are 0.01 precise and the boards' to-date points 0.0001 precise.
_POINTS_TOLERANCE = 0.0051

_STAGE = "artifacts.season_actuals"


def _fail(check_id: str, message: str, offenders: Sequence[str], expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=_STAGE,
        message=message,
        observed="; ".join(offenders[:10]) + (" …" if len(offenders) > 10 else ""),
        expected=expected,
    )


def actuals_record_checks(records: Sequence[Mapping[str, Any]], stage: str) -> list[QualityCheck]:
    """Arithmetic, nullness and ranks, re-derived from the artifact's own rows."""
    checks: list[QualityCheck] = []
    nullness: list[str] = []
    arithmetic: list[str] = []
    for record in records:
        key = f"{record.get('scoring_preset')}/{record.get('player_id')}"
        games = int(record.get("games_played") or 0)
        points = float(record.get("points") or 0.0)
        ppg = record.get("points_per_game")
        rank = record.get("season_position_rank")
        if games == 0:
            if ppg is not None or rank is not None or points != 0.0:
                nullness.append(f"{key}: no appearances must mean 0 points, no rate, no rank")
            continue
        if ppg is None or rank is None:
            nullness.append(f"{key}: {games} game(s) but rate {ppg} and rank {rank}")
            continue
        if abs(round(points, 2) - points) > 1e-9:
            arithmetic.append(f"{key}: points {points} not at 0.01 precision")
        if abs(float(ppg) - round(points / games, 2)) > 1e-9:
            arithmetic.append(f"{key}: {ppg} != {points}/{games}")
    if nullness:
        checks.append(
            _fail(
                "season_actuals.nullness",
                "a player with no appearances has 0 points and no rate or rank; any other "
                "player has both",
                nullness,
                "games_played 0 ⇔ points_per_game null ⇔ season_position_rank null",
            ),
        )
    if arithmetic:
        checks.append(
            _fail(
                "season_actuals.arithmetic",
                "points per game must be the published points over the published games",
                arithmetic,
                "points_per_game == round(points / games_played, 2)",
            ),
        )

    # Re-rank every (preset, position) from the published rows.
    groups: dict[tuple[str, str], dict[str, int]] = {}
    published: dict[tuple[str, str, str], int] = {}
    for record in records:
        if int(record.get("games_played") or 0) == 0 or record.get("season_position_rank") is None:
            continue
        group = (str(record["scoring_preset"]), str(record["position"]))
        player = str(record["player_id"])
        groups.setdefault(group, {})[player] = round(float(record["points"]) * 100)
        published[(*group, player)] = int(record["season_position_rank"])
    wrong: list[str] = []
    for group, members in sorted(groups.items()):
        for player, rank in competition_ranks(members).items():
            if published[(*group, player)] != rank:
                wrong.append(
                    f"{group[0]} {group[1]} {player}: {published[(*group, player)]} ≠ {rank}"
                )
    if wrong:
        checks.append(
            _fail(
                "season_actuals.rank_not_rederivable",
                "every season rank must be the competition rank of the published points "
                "within its position and preset",
                wrong,
                "ranks re-derived from the artifact's own rows",
            ),
        )

    # One player, one position and one games count, whatever the preset.
    seen: dict[str, tuple[str, int]] = {}
    presets: dict[str, set[str]] = {}
    drift: list[str] = []
    for record in records:
        player = str(record["player_id"])
        shape = (str(record["position"]), int(record.get("games_played") or 0))
        presets.setdefault(player, set()).add(str(record["scoring_preset"]))
        if seen.setdefault(player, shape) != shape:
            drift.append(f"{player}: {seen[player]} vs {shape}")
    every = set().union(*presets.values()) if presets else set()
    partial = sorted(player for player, held in presets.items() if held != every)
    if drift or partial:
        checks.append(
            _fail(
                "season_actuals.preset_consistency",
                "a player's position and games played do not depend on the scoring preset, "
                "and every player has a record in every published preset",
                [*drift, *(f"{player}: missing a preset" for player in partial)],
                "one position and one games count per player; every preset present",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "season_actuals.records_consistent",
                stage=stage,
                message=(
                    "season actuals re-derive: rates are points over games and every rank is "
                    "the competition rank of the published points within its position"
                ),
                observed=f"{len(records)} record(s) across {len(every)} preset(s)",
            ),
        )
    return checks


def actuals_metadata_checks(
    metadata: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The metadata block must describe the artifact beside it, or its absence."""
    block = metadata.get("season_actuals")
    envelope = envelopes.get("season_actuals")
    stage = "artifacts.ros_build_metadata"
    if block is None:
        if envelope is None:
            return []
        return [
            QualityCheck.fail(
                "ros_build_metadata.season_actuals_undescribed",
                stage=stage,
                message="season_actuals.json is published without its definitions and cutoff",
                observed="metadata season_actuals null",
                expected="a season_actuals block",
            ),
        ]
    records = list((envelope or {}).get("records", ()))
    problems: list[str] = []
    status = block.get("status")
    if status == "published" and envelope is None:
        problems.append("status published but no season_actuals.json")
    if status == "withheld" and envelope is not None:
        problems.append("status withheld but season_actuals.json is present")
    if int(block.get("records", -1)) != len(records):
        problems.append(f"records {block.get('records')} vs artifact {len(records)}")
    if int(block.get("through_week", -1)) != int(metadata.get("through_week", -2)):
        problems.append(
            f"through_week {block.get('through_week')} vs board {metadata.get('through_week')}",
        )
    if envelope is not None:
        population: dict[str, set[str]] = {position: set() for position in ACTUALS_POSITIONS}
        for record in records:
            if int(record.get("games_played") or 0) > 0:
                population[str(record["position"])].add(str(record["player_id"]))
        declared = block.get("population") or {}
        for position in ACTUALS_POSITIONS:
            if int(declared.get(position, -1)) != len(population[position]):
                problems.append(
                    f"population {position} {declared.get(position)} vs "
                    f"{len(population[position])} appearing",
                )
    if problems:
        return [
            QualityCheck.fail(
                "ros_build_metadata.season_actuals_mismatch",
                stage=stage,
                message="the season-actuals block disagrees with the artifact it describes",
                observed="; ".join(problems),
                expected="status, record count, cutoff and populations agree",
            ),
        ]
    return [
        QualityCheck.ok(
            "ros_build_metadata.season_actuals",
            stage=stage,
            message="the season-actuals block describes the artifact beside it",
            observed=f"status {status}; {len(records)} record(s)",
        ),
    ]


def actuals_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Agreement with every board that prints a number beside the actuals."""
    envelope = envelopes.get("season_actuals")
    if envelope is None:
        return []
    index = actuals_index(list(envelope.get("records", ())))
    problems: dict[str, list[str]] = {
        "coverage": [],
        "position": [],
        "points": [],
        "games": [],
    }
    for artifact in ("ros_tiers", "inseason_opportunity", "weekly_projections"):
        for record in envelopes.get(artifact, {}).get("records", ()):
            player = str(record.get("player_id"))
            if not player.startswith("gsis:"):
                continue
            actual = index.get((str(record.get("scoring_preset")), player))
            if actual is None:
                problems["coverage"].append(f"{artifact} {record.get('scoring_preset')}/{player}")
                continue
            if record.get("position") and str(record["position"]) != str(actual["position"]):
                problems["position"].append(
                    f"{artifact} {player}: {record['position']} vs {actual['position']}",
                )
            if artifact == "ros_tiers":
                to_date = record.get("points_to_date")
                if to_date is not None and abs(float(to_date) - float(actual["points"])) > (
                    _POINTS_TOLERANCE
                ):
                    problems["points"].append(
                        f"{record.get('scoring_preset')}/{player}: board {to_date} vs "
                        f"actuals {actual['points']}",
                    )
                model_games = float(record.get("games_played_to_date") or 0.0)
                if int(actual["games_played"]) < model_games:
                    problems["games"].append(
                        f"{player}: {actual['games_played']} appearance(s) < model's "
                        f"{model_games:g} stats-row games",
                    )
    for usage in envelopes.get("player_usage", {}).get("records", ()):
        player = str(usage.get("player_id"))
        for preset, total in (usage.get("fantasy_points_to_date") or {}).items():
            actual = index.get((str(preset), player))
            if actual is None or total is None:
                continue
            if int(actual["games_played"]) != int(usage.get("appearances") or 0):
                problems["games"].append(
                    f"{player}: actuals {actual['games_played']} vs usage "
                    f"{usage.get('appearances')} appearance(s)",
                )
            if abs(float(total) - float(actual["points"])) > _POINTS_TOLERANCE:
                problems["points"].append(
                    f"{preset}/{player}: usage {total} vs actuals {actual['points']}",
                )
    checks: list[QualityCheck] = []
    messages = {
        "coverage": (
            "season_actuals.board_player_missing",
            "every board player must have a season-actuals record in his preset",
        ),
        "position": (
            "season_actuals.position_disagrees",
            "a season rank must be ranked within the position the board prints",
        ),
        "points": (
            "season_actuals.points_disagree",
            "season points must equal the points to date the boards and the week strip print",
        ),
        "games": (
            "season_actuals.games_disagree",
            "games played must equal the usage layer's appearances and be at least the "
            "model's stats-row games",
        ),
    }
    for kind, offenders in problems.items():
        if offenders:
            check_id, message = messages[kind]
            checks.append(_fail(check_id, message, sorted(set(offenders)), "agreement"))
    if not checks:
        checks.append(
            QualityCheck.ok(
                "season_actuals.agrees_with_boards",
                stage=_STAGE,
                message=(
                    "every board player has season actuals at his board position, with the "
                    "same points to date and the usage layer's appearances"
                ),
                observed=f"{len(index)} record(s)",
            ),
        )
    return checks


def actuals_csv_checks(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
    csv_filenames: Mapping[str, str],
) -> list[QualityCheck]:
    """The in-season boards' CSV actuals columns are copies of the artifact (or empty)."""
    index = actuals_index(list(envelopes.get("season_actuals", {}).get("records", ())))
    checks: list[QualityCheck] = []
    for artifact in sorted(CSV_COMPANION_ARTIFACTS):
        filename = csv_filenames.get(artifact)
        if artifact not in envelopes or filename is None:
            continue
        path = directory / filename
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        wrong: list[str] = []
        for row in rows:
            actual = index.get((row.get("scoring_preset", ""), row.get("player_id", "")))
            for column, source in SEASON_ACTUALS_CSV_COLUMNS:
                value = None if actual is None else actual.get(source)
                expected = "" if value is None else str(value)
                if row.get(column, "") != expected:
                    wrong.append(
                        f"{row.get('scoring_preset')}/{row.get('player_id')} {column}: "
                        f"{row.get(column)!r} vs {expected!r}",
                    )
        if wrong:
            checks.append(
                QualityCheck.fail(
                    "artifact.csv_actuals_disagree",
                    stage=f"artifacts.{artifact}",
                    message=f"{filename}'s season columns must copy season_actuals.json",
                    observed="; ".join(wrong[:10]),
                    expected="identical values, empty where no actuals were published",
                ),
            )
        else:
            checks.append(
                QualityCheck.ok(
                    "artifact.csv_actuals_agree",
                    stage=f"artifacts.{artifact}",
                    message=f"{filename}'s season columns copy season_actuals.json",
                    observed=f"{len(rows)} row(s)",
                ),
            )
    return checks
