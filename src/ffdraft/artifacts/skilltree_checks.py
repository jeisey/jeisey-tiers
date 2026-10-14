"""Validation of the Skill Tree artifacts (ADR-107): re-derive what can be re-derived, and agree.

Every reading carries its sample, so most of the artifact is checkable from its own rows:

* a state must agree with its value, sample, rank and cohort (a missing value is never 0, a
  rank exists only for ``ranked``);
* every rank and percentile is re-derived from the published values of its cohort, with the
  definition's direction and precision — a rank that is not the competition rank of the
  published values over the published cohort cannot pass;
* a rate or share must equal its published numerator over its denominator;
* every reading needs a definition, and every appearing player carries his position's whole
  tree.

The cross-artifact checks then hold it to the numbers printed beside it on the same card: the
same games and position as the season actuals, a presence record for every board player, and
the same targets, carries and attempts as the usage layer's week-by-week series.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ffdraft.contracts import QualityCheck
from ffdraft.signals.skilltree import MIN_COHORT, percentile_ranks

__all__ = [
    "skilltree_cross_checks",
    "skilltree_definition_checks",
    "skilltree_metadata_checks",
    "skilltree_record_checks",
]

_STAGE = "artifacts.player_skill_tree"
_EMPTY_STATES = frozenset({"no_opportunity", "not_covered", "unavailable"})
#: A rate is published at its definition's decimals; its sides at three. One unit in the last
#: published place, plus the sides' own rounding.
_RATE_TOLERANCE = {0: 0.51, 1: 0.051, 2: 0.0051, 3: 0.00051, 4: 0.000051}


def _fail(check_id: str, message: str, offenders: Sequence[str], expected: str) -> QualityCheck:
    return QualityCheck.fail(
        check_id,
        stage=_STAGE,
        message=message,
        observed="; ".join(offenders[:10]) + (" …" if len(offenders) > 10 else ""),
        expected=expected,
    )


def skilltree_record_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """Each reading's state against its own value, sample, rank and cohort."""
    problems: list[str] = []
    duplicates: list[str] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        key = (str(record.get("player_id")), str(record.get("metric_id")))
        label = f"{key[0]}/{key[1]}"
        if key in seen:
            duplicates.append(label)
        seen.add(key)
        state = record.get("state")
        value = record.get("value")
        rank = record.get("rank")
        percentile = record.get("percentile")
        cohort = record.get("cohort_size")
        if state in _EMPTY_STATES and value is not None:
            problems.append(f"{label}: {state} with a value")
        if state not in _EMPTY_STATES and value is None:
            problems.append(f"{label}: {state} without a value")
        if (rank is None) != (state != "ranked") or (percentile is None) != (state != "ranked"):
            problems.append(f"{label}: rank/percentile do not match state {state}")
        if (cohort is None) != (state not in ("ranked", "small_cohort")):
            problems.append(f"{label}: cohort size does not match state {state}")
        if state == "ranked" and isinstance(rank, int) and isinstance(cohort, int):
            if rank > cohort:
                problems.append(f"{label}: rank {rank} of {cohort}")
            if cohort < MIN_COHORT:
                problems.append(f"{label}: ranked within a cohort of {cohort}")
        if state == "small_cohort" and isinstance(cohort, int) and cohort >= MIN_COHORT:
            problems.append(f"{label}: small_cohort with {cohort} qualified")
        if state in ("unavailable", "not_covered") and not record.get("reason"):
            problems.append(f"{label}: {state} without a reason")
        if state == "no_opportunity" and record.get("denominator") not in (0, 0.0, None):
            problems.append(f"{label}: no_opportunity with denominator {record.get('denominator')}")
        if state == "no_appearances" and (key[1] != "appearances" or value != 0):
            problems.append(f"{label}: no_appearances on a reading")
        if int(record.get("games") or 0) == 0 and key[1] != "appearances":
            problems.append(f"{label}: a reading for a player with no games")
    checks: list[QualityCheck] = []
    if duplicates:
        checks.append(
            _fail(
                "player_skill_tree.duplicate_reading",
                "a player carries the same metric twice",
                duplicates,
                "one record per player per metric",
            ),
        )
    if problems:
        checks.append(
            _fail(
                "player_skill_tree.state_inconsistent",
                "a reading's state disagrees with its value, sample, rank or cohort",
                problems,
                "ADR-107's seven states, each with exactly its own fields",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "player_skill_tree.states",
                stage=stage,
                message="every reading's state agrees with its value, sample, rank and cohort",
                observed=f"{len(records)} reading(s)",
            ),
        )
    return checks


def skilltree_definition_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """One definition per position × metric; every detail's parent is a node of its branch."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    nodes: dict[str, dict[str, str | None]] = {}
    for record in records:
        key = (str(record.get("position")), str(record.get("metric_id")))
        if key in seen:
            problems.append(f"{key[0]}/{key[1]} defined twice")
        seen.add(key)
        if record.get("role") == "node":
            nodes.setdefault(key[0], {})[key[1]] = record.get("branch_id")
    for record in records:
        if record.get("role") != "detail":
            continue
        position = str(record.get("position"))
        parent = record.get("parent_metric_id")
        if parent not in nodes.get(position, {}):
            problems.append(f"{position}/{record.get('metric_id')}: parent {parent} is not a node")
        elif nodes[position][str(parent)] != record.get("branch_id"):
            problems.append(f"{position}/{record.get('metric_id')}: parent in another branch")
    for position, metrics in nodes.items():
        if not 10 <= len(metrics) <= 16:
            problems.append(f"{position}: {len(metrics)} nodes")
    if problems:
        return [
            _fail(
                "skill_tree_definitions.inconsistent",
                "the tree's definitions are not one coherent tree per position",
                problems,
                "one definition per position × metric; 10-16 nodes; details under their node",
            ),
        ]
    return [
        QualityCheck.ok(
            "skill_tree_definitions.coherent",
            stage=stage,
            message="one definition per position × metric, every detail under a node",
            observed=", ".join(f"{p} {len(m)} nodes" for p, m in sorted(nodes.items())),
        ),
    ]


def skilltree_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Ranks, rates and coverage re-derived, then agreement with the card's other numbers."""
    tree = envelopes.get("player_skill_tree")
    definitions = envelopes.get("skill_tree_definitions")
    if tree is None and definitions is None:
        return []
    if tree is None or definitions is None:
        return [
            _fail(
                "player_skill_tree.half_published",
                "the Skill Tree's readings and definitions must be published together",
                [f"readings {tree is not None}", f"definitions {definitions is not None}"],
                "both or neither",
            ),
        ]
    records = list(tree.get("records", ()))
    defs = {
        (str(row["position"]), str(row["metric_id"])): row for row in definitions.get("records", ())
    }
    checks: list[QualityCheck] = []

    # Every reading defined; every appearing player carries his whole tree.
    undefined: list[str] = []
    incomplete: list[str] = []
    by_player: dict[str, set[str]] = {}
    games: dict[str, int] = {}
    positions: dict[str, str] = {}
    for record in records:
        player = str(record["player_id"])
        position = str(record["position"])
        if (position, str(record["metric_id"])) not in defs:
            undefined.append(f"{player}/{record['metric_id']}")
        by_player.setdefault(player, set()).add(str(record["metric_id"]))
        games[player] = int(record.get("games") or 0)
        positions[player] = position
    expected: dict[str, set[str]] = {}
    for (position, metric_id), _row in defs.items():
        expected.setdefault(position, set()).add(metric_id)
    for player, held in by_player.items():
        if games[player] == 0:
            if held != {"appearances"}:
                incomplete.append(f"{player}: no games but {sorted(held - {'appearances'})[:3]}")
            continue
        missing = expected.get(positions[player], set()) - held
        if missing:
            incomplete.append(f"{player}: missing {sorted(missing)[:4]}")
    if undefined:
        checks.append(
            _fail(
                "player_skill_tree.undefined_metric",
                "a reading has no definition for its position",
                undefined,
                "a definition for every published reading",
            ),
        )
    if incomplete:
        checks.append(
            _fail(
                "player_skill_tree.incomplete_tree",
                "an appearing player is missing part of his position's tree",
                incomplete,
                "every metric of his position for every player with games",
            ),
        )

    # Rates and shares equal their published sides; ranks re-derive from published values.
    arithmetic: list[str] = []
    cohorts: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for record in records:
        definition = defs.get((str(record["position"]), str(record["metric_id"])))
        if definition is None:
            continue
        state = record.get("state")
        if state in ("ranked", "small_cohort") and record["metric_id"] != "combine_forty":
            cohorts.setdefault((str(record["position"]), str(record["metric_id"])), {})[
                str(record["player_id"])
            ] = record
        numerator, denominator, value = (
            record.get("numerator"),
            record.get("denominator"),
            record.get("value"),
        )
        if (
            definition["kind"] in ("rate", "share")
            and definition["source_id"] != "next_gen_stats"
            and value is not None
            and isinstance(numerator, int | float)
            and isinstance(denominator, int | float)
            and denominator > 0
        ):
            tolerance = _RATE_TOLERANCE.get(int(definition["decimals"]), 0.0001) + 0.0006 / (
                float(denominator)
            )
            if abs(float(numerator) / float(denominator) - float(value)) > tolerance:
                label = f"{record['player_id']}/{record['metric_id']}"
                arithmetic.append(f"{label}: {numerator}/{denominator} ≠ {value}")
    rank_problems: list[str] = []
    for (position, metric_id), members in cohorts.items():
        definition = defs[(position, metric_id)]
        values = {player: float(row["value"]) for player, row in members.items()}
        derived = percentile_ranks(
            values,
            direction=str(definition["direction"]),
            decimals=int(definition["decimals"]),
        )
        for player, row in members.items():
            if row.get("cohort_size") != len(members):
                size = row.get("cohort_size")
                rank_problems.append(
                    f"{position}/{metric_id}/{player}: cohort {size} vs {len(members)}"
                )
                continue
            mine = derived.get(player)
            got = (row.get("rank"), row.get("percentile"))
            if (mine is None and got != (None, None)) or (
                mine is not None
                and (mine[0] != got[0] or abs(mine[1] - float(got[1] or 0)) > 0.051)
            ):
                rank_problems.append(f"{position}/{metric_id}/{player}: {got} vs {mine}")
    if arithmetic:
        checks.append(
            _fail(
                "player_skill_tree.rate_arithmetic",
                "a published rate or share is not its numerator over its denominator",
                arithmetic,
                "value = numerator / denominator at the published precision",
            ),
        )
    if rank_problems:
        checks.append(
            _fail(
                "player_skill_tree.rank_rederivation",
                "a rank, percentile or cohort size does not re-derive from the published cohort",
                rank_problems,
                "competition rank and ADR-107 percentile over the published qualified values",
            ),
        )

    # Agreement with the season actuals (games, position) and board coverage.
    disagreements: list[str] = []
    actuals = envelopes.get("season_actuals")
    if actuals is not None:
        for row in actuals.get("records", ()):
            player = str(row.get("player_id"))
            if player not in games:
                disagreements.append(f"{player}: in season_actuals, no presence record")
                continue
            if int(row.get("games_played") or 0) != games[player]:
                disagreements.append(
                    f"{player}: games {games[player]} vs actuals {row.get('games_played')}",
                )
            if str(row.get("position")) != positions[player]:
                disagreements.append(
                    f"{player}: position {positions[player]} vs actuals {row.get('position')}",
                )
    usage = envelopes.get("player_usage")
    usage_mismatch: list[str] = []
    if usage is not None:
        totals = {
            (str(record["player_id"]), str(record["metric_id"])): record.get("value")
            for record in records
            if record["metric_id"] in ("targets", "carries", "pass_attempts")
        }
        through = int(tree.get("records", [{}])[0].get("through_week", 0) or 0) if records else 0
        for row in usage.get("records", ()):
            player = str(row.get("player_id"))
            played = [
                week
                for week in row.get("weeks") or ()
                if week.get("status") == "played" and int(week.get("week") or 0) <= through
            ]
            for metric_id, field in (
                ("targets", "targets"),
                ("carries", "carries"),
                ("pass_attempts", "pass_attempts"),
            ):
                published = totals.get((player, metric_id))
                if published is None:
                    continue
                summed = sum(float(week.get(field) or 0.0) for week in played)
                if abs(summed - float(published)) > 0.51:
                    usage_mismatch.append(f"{player}/{metric_id}: {published} vs usage {summed}")
    if disagreements:
        checks.append(
            _fail(
                "player_skill_tree.actuals_disagree",
                "the Skill Tree's games or position disagree with the season actuals",
                disagreements,
                "the same games and position on one card",
            ),
        )
    if usage_mismatch:
        checks.append(
            _fail(
                "player_skill_tree.usage_disagree",
                "a Skill Tree total disagrees with the usage layer's week-by-week series",
                usage_mismatch,
                "the same targets, carries and attempts on one card",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "player_skill_tree.cross_artifact",
                stage=_STAGE,
                message=(
                    "every reading defined and every tree complete; ranks, percentiles and "
                    "rates re-derive; games, positions and totals agree with the season "
                    "actuals and the usage series"
                ),
                observed=f"{len(by_player)} player(s), {len(cohorts)} ranked cohort(s)",
            ),
        )
    return checks


def skilltree_metadata_checks(
    metadata: Mapping[str, Any],
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The metadata block must describe the artifacts beside it, or their absence."""
    block = metadata.get("skill_tree")
    tree = envelopes.get("player_skill_tree")
    stage = "artifacts.ros_build_metadata"
    if block is None:
        if tree is None:
            return []
        return [
            QualityCheck.fail(
                "ros_build_metadata.skill_tree_undescribed",
                stage=stage,
                message="player_skill_tree.json is published without its build block",
                observed="skill_tree: null",
                expected="the ADR-107 block",
            ),
        ]
    problems: list[str] = []
    if block.get("status") == "published":
        if tree is None:
            problems.append("status published but no player_skill_tree.json")
        else:
            records = list(tree.get("records", ()))
            if int(block.get("records") or -1) != len(records):
                problems.append(f"records {block.get('records')} vs {len(records)}")
            appearing: dict[str, int] = {}
            for record in records:
                if record.get("metric_id") == "appearances" and int(record.get("games") or 0) > 0:
                    position = str(record.get("position"))
                    appearing[position] = appearing.get(position, 0) + 1
            for position, count in (block.get("population") or {}).items():
                if appearing.get(position, 0) != int(count):
                    problems.append(
                        f"population {position} {count} vs {appearing.get(position, 0)}"
                    )
            if block.get("through_week") != metadata.get("through_week"):
                problems.append("through_week differs from the bundle's")
            # Every reason a reading carries is explained in words on the card (a combine
            # reading's ``tested_as:<POS>`` names its cohort and needs no sentence).
            sentences = block.get("reasons") or {}
            unexplained = sorted(
                {
                    str(record["reason"])
                    for record in records
                    if record.get("reason") is not None
                    and not str(record["reason"]).startswith("tested_as:")
                    and str(record["reason"]) not in sentences
                }
            )
            if unexplained:
                problems.append(f"reasons without a sentence: {', '.join(unexplained)}")
    elif tree is not None:
        problems.append(f"status {block.get('status')} but player_skill_tree.json published")
    if problems:
        return [
            QualityCheck.fail(
                "ros_build_metadata.skill_tree_mismatch",
                stage=stage,
                message="the skill_tree block does not describe the artifact beside it",
                observed="; ".join(problems),
                expected="the block's counts, population and cutoff equal the artifact's",
            ),
        ]
    return [
        QualityCheck.ok(
            "ros_build_metadata.skill_tree",
            stage=stage,
            message="the skill_tree block describes the artifact beside it",
            observed=str(block.get("status")),
        ),
    ]
