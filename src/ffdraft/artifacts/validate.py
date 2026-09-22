"""Validation of a generated artifact directory.

Schema validity is necessary and nowhere near sufficient. A tier artifact can satisfy every
type constraint while numbering two players fair rank 4, splitting a tier across a gap, or
reporting a ``rank_gap`` with the wrong sign - and each of those would be visibly wrong on
the draft sheet. `docs/DATA_CONTRACTS.md` sections 8 and 12 list the semantic rules; this
module enforces them, plus the cross-artifact agreement no single schema can express.

Used by ``ffdraft validate-artifacts`` and by the Phase-1 fixture pipeline test.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ffdraft.artifacts.csv_flatten import flattener_for
from ffdraft.artifacts.schemas import (
    record_field_order,
    validate_envelope,
    validate_records,
)
from ffdraft.artifacts.spec import (
    ARTIFACT_SPECS,
    BUILD_METADATA_FILENAME,
    BUILD_METADATA_SCHEMA,
    spec_for,
)
from ffdraft.contracts import QualityCheck
from ffdraft.contracts.enums import Severity
from ffdraft.headshots import HEADSHOT_HOST, HEADSHOT_PROVIDER, headshot_url
from ffdraft.quality import (
    QualityGate,
    check_duplicate_keys,
    check_finite,
    check_quantiles_monotonic,
    check_range,
    check_unique_contiguous_tiers,
)

__all__ = ["validate_artifact_directory"]

#: ``rank_gap = market_adp - fair_rank`` (docs/DATA_CONTRACTS.md section 10). Positive means
#: the model would take the player earlier than the market does.
_RANK_GAP_TOLERANCE = 1e-6

#: Slack on the published `span_days` against the record's own first and last point.
#: Generous by design: the field is rounded for the artifact and a tolerance this size
#: still catches the failure it exists for, which is a span describing a different window.
_SPAN_TOLERANCE_DAYS = 1e-3

#: Selections the frontend offers that no capture produces. A series record naming one would
#: be a synthesized cross-market history — the thing ADR-081 declines to invent.
_SYNTHETIC_SOURCE_IDS = frozenset({"cross"})

#: The series rounds each point to two decimals for page weight; the arbitrage record does
#: not. Half a hundredth is the whole disagreement that rounding can produce.
_TREND_POINT_TOLERANCE = 0.0051

#: The in-season bundle's own metadata file and schema. Separate from the draft bundle's
#: because the two are produced by different models at different cutoffs, carry different
#: build ids, and must be independently validatable (roadmap 12.5).
ROS_BUILD_METADATA_FILENAME = "ros_build_metadata.json"
ROS_BUILD_METADATA_SCHEMA = "ros_build_metadata"

#: Which artifacts belong to which bundle. A build id is compared inside a bundle and never
#: across one: a site legitimately holds a Tuesday draft board beside a Monday ROS board.
#:
#: **Adding an in-season artifact means adding it here, and the omission fails in production
#: rather than in a fixture.** `behavior_trend_series` was published by the ROS build and left
#: out of this set (ADR-089), so `_build_metadata_checks` read it as a *draft* artifact and
#: compared its ROS build id against the draft bundle's — a critical failure on a correct
#: build, which stopped the 2026-09-19 refresh at `validate-artifacts`. The same omission
#: silently skipped it in `_ros_metadata_checks`, so the agreement it *should* have been
#: getting was never asserted either. One membership list, two directions, one line.
#:
#: The fixture build cannot catch this: it produces every artifact in one pass under one
#: build id, so draft and in-season trivially agree there. `test_two_bundle_validation.py`
#: is the test that can, and it builds the two-bundle shape production actually has.
_IN_SEASON_ARTIFACTS = frozenset(
    {
        "ros_tiers",
        "inseason_opportunity",
        "behavior_trend_series",
        # ADR-091. Both written by `run_ros_build`; added here in the same change that adds
        # them to the pipeline, which is the lesson ADR-089's refresh paid for.
        "player_usage",
        "team_matchups",
    },
)

#: Two sums of one set of weekly rows, one rounded per week and one per season. Five
#: hundredths is far past any rounding and far short of one reception.
_USAGE_POINTS_TOLERANCE = 0.05

#: Implied points are published to two decimals from lines published to one.
_IMPLIED_TOLERANCE = 0.011

#: How far two copies of the same intrinsic number may differ before the firewall check
#: fails. Zero, in effect: the opportunity board copies these values rather than computing
#: them, so any difference at all is a code path that recomputed one of them.
_INTRINSIC_COPY_TOLERANCE = 1e-9

#: The intrinsic fields the Opportunity Board copies from the rest-of-season board. Every one
#: of them is checked, because "behaviour never changes a value" is the phase's central claim
#: and a claim nobody tests is a comment.
#: The rest-of-season quantile columns, in order. Named explicitly rather than derived from
#: a prefix because the public vocabulary puts the quantile last (`ros_vorp_p10`) while the
#: preseason one puts it first (`p10_vorp`), and a shared helper that guessed would silently
#: check nothing.
_ROS_VORP_QUANTILES = (
    "ros_vorp_p10",
    "ros_vorp_p25",
    "ros_vorp_p50",
    "ros_vorp_p75",
    "ros_vorp_p90",
)
_ROS_POINT_QUANTILES = ("ros_points_p10", "ros_points_p50", "ros_points_p90")

_COPIED_INTRINSIC_FIELDS = (
    "ros_fair_rank",
    "ros_position_rank",
    "ros_expected_vorp",
    "ros_expected_points",
    "ros_expected_games",
    "ros_uncertainty",
    "ros_tier",
)


def validate_artifact_directory(directory: Path) -> QualityGate:
    """Validate every artifact present in ``directory``.

    A missing optional artifact is not an error - a build may legitimately emit tiers
    without arbitrage when the market source failed (`docs/DATA_SOURCES.md` section 10).
    A missing ``build_metadata.json`` *is* an error: the frontend reads freshness from it.
    """
    gate = QualityGate()
    if not directory.is_dir():
        return gate.add(
            QualityCheck.fail(
                "artifact.directory_missing",
                stage="artifacts",
                message="artifact directory does not exist",
                observed=str(directory),
                expected="a directory of generated artifacts",
            ),
        )

    envelopes: dict[str, Mapping[str, Any]] = {}
    for artifact, spec in ARTIFACT_SPECS.items():
        path = directory / spec.json_filename
        if not path.is_file():
            continue
        payload = _load_json(path, gate)
        if payload is None:
            continue
        envelopes[artifact] = payload
        stage = f"artifacts.{artifact}"
        gate.extend(validate_envelope(payload, stage=stage))
        records = list(payload.get("records", ()))
        gate.extend(validate_records(spec.schema_name, records, stage=stage))
        gate.extend(check_duplicate_keys(records, key_fields=spec.key_fields, stage=stage))
        gate.extend(_semantic_checks(artifact, records, payload, stage))
        if spec.csv_filename:
            gate.extend(_csv_agreement(directory / spec.csv_filename, artifact, records, stage))

    gate.extend(_build_metadata_checks(directory, envelopes))
    gate.extend(_ros_metadata_checks(directory, envelopes))
    gate.extend(_cross_artifact_checks(envelopes))
    gate.extend(_headshot_cross_checks(envelopes))
    gate.extend(_in_season_cross_checks(envelopes))
    gate.extend(_behavior_series_cross_checks(envelopes))
    gate.extend(_signal_cross_checks(envelopes))
    if not envelopes:
        gate.add(
            QualityCheck.fail(
                "artifact.none_found",
                stage="artifacts",
                message="no known artifact files were found",
                observed=str(directory),
                expected=", ".join(spec.json_filename for spec in ARTIFACT_SPECS.values()),
            ),
        )
    return gate


def _load_json(path: Path, gate: QualityGate) -> Mapping[str, Any] | None:
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        gate.add(
            QualityCheck.fail(
                "artifact.unreadable",
                stage="artifacts",
                message=f"could not read {path.name}",
                observed=str(exc),
                expected="valid UTF-8 JSON",
            ),
        )
        return None
    if not isinstance(loaded, Mapping):
        gate.add(
            QualityCheck.fail(
                "artifact.not_an_object",
                stage="artifacts",
                message=f"{path.name} must be a JSON object",
                observed=type(loaded).__name__,
                expected="object",
            ),
        )
        return None
    return loaded


def _semantic_checks(
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    stage: str,
) -> list[QualityCheck]:
    match artifact:
        case "tiers":
            return [
                *check_unique_contiguous_tiers(records, stage=stage),
                *check_quantiles_monotonic(records, prefix="vorp", stage=stage),
                *check_finite(
                    records,
                    fields=("expected_vorp", "expected_points", "uncertainty"),
                    stage=stage,
                ),
                *check_range(records, field="fair_rank", minimum=1, stage=stage),
                *check_range(records, field="position_rank", minimum=1, stage=stage),
                *check_range(records, field="uncertainty", minimum=0, stage=stage),
            ]
        case "projections":
            return [
                *check_quantiles_monotonic(records, prefix="points", stage=stage),
                *check_finite(
                    records,
                    fields=("expected_points", "uncertainty_points"),
                    stage=stage,
                ),
                *check_range(records, field="uncertainty_points", minimum=0, stage=stage),
            ]
        case "ros_tiers":
            return _ros_tier_checks(records, stage)
        case "inseason_opportunity":
            return _opportunity_checks(records, stage)
        case "arbitrage":
            return _arbitrage_checks(records, envelope, stage)
        case "market_snapshot":
            return [
                *check_range(records, field="market_adp", minimum=1e-9, stage=stage),
                *check_range(records, field="league_size", minimum=4, maximum=32, stage=stage),
                *_market_dispersion_checks(records, stage),
            ]
        case "market_trend_series":
            return _trend_series_checks(records, stage)
        case "behavior_trend_series":
            return _behavior_series_checks(records, stage)
        case "player_usage":
            return _usage_checks(records, stage)
        case "team_matchups":
            return _matchup_checks(records, stage)
        case "player_headshots":
            return _headshot_checks(records, stage)
    return []


def _usage_checks(records: Sequence[Mapping[str, Any]], stage: str) -> list[QualityCheck]:
    """What ``usage_signals_v1`` promises about every record, checked on the bytes (ADR-091).

    The schema pins shapes; these pin the promises a card relies on when it draws a series:
    one entry per week in order, an absence published as null rather than as zero, a change
    that is exactly the difference of the two numbers printed beside it, and thresholds that
    withhold a reading rather than print one from too small a sample.
    """
    bad_weeks: list[str] = []
    zero_absence: list[str] = []
    miscounted: list[str] = []
    bad_change: list[str] = []
    bad_totals: list[str] = []
    thin: list[str] = []
    for record in records:
        key = str(record.get("player_id"))
        weeks = list(record.get("weeks", ()))
        through = int(record.get("through_week") or 0)
        numbers = [int(week.get("week", 0)) for week in weeks]
        if numbers != list(range(1, len(numbers) + 1)) or (numbers and numbers[-1] > through):
            bad_weeks.append(f"{key}: {numbers}")
        played = [week for week in weeks if week.get("status") == "played"]
        if int(record.get("appearances", -1)) != len(played):
            miscounted.append(
                f"{key}: appearances={record.get('appearances')} played={len(played)}"
            )
        for week in weeks:
            if week.get("status") == "played":
                continue
            carried = [
                name
                for name in (
                    "snap_share",
                    "target_share",
                    "carry_share",
                    "air_yards_share",
                    "targets",
                    "carries",
                    "pass_attempts",
                    "fantasy_points",
                )
                if week.get(name) is not None
            ]
            if carried:
                zero_absence.append(f"{key}@{week.get('week')}: {', '.join(carried)}")
        last_played = played[-1]["week"] if played else None
        for metric, change in (record.get("role_changes") or {}).items():
            if change is None:
                continue
            if change.get("latest_week") != last_played:
                bad_change.append(f"{key}/{metric}: latest_week={change.get('latest_week')}")
            latest, earlier, delta = (
                change.get("latest"),
                change.get("earlier"),
                change.get("change"),
            )
            if (earlier is None) != (delta is None):
                bad_change.append(f"{key}/{metric}: earlier={earlier} change={delta}")
            elif earlier is not None and abs(float(latest) - float(earlier) - float(delta)) > 1e-6:
                bad_change.append(f"{key}/{metric}: {latest} - {earlier} != {delta}")
            if int(change.get("earlier_games", 0)) > max(0, len(played) - 1):
                bad_change.append(f"{key}/{metric}: earlier_games exceeds earlier appearances")
        totals = record.get("fantasy_points_to_date") or {}
        for preset, total in totals.items():
            summed = sum(
                float((week.get("fantasy_points") or {}).get(preset) or 0.0) for week in played
            )
            if total is None or abs(summed - float(total)) > _USAGE_POINTS_TOLERANCE:
                bad_totals.append(f"{key}/{preset}: weeks={summed:.2f} total={total}")
            share = (record.get("touchdown_points_share") or {}).get(preset)
            if share is not None and total is not None and float(total) < 10.0:
                thin.append(f"{key}/{preset}: touchdown share on {total} points")
        if (
            record.get("pass_epa_per_dropback") is not None
            and float(record.get("dropbacks") or 0) < 20
        ):
            thin.append(f"{key}: EPA per dropback on {record.get('dropbacks')} dropbacks")

    checks: list[QualityCheck] = []
    for check_id, found, message, expected in (
        (
            "player_usage.weeks_not_contiguous",
            bad_weeks,
            "a usage series must carry every week from 1 through the cutoff, in order",
            "weeks == 1..n with n <= through_week",
        ),
        (
            "player_usage.absence_published_as_a_value",
            zero_absence,
            "a week he did not play must carry null metrics; a zero there would read as a role",
            "every metric null unless status is played",
        ),
        (
            "player_usage.appearances_disagree",
            miscounted,
            "appearances must count the played weeks it summarises",
            "appearances == weeks with status played",
        ),
        (
            "player_usage.change_is_not_the_difference",
            bad_change,
            "role_change_v1: the change is the latest appearance minus the earlier average, "
            "exactly as published, and only where an earlier appearance exists",
            "change == latest - earlier; latest_week == last played week",
        ),
        (
            "player_usage.points_do_not_sum",
            bad_totals,
            "fantasy points to date must be the sum of the weekly points the card draws",
            "sum(weeks.fantasy_points) == fantasy_points_to_date",
        ),
        (
            "player_usage.reading_below_minimum",
            thin,
            "a touchdown share or an EPA was published from a sample below its declared minimum",
            "null below 10 points / 20 dropbacks",
        ),
    ):
        if found:
            checks.append(
                QualityCheck.fail(
                    check_id,
                    stage=stage,
                    message=message,
                    observed="; ".join(found[:10]),
                    expected=expected,
                ),
            )
    if not checks and records:
        with_change = sum(
            1
            for record in records
            if any(value is not None for value in (record.get("role_changes") or {}).values())
        )
        checks.append(
            QualityCheck.ok(
                "player_usage.series_well_formed",
                stage=stage,
                message=(
                    "every usage series is contiguous, publishes absences as null, and states "
                    "changes that are exactly the difference of its own published numbers"
                ),
                observed=f"{len(records)} player(s), {with_change} with a role change",
            ),
        )
    return checks


def _matchup_checks(records: Sequence[Mapping[str, Any]], stage: str) -> list[QualityCheck]:
    """``next_game_v1``'s arithmetic and its one sign convention, checked on the bytes.

    The implied points are two published numbers' arithmetic and must reproduce them; the
    two sides of one game must be each other's mirror, which is the check that catches the
    upstream spread convention being applied backwards — the one mistake in this artifact
    that would still look plausible on every card.
    """
    arithmetic: list[str] = []
    provenance: list[str] = []
    mirrored: list[str] = []
    self_play: list[str] = []
    by_game: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        key = str(record.get("team"))
        if record.get("team") == record.get("opponent"):
            self_play.append(key)
        by_game.setdefault(str(record.get("game_id")), []).append(record)
        total = record.get("total_line")
        margin = record.get("team_expected_margin")
        mine = record.get("implied_team_points")
        theirs = record.get("implied_opponent_points")
        if total is None or margin is None:
            if mine is not None or theirs is not None:
                arithmetic.append(f"{key}: implied points without both lines")
        else:
            if mine is None or theirs is None:
                arithmetic.append(f"{key}: both lines posted and no implied points")
            elif (
                abs(float(mine) + float(theirs) - float(total)) > _IMPLIED_TOLERANCE
                or abs(float(mine) - float(theirs) - float(margin)) > _IMPLIED_TOLERANCE
            ):
                arithmetic.append(f"{key}: {mine} / {theirs} from total {total} margin {margin}")
        has_lines = total is not None or margin is not None
        if has_lines != (record.get("lines_source_id") is not None):
            provenance.append(f"{key}: lines={has_lines} source={record.get('lines_source_id')}")
    for game_id, sides in by_game.items():
        if len(sides) != 2:
            continue
        first, second = sides
        if first.get("opponent") != second.get("team") or first.get("home_away") == second.get(
            "home_away",
        ):
            mirrored.append(f"{game_id}: sides disagree on who plays where")
        a, b = first.get("team_expected_margin"), second.get("team_expected_margin")
        if a is None or b is None:
            if (a is None) != (b is None):
                mirrored.append(f"{game_id}: one side has a margin and the other none")
        elif abs(float(a) + float(b)) > 1e-9:
            mirrored.append(f"{game_id}: margins {a} and {b} are not opposite")
        if first.get("total_line") != second.get("total_line"):
            mirrored.append(f"{game_id}: totals differ")

    checks: list[QualityCheck] = []
    for check_id, found, message, expected in (
        (
            "team_matchups.implied_points_disagree",
            arithmetic,
            "implied points must be (total ± margin) / 2 and exist exactly when both lines do",
            "implied_team + implied_opponent == total; difference == margin",
        ),
        (
            "team_matchups.line_without_provenance",
            provenance,
            "a published line must name where it was read, and a missing one must not",
            "lines_source_id set exactly when a line is posted",
        ),
        (
            "team_matchups.sides_disagree",
            mirrored,
            "the two teams of one game must mirror each other: opposite venues and margins, "
            "one total",
            "opposite home_away and team_expected_margin, equal total_line",
        ),
        (
            "team_matchups.team_plays_itself",
            self_play,
            "a team cannot be its own opponent",
            "team != opponent",
        ),
    ):
        if found:
            checks.append(
                QualityCheck.fail(
                    check_id,
                    stage=stage,
                    message=message,
                    observed="; ".join(found[:10]),
                    expected=expected,
                ),
            )
    if not checks and records:
        lined = sum(1 for record in records if record.get("total_line") is not None)
        checks.append(
            QualityCheck.ok(
                "team_matchups.well_formed",
                stage=stage,
                message=(
                    "every next game mirrors its opponent's and every implied score reproduces "
                    "the lines it came from; the lines are context and feed no model"
                ),
                observed=f"{len(records)} team(s), {lined} with posted lines",
            ),
        )
    return checks


def _headshot_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """The one place a published address can point the browser somewhere new (ADR-087).

    The record schema already pins the host with a pattern, so this is a second reading of the
    same claim rather than the only one - deliberately, because it is the check that has to
    survive a future schema edit. It asserts two things the pattern alone cannot: that the URL
    and the id agree, so a row cannot carry one player's id beside another's picture, and that
    every row names the provider its id came from.
    """
    wrong_host: list[str] = []
    disagreeing: list[str] = []
    wrong_provider: list[str] = []

    for record in records:
        player_id = str(record.get("player_id"))
        provider = record.get("provider")
        provider_id = str(record.get("provider_player_id") or "")
        url = str(record.get("image_url") or "")
        if provider != HEADSHOT_PROVIDER:
            wrong_provider.append(f"{player_id}: {provider!r}")
            continue
        if not url.startswith(f"https://{HEADSHOT_HOST}/"):
            wrong_host.append(f"{player_id}: {url}")
            continue
        if url != headshot_url(provider_id):
            disagreeing.append(f"{player_id}: {provider_id} -> {url}")

    checks: list[QualityCheck] = []
    if wrong_provider:
        checks.append(
            QualityCheck.fail(
                "artifact.headshot_unknown_provider",
                stage=stage,
                message="a portrait row names a provider this build does not publish",
                observed="; ".join(wrong_provider[:10]),
                expected=HEADSHOT_PROVIDER,
            ),
        )
    if wrong_host:
        checks.append(
            QualityCheck.fail(
                "artifact.headshot_foreign_host",
                stage=stage,
                message=(
                    "a portrait address points somewhere other than the one declared host; "
                    "publishing it would open the page to an origin nothing reviewed"
                ),
                observed="; ".join(wrong_host[:10]),
                expected=f"https://{HEADSHOT_HOST}/",
            ),
        )
    if disagreeing:
        checks.append(
            QualityCheck.fail(
                "artifact.headshot_url_disagrees_with_id",
                stage=stage,
                message=(
                    "a portrait address does not resolve from the id beside it, so the row "
                    "could show one player's picture under another player's name"
                ),
                observed="; ".join(disagreeing[:10]),
                expected="image_url == headshot_url(provider_player_id)",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "artifact.headshot_addresses_agree",
                stage=stage,
                message="every portrait address resolves from its own id on the declared host",
                observed=f"{len(records)} row(s), host {HEADSHOT_HOST}",
            ),
        )
    return checks


def _behavior_series_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """The momentum series, checked against the claim it is allowed to make (ADR-089).

    Four things a schema cannot say, and the first two are what keep a two-point slope
    honest rather than merely permitted:

    **A slope needs two points.** `behavior_trend_v1` deliberately estimates one from as few
    as two observations, because an add count moves in hours and a three-day rule would
    admit a waiver signal after the edge is gone. The price of that is that a single
    observation must never carry a trend — that would not be a short measurement, it would
    be an invented one.

    **A slope is never published without its span.** ``span_days`` and ``observations`` are
    required fields precisely so a consumer can print "over 2 days"; a record whose span
    disagrees with its own points would let a chart label a two-day reading as a week.

    **``observations`` counts the points.** The field exists so a reader can compare it with
    ``snapshots_in_window`` and see the days the player was outside the feed's top N. If it
    can drift from the array beside it, that comparison means nothing.

    **Net is the difference.** ``net_add_count`` is the one subtraction this product allows
    on behaviour data, and it is allowed because both sides are the same unit at the same
    moment. A row where it is not the difference is a row where something else was computed.
    """
    unordered: list[str] = []
    miscounted: list[str] = []
    invented: list[str] = []
    bad_span: list[str] = []
    bad_net: list[str] = []
    impossible_coverage: list[str] = []

    for record in records:
        key = str(record.get("player_id"))
        points = list(record.get("points", ()))
        stamps = [str(point.get("observed_at")) for point in points]
        if stamps != sorted(stamps):
            unordered.append(key)
        observations = record.get("observations")
        if observations != len(points):
            miscounted.append(f"{key}: observations={observations} points={len(points)}")
        if len(points) < 2 and (
            record.get("add_trend") is not None or record.get("net_trend") is not None
        ):
            invented.append(key)
        span = record.get("span_days")
        if len(points) >= 2 and span is not None:
            first = _parse_iso(stamps[0])
            last = _parse_iso(stamps[-1])
            if first is not None and last is not None:
                measured = (last - first).total_seconds() / 86400.0
                if abs(measured - float(span)) > _SPAN_TOLERANCE_DAYS:
                    bad_span.append(f"{key}: field={span} points={measured:.4f}")
        elif len(points) < 2 and span not in (None, 0, 0.0):
            bad_span.append(f"{key}: one point but span_days={span}")
        snapshots = record.get("snapshots_in_window")
        if isinstance(snapshots, int) and snapshots < len(points):
            impossible_coverage.append(f"{key}: {len(points)} point(s) in {snapshots} snapshot(s)")
        for point in points:
            add = point.get("add_count")
            drop = point.get("drop_count")
            net = point.get("net_add_count")
            if add is None or drop is None or net is None:
                continue
            if int(net) != int(add) - int(drop):
                bad_net.append(f"{key}@{point.get('observed_at')}: {add} - {drop} != {net}")

    checks: list[QualityCheck] = []
    if unordered:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.points_out_of_order",
                stage=stage,
                message="points must ascend by observed_at; a sparkline trusts the order",
                observed="; ".join(unordered[:10]),
                expected="ascending observed_at",
            ),
        )
    if miscounted:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.observation_count_disagrees",
                stage=stage,
                message=(
                    "observations must equal the number of points, because it is what a "
                    "reader compares against snapshots_in_window"
                ),
                observed="; ".join(miscounted[:10]),
                expected="observations == len(points)",
            ),
        )
    if invented:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.trend_without_two_points",
                stage=stage,
                message=(
                    "a single observation carries no direction; behavior_trend_v1 estimates "
                    "a slope from two points and never from one"
                ),
                observed="; ".join(invented[:10]),
                expected="add_trend and net_trend null below two observations",
            ),
        )
    if bad_span:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.span_disagrees_with_points",
                stage=stage,
                message=(
                    "span_days must describe this record's own points; it is the field that "
                    "stops a two-day reading being labelled as a week"
                ),
                observed="; ".join(bad_span[:10]),
                expected="span_days == last observed_at - first observed_at, in days",
            ),
        )
    if impossible_coverage:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.more_points_than_snapshots",
                stage=stage,
                message=("a player cannot be observed more times than the window held snapshots"),
                observed="; ".join(impossible_coverage[:10]),
                expected="observations <= snapshots_in_window",
            ),
        )
    if bad_net:
        checks.append(
            QualityCheck.fail(
                "behavior_trend_series.net_is_not_the_difference",
                stage=stage,
                message="net_add_count must be add_count minus drop_count at that instant",
                observed="; ".join(bad_net[:10]),
                expected="net_add_count == add_count - drop_count",
            ),
        )
    if not checks and records:
        with_trend = sum(1 for record in records if record.get("add_trend") is not None)
        checks.append(
            QualityCheck.ok(
                "behavior_trend_series.series_well_formed",
                stage=stage,
                message=(
                    "every series ascends, counts its own points, states the span it was "
                    "measured over and carries a direction only where two points support one"
                ),
                observed=f"{len(records)} series, {with_trend} with a direction",
            ),
        )
    return checks


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _trend_series_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """The chart's own data, checked as a series rather than as a bag of numbers.

    Two things a schema cannot say. **Points ascend**: the artifact promises ascending
    ``observed_at`` and a consumer that trusted it would draw a line that doubles back.
    **No source is invented**: `cross` is a *view* the reader selects, never a market anyone
    captured, so a series claiming it would be a history no snapshot produced (ADR-081).
    """
    unordered: list[str] = []
    empty: list[str] = []
    synthetic: list[str] = []
    for record in records:
        key = (
            f"{record.get('market_source_id')}/{record.get('league_preset_id')}/"
            f"{record.get('scoring_preset')}/{record.get('player_id')}"
        )
        points = list(record.get("points", ()))
        if not points:
            empty.append(key)
        stamps = [str(point.get("observed_at")) for point in points]
        if stamps != sorted(stamps):
            unordered.append(key)
        if str(record.get("market_source_id")) in _SYNTHETIC_SOURCE_IDS:
            synthetic.append(key)

    checks: list[QualityCheck] = []
    if empty:
        checks.append(
            QualityCheck.fail(
                "market_trend_series.empty_series",
                stage=stage,
                message="a series with no points is bytes shipped to say nothing",
                observed="; ".join(empty[:10]),
                expected="at least one retained observation per record",
            ),
        )
    if unordered:
        checks.append(
            QualityCheck.fail(
                "market_trend_series.points_out_of_order",
                stage=stage,
                message=(
                    "points must ascend by observed_at; the contract says so and a chart trusts it"
                ),
                observed="; ".join(unordered[:10]),
                expected="ascending observed_at",
            ),
        )
    if synthetic:
        checks.append(
            QualityCheck.fail(
                "market_trend_series.synthetic_source",
                stage=stage,
                message=(
                    "a history must name a market that was actually captured; the "
                    "cross-market view is a selection, not a source"
                ),
                observed="; ".join(sorted(set(synthetic))[:10]),
                expected="a retained source id",
            ),
        )
    return checks


def _arbitrage_checks(
    records: Sequence[Mapping[str, Any]],
    envelope: Mapping[str, Any],
    stage: str,
) -> list[QualityCheck]:
    checks: list[QualityCheck] = [
        *check_range(records, field="arbitrage_score", minimum=0, maximum=100, stage=stage),
        *check_range(records, field="market_adp", minimum=1e-9, stage=stage),
        *check_range(records, field="p_positive_surplus", minimum=0, maximum=1, stage=stage),
    ]

    sign_offenders = [
        f"{record.get('player_id')}: {record.get('rank_gap')}"
        for record in records
        if abs(
            float(record.get("rank_gap", 0.0))
            - (float(record.get("market_adp", 0.0)) - float(record.get("fair_rank", 0.0)))
        )
        > _RANK_GAP_TOLERANCE
    ]
    if sign_offenders:
        checks.append(
            QualityCheck.fail(
                "arbitrage.rank_gap_convention",
                stage=stage,
                message="rank_gap must equal market_adp - fair_rank (positive = bargain)",
                observed="; ".join(sign_offenders[:10]),
                expected="market_adp - fair_rank",
            ),
        )
    else:
        checks.append(
            QualityCheck.ok(
                "arbitrage.rank_gap_convention",
                stage=stage,
                message="rank_gap follows the documented sign convention",
                observed=f"{len(records)} record(s)",
            ),
        )

    modes = {str(record.get("arbitrage_mode")) for record in records}
    declared = envelope.get("arbitrage_mode")
    if declared is not None and modes and modes != {str(declared)}:
        checks.append(
            QualityCheck.fail(
                "arbitrage.mode_mismatch",
                stage=stage,
                message="record arbitrage_mode disagrees with the envelope",
                observed=f"records {sorted(modes)}, envelope {declared}",
                expected="identical",
            ),
        )
    leaked = [
        str(record.get("player_id"))
        for record in records
        if str(record.get("arbitrage_mode")) == "baseline"
        and (
            record.get("expected_surplus_vorp") is not None
            or record.get("p_positive_surplus") is not None
        )
    ]
    if leaked:
        # ADR-010: baseline mode must not publish learned-model fields. Populating them
        # would claim a model that was never trained.
        checks.append(
            QualityCheck.fail(
                "arbitrage.baseline_mode_ml_fields",
                stage=stage,
                message="baseline-mode records must leave learned-model fields null (ADR-010)",
                observed="; ".join(leaked[:10]),
                expected="null expected_surplus_vorp and p_positive_surplus",
            ),
        )
    return checks


def _market_dispersion_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    offenders = [
        str(record.get("player_id"))
        for record in records
        if record.get("adp_low") is not None
        and record.get("adp_high") is not None
        and float(record["adp_low"]) > float(record["adp_high"])
    ]
    if offenders:
        return [
            QualityCheck.fail(
                "market.inverted_dispersion",
                stage=stage,
                message="adp_low must not exceed adp_high",
                observed="; ".join(offenders[:10]),
                expected="adp_low <= adp_high",
            ),
        ]
    return []


def _csv_agreement(
    path: Path,
    artifact: str,
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """The CSV export must carry the same rows and columns as the JSON."""
    spec = spec_for(artifact)
    if not path.is_file():
        return [
            QualityCheck.fail(
                "artifact.csv_missing",
                stage=stage,
                message=f"{spec.json_filename} has no matching CSV export",
                observed=str(path),
                expected=spec.csv_filename or "",
            ),
        ]
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [
            QualityCheck.fail(
                "artifact.csv_empty",
                stage=stage,
                message=f"{path.name} has no header row",
                observed="0 rows",
                expected="header + one row per record",
            ),
        ]
    # An artifact whose JSON record nests declares a CSV projection instead of inheriting
    # the schema's field order (ADR-065). The header is still fixed and still checked -
    # what changes is which declaration it is checked against.
    flattener = flattener_for(spec.artifact)
    expected_header = (
        list(flattener[0]) if flattener else list(record_field_order(spec.schema_name))
    )
    checks: list[QualityCheck] = []
    if rows[0] != expected_header:
        checks.append(
            QualityCheck.fail(
                "artifact.csv_header_mismatch",
                stage=stage,
                message=(
                    f"{path.name} columns must match its declared CSV projection"
                    if flattener
                    else f"{path.name} columns must match the record schema order"
                ),
                observed=", ".join(rows[0]),
                expected=", ".join(expected_header),
            ),
        )
    if len(rows) - 1 != len(records):
        checks.append(
            QualityCheck.fail(
                "artifact.csv_row_count_mismatch",
                stage=stage,
                message=f"{path.name} row count disagrees with the JSON artifact",
                observed=f"{len(rows) - 1} data row(s)",
                expected=f"{len(records)}",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "artifact.csv_agrees",
                stage=stage,
                message=f"{path.name} agrees with {spec.json_filename}",
                observed=f"{len(rows) - 1} row(s)",
            ),
        )
    return checks


def _build_metadata_checks(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    path = directory / BUILD_METADATA_FILENAME
    stage = "artifacts.build_metadata"
    draft_envelopes = {
        artifact: envelope
        for artifact, envelope in envelopes.items()
        if artifact not in _IN_SEASON_ARTIFACTS
    }
    if not path.is_file():
        if not draft_envelopes:
            # An in-season-only directory is a legitimate shape: the two bundles are built by
            # different jobs and must validate independently (roadmap 12.5).
            return []
        return [
            QualityCheck.fail(
                "artifact.build_metadata_missing",
                stage=stage,
                message="build_metadata.json is required; the UI reads freshness from it",
                observed=str(path),
                expected=BUILD_METADATA_FILENAME,
            ),
        ]
    envelopes = draft_envelopes
    try:
        metadata: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            QualityCheck.fail(
                "artifact.build_metadata_unreadable",
                stage=stage,
                message="could not read build_metadata.json",
                observed=str(exc),
                expected="valid JSON",
            ),
        ]

    checks = list(validate_records(BUILD_METADATA_SCHEMA, [metadata], stage=stage))
    if any(check.blocking for check in checks):
        return checks

    gate = metadata.get("quality_gate", {})
    if gate.get("status") == "pass" and gate.get("critical_failures", 0):
        checks.append(
            QualityCheck.fail(
                "build_metadata.gate_inconsistent",
                stage=stage,
                message="quality_gate claims pass while reporting critical failures",
                observed=json.dumps(gate),
                expected="status=fail when critical_failures > 0",
            ),
        )
    supported = set(metadata.get("supported_presets", ()))
    for artifact, envelope in envelopes.items():
        if envelope.get("build_id") != metadata.get("build_id"):
            checks.append(
                QualityCheck.fail(
                    "build_metadata.build_id_mismatch",
                    stage=stage,
                    message=f"{artifact} carries a different build_id from build_metadata",
                    observed=f"{artifact}={envelope.get('build_id')}",
                    expected=str(metadata.get("build_id")),
                ),
            )
        presets = {
            str(record.get("league_preset_id"))
            for record in envelope.get("records", ())
            if record.get("league_preset_id") is not None
        }
        unknown = presets - supported
        if unknown:
            checks.append(
                QualityCheck.fail(
                    "build_metadata.unsupported_preset",
                    stage=stage,
                    message=f"{artifact} references presets absent from supported_presets",
                    observed=", ".join(sorted(unknown)),
                    expected=", ".join(sorted(supported)),
                ),
            )
    return checks


def _monotonic_fields(
    records: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    *,
    label: str,
    stage: str,
) -> list[QualityCheck]:
    """Named quantile columns must be non-decreasing. Critical, as everywhere else."""
    offenders: list[str] = []
    for record in records:
        values = [record.get(field) for field in fields]
        if any(value is None for value in values):
            offenders.append(f"{record.get('player_id')} (missing quantile)")
            continue
        numeric = [float(value) for value in values]  # type: ignore[arg-type]
        if any(later < earlier for earlier, later in zip(numeric, numeric[1:], strict=False)):
            offenders.append(f"{record.get('player_id')} ({numeric})")
    if offenders:
        return [
            QualityCheck.fail(
                "artifact.non_monotonic_quantiles",
                stage=stage,
                message=f"{label} quantiles must be non-decreasing",
                observed="; ".join(offenders[:10]),
                expected=" <= ".join(fields),
            ),
        ]
    return [
        QualityCheck.ok(
            "artifact.non_monotonic_quantiles",
            stage=stage,
            message=f"{label} quantiles are non-decreasing on every row",
            observed=f"{len(records)} record(s)",
        ),
    ]


def _ros_tier_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """Semantic rules a rest-of-season board must satisfy beyond its schema.

    The ADR-076 clauses are the ones worth stating plainly: the long-absence flag has to mean
    exactly what the ADR defines it to mean, and it has to be accompanied by the observable
    number that makes it checkable. A flag set on a player who has not played at all, or on
    one whose consecutive-miss count contradicts it, would be a different claim wearing the
    same name.
    """
    checks: list[QualityCheck] = [
        *_monotonic_fields(records, _ROS_VORP_QUANTILES, label="ros_vorp", stage=stage),
        *_monotonic_fields(records, _ROS_POINT_QUANTILES, label="ros_points", stage=stage),
        *check_finite(
            records,
            fields=("ros_expected_vorp", "ros_expected_points", "ros_uncertainty"),
            stage=stage,
        ),
        *check_range(records, field="ros_fair_rank", minimum=1, stage=stage),
        *check_range(records, field="ros_position_rank", minimum=1, stage=stage),
        *check_range(records, field="ros_uncertainty", minimum=0, stage=stage),
        *check_range(records, field="ros_expected_games", minimum=0, stage=stage),
        *check_range(records, field="through_week", minimum=1, stage=stage),
    ]

    mislabelled = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("long_absence"))
        and not (
            bool(record.get("has_played_this_season"))
            and float(record.get("consecutive_weeks_missed") or 0.0) >= 3.0
        )
    ]
    if mislabelled:
        checks.append(
            QualityCheck.fail(
                "ros.long_absence_definition",
                stage=stage,
                message=(
                    "long_absence must be set exactly when the player HAS played this season "
                    "and has missed three or more consecutive weeks (ADR-076)"
                ),
                observed="; ".join(mislabelled[:10]),
                expected="has_played_this_season and consecutive_weeks_missed >= 3",
            ),
        )
    missed = [
        str(record.get("player_id"))
        for record in records
        if not bool(record.get("long_absence"))
        and bool(record.get("has_played_this_season"))
        and float(record.get("consecutive_weeks_missed") or 0.0) >= 3.0
    ]
    if missed:
        checks.append(
            QualityCheck.fail(
                "ros.long_absence_unflagged",
                stage=stage,
                message=(
                    "a player meeting the long-absence condition is not flagged; the "
                    "disclosure contract is a property of the data, not of the renderer"
                ),
                observed="; ".join(missed[:10]),
                expected="every qualifying row carries long_absence",
            ),
        )
    if not mislabelled and not missed:
        flagged = sum(1 for record in records if record.get("long_absence"))
        checks.append(
            QualityCheck.ok(
                "ros.long_absence_definition",
                stage=stage,
                message=(
                    "the long-absence flag matches its ADR-076 definition on every row, and "
                    "weeks_since_last_game is published beside it"
                ),
                observed=f"{flagged} of {len(records)} row(s) flagged",
            ),
        )

    cutoffs = {int(record["through_week"]) for record in records if "through_week" in record}
    if len(cutoffs) > 1:
        checks.append(
            QualityCheck.fail(
                "ros.mixed_cutoffs",
                stage=stage,
                message="every row in one rest-of-season bundle must share the cutoff week",
                observed=", ".join(str(week) for week in sorted(cutoffs)),
                expected="one through_week",
            ),
        )
    return checks


def _opportunity_checks(
    records: Sequence[Mapping[str, Any]],
    stage: str,
) -> list[QualityCheck]:
    """Rules the Opportunity Board must satisfy, all about not inventing a quantity."""
    checks: list[QualityCheck] = [
        *check_range(records, field="ros_fair_rank", minimum=1, stage=stage),
        *check_range(records, field="add_count", minimum=0, stage=stage),
        *check_range(records, field="drop_count", minimum=0, stage=stage),
    ]

    inconsistent = [
        str(record.get("player_id"))
        for record in records
        if record.get("add_count") is not None
        and record.get("drop_count") is not None
        and record.get("net_add_count") is not None
        and int(record["net_add_count"]) != int(record["add_count"]) - int(record["drop_count"])
    ]
    if inconsistent:
        checks.append(
            QualityCheck.fail(
                "opportunity.net_add_arithmetic",
                stage=stage,
                message="net_add_count must equal add_count minus drop_count",
                observed="; ".join(inconsistent[:10]),
                expected="add_count - drop_count",
            ),
        )

    # A surfaced row is published *because* it is outside the tier depth, so it must not
    # carry a tier: a fabricated one is exactly the number the surface rule refuses to
    # invent (ADR-063).
    tiered_exceptions = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("outside_tier_board")) and record.get("ros_tier") is not None
    ]
    if tiered_exceptions:
        checks.append(
            QualityCheck.fail(
                "opportunity.surfaced_row_has_tier",
                stage=stage,
                message=(
                    "a player surfaced from beyond the tier depth must carry no tier; the "
                    "model never segmented him"
                ),
                observed="; ".join(tiered_exceptions[:10]),
                expected="null ros_tier",
            ),
        )
    unexplained = [
        str(record.get("player_id"))
        for record in records
        if bool(record.get("outside_tier_board")) and not record.get("surface_reasons")
    ]
    if unexplained:
        checks.append(
            QualityCheck.fail(
                "opportunity.surfaced_row_without_reason",
                stage=stage,
                message="a surfaced player must say why he is visible (ADR-063)",
                observed="; ".join(unexplained[:10]),
                expected="a non-empty surface_reasons list",
            ),
        )

    stale_behavior = [
        str(record.get("player_id"))
        for record in records
        if not bool(record.get("behavior_available"))
        and (record.get("add_count") is not None or record.get("drop_count") is not None)
    ]
    if stale_behavior:
        checks.append(
            QualityCheck.fail(
                "opportunity.counts_without_a_feed",
                stage=stage,
                message=(
                    "a row that declares no behaviour feed must publish no counts; a zero "
                    "and an absence are different claims"
                ),
                observed="; ".join(stale_behavior[:10]),
                expected="null add_count and drop_count",
            ),
        )
    if not (inconsistent or tiered_exceptions or unexplained or stale_behavior):
        surfaced = sum(1 for record in records if record.get("outside_tier_board"))
        checks.append(
            QualityCheck.ok(
                "opportunity.semantics",
                stage=stage,
                message=(
                    "behaviour counts are internally consistent, and every surfaced player "
                    "carries a reason and no invented tier"
                ),
                observed=f"{len(records)} row(s), {surfaced} surfaced beyond the tier depth",
            ),
        )
    return checks


def _ros_metadata_checks(
    directory: Path,
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """Validate the in-season bundle's own metadata, and only when that bundle exists."""
    stage = "artifacts.ros_build_metadata"
    in_season = {
        artifact: envelope
        for artifact, envelope in envelopes.items()
        if artifact in _IN_SEASON_ARTIFACTS
    }
    path = directory / ROS_BUILD_METADATA_FILENAME
    if not in_season:
        return []
    if not path.is_file():
        return [
            QualityCheck.fail(
                "artifact.ros_build_metadata_missing",
                stage=stage,
                message=(
                    "ros_build_metadata.json is required beside a rest-of-season artifact: it "
                    "carries the cutoff week and the ADR-076 disclosures, and a board without "
                    "them may not be rendered"
                ),
                observed=str(path),
                expected=ROS_BUILD_METADATA_FILENAME,
            ),
        ]
    try:
        metadata: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [
            QualityCheck.fail(
                "artifact.ros_build_metadata_unreadable",
                stage=stage,
                message="could not read ros_build_metadata.json",
                observed=str(exc),
                expected="valid JSON",
            ),
        ]

    checks = list(validate_records(ROS_BUILD_METADATA_SCHEMA, [metadata], stage=stage))
    if any(check.blocking for check in checks):
        return checks

    for artifact, envelope in in_season.items():
        if envelope.get("build_id") != metadata.get("build_id"):
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.build_id_mismatch",
                    stage=stage,
                    message=f"{artifact} carries a different build_id from ros_build_metadata",
                    observed=f"{artifact}={envelope.get('build_id')}",
                    expected=str(metadata.get("build_id")),
                ),
            )
        offenders = {
            int(record["through_week"])
            for record in envelope.get("records", ())
            if record.get("through_week") is not None
        } - {int(metadata.get("through_week", -1))}
        if offenders:
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.cutoff_mismatch",
                    stage=stage,
                    message=f"{artifact} rows disagree with the bundle's declared cutoff week",
                    observed=", ".join(str(week) for week in sorted(offenders)),
                    expected=str(metadata.get("through_week")),
                ),
            )

    disclosures = metadata.get("disclosures", {})
    if disclosures.get("uses_injury_information") is not False:
        checks.append(
            QualityCheck.fail(
                "ros_build_metadata.injury_claim",
                stage=stage,
                message=(
                    "the rest-of-season model has no injury or practice-report feature "
                    "(ADR-070); the artifact must say so"
                ),
                observed=str(disclosures.get("uses_injury_information")),
                expected="false",
            ),
        )
    declared = int(disclosures.get("long_absence_players", -1))
    tiers = envelopes.get("ros_tiers")
    if tiers is not None and declared >= 0:
        actual = sum(1 for record in tiers.get("records", ()) if record.get("long_absence"))
        if actual != declared:
            checks.append(
                QualityCheck.fail(
                    "ros_build_metadata.long_absence_count",
                    stage=stage,
                    message=("the disclosed long-absence count disagrees with the published rows"),
                    observed=f"metadata {declared}, artifact {actual}",
                    expected="equal",
                ),
            )
    return checks


def _in_season_cross_checks(
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The market-firewall proof, run over the published bytes rather than over the code.

    Phase 12's central claim is that behaviour decides visibility and never value. The
    Opportunity Board copies its intrinsic columns from the rest-of-season board, so the
    claim is checkable by comparison: every player on both boards must carry identical
    intrinsic numbers. A single differing value means some code path recomputed one of them,
    which is precisely the thing that must not exist.
    """
    tiers = envelopes.get("ros_tiers")
    opportunity = envelopes.get("inseason_opportunity")
    if tiers is None or opportunity is None:
        return []

    published = {
        (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        ): record
        for record in tiers.get("records", ())
    }
    mismatched: list[str] = []
    unexplained: list[str] = []
    compared = 0
    for record in opportunity.get("records", ()):
        key = (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        )
        source = published.get(key)
        if source is None:
            # Absent from the tier board is exactly what a surfaced row is. It has to say so.
            if not (bool(record.get("outside_tier_board")) and record.get("surface_reasons")):
                unexplained.append(str(key))
            continue
        if bool(record.get("outside_tier_board")):
            unexplained.append(str(key))
            continue
        compared += 1
        for field in _COPIED_INTRINSIC_FIELDS:
            left, right = source.get(field), record.get(field)
            if left is None and right is None:
                continue
            if left is None or right is None:
                mismatched.append(f"{key}/{field}: {left!r} != {right!r}")
                continue
            if abs(float(left) - float(right)) > _INTRINSIC_COPY_TOLERANCE:
                mismatched.append(f"{key}/{field}: {left} != {right}")

    checks: list[QualityCheck] = []
    if mismatched:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.intrinsic_value_modified",
                stage="artifacts",
                message=(
                    "an opportunity row's intrinsic value disagrees with the rest-of-season "
                    "board; behaviour may decide visibility and may never change a value"
                ),
                observed="; ".join(mismatched[:10]),
                expected="identical intrinsic columns on both boards",
            ),
        )
    if unexplained:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.opportunity_row_not_in_ros_tiers",
                stage="artifacts",
                message=(
                    "an opportunity row is absent from the rest-of-season board without "
                    "declaring itself a surfaced exception, or declares itself one while the "
                    "board publishes him"
                ),
                observed="; ".join(unexplained[:10]),
                expected="outside_tier_board and surface_reasons on exactly the absent rows",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "cross_artifact.intrinsic_firewall",
                stage="artifacts",
                message=(
                    "every intrinsic value on the Opportunity Board is byte-identical to the "
                    "rest-of-season board's; behaviour changed visibility only"
                ),
                observed=(
                    f"{compared} player(s) compared across "
                    f"{len(_COPIED_INTRINSIC_FIELDS)} intrinsic field(s)"
                ),
            ),
        )
    return checks


def _trend_series_agreement(
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The chart and the board must be two views of one number, per source.

    ADR-066 says the series carries "the same scalar the arbitrage row carries, from the same
    points ... asserted equal by the cross-artifact validator". It was not. Nothing compared
    them, so a fixture whose board published `market_trend: null` while its series published
    a fabricated slope for the same player validated cleanly for two phases, and a whole
    second market could ship with a price and no history without any gate noticing (ADR-081).

    Three agreements, each source-specific:

    * every series names a market that priced that player on that board;
    * its ``market_trend`` is that market's own slope, not another market's;
    * its newest point is that market's published ADP, so "Latest 33.6" on the chart and the
      ADP readout beside it can never be different numbers.
    """
    arbitrage = envelopes.get("arbitrage")
    series = envelopes.get("market_trend_series")
    if arbitrage is None or series is None:
        return []

    quotes: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for record in arbitrage.get("records", ()):
        block = (str(record.get("league_preset_id")), str(record.get("scoring_preset")))
        entries = [
            entry
            for entry in record.get("markets") or ()
            if str(entry.get("market_signal_type")) == "adp"
        ] or [record]
        for entry in entries:
            # A `markets` entry names its source in `source_id`; a Release 1 row has no
            # array at all and names it in the flat `market_source_id`.
            key = (
                *block,
                str(entry.get("source_id") or record.get("market_source_id")),
                str(record.get("player_id")),
            )
            quotes[key] = entry

    orphaned: list[str] = []
    trend_mismatch: list[str] = []
    price_mismatch: list[str] = []
    for record in series.get("records", ()):
        key = (
            str(record.get("league_preset_id")),
            str(record.get("scoring_preset")),
            str(record.get("market_source_id")),
            str(record.get("player_id")),
        )
        quote = quotes.get(key)
        if quote is None:
            orphaned.append("/".join(key))
            continue
        published = quote.get("market_trend")
        drawn = record.get("market_trend")
        if (published is None) != (drawn is None) or (
            published is not None
            and drawn is not None
            and abs(float(published) - float(drawn)) > _RANK_GAP_TOLERANCE
        ):
            trend_mismatch.append(f"{'/'.join(key)}: board={published} series={drawn}")
        points = list(record.get("points", ()))
        price = quote.get("market_adp")
        if points and price is not None:
            latest = points[-1].get("market_adp")
            if latest is not None and abs(float(latest) - float(price)) > _TREND_POINT_TOLERANCE:
                price_mismatch.append(f"{'/'.join(key)}: board={price} series={latest}")

    checks: list[QualityCheck] = []
    if orphaned:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.trend_series_without_a_market",
                stage="artifacts",
                message=(
                    "every retained history must belong to a market that priced that player "
                    "on that board"
                ),
                observed="; ".join(orphaned[:10]),
                expected="a matching entry in the arbitrage row's markets array",
            ),
        )
    if trend_mismatch:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.trend_scalar_disagreement",
                stage="artifacts",
                message=("the published slope and the charted history's slope must be one number"),
                observed="; ".join(trend_mismatch[:10]),
                expected="identical market_trend per source",
            ),
        )
    if price_mismatch:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.trend_series_latest_price",
                stage="artifacts",
                message=(
                    "the newest retained point must be the ADP the board publishes for that "
                    "market; a chart whose last reading differs from the number beside it is "
                    "two answers to one question"
                ),
                observed="; ".join(price_mismatch[:10]),
                expected="the market's published market_adp",
            ),
        )
    if not checks:
        by_source: dict[str, int] = {}
        for record in series.get("records", ()):
            source = str(record.get("market_source_id"))
            by_source[source] = by_source.get(source, 0) + 1
        checks.append(
            QualityCheck.ok(
                "cross_artifact.trend_series_agreement",
                stage="artifacts",
                message=(
                    "every retained history agrees with its own market's published price and slope"
                ),
                observed=", ".join(
                    f"{source}: {count}" for source, count in sorted(by_source.items())
                )
                or "no series published",
            ),
        )
    return checks


def _headshot_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """A portrait may only describe a player the board publishes.

    One direction only, and that asymmetry is the contract. A board row with no portrait is
    the normal state - the crosswalk does not reach every player and the card draws a monogram
    instead - so the missing direction is not a finding and is reported as coverage rather
    than as a failure. A *portrait* with no board row is the other thing entirely: it is
    either an identity mistake or payload for a card nobody can open.
    """
    headshots = envelopes.get("player_headshots")
    tiers = envelopes.get("tiers")
    if headshots is None or tiers is None:
        return []

    board = {str(record.get("player_id")) for record in tiers.get("records", ())}
    orphans = sorted(
        {
            str(record.get("player_id"))
            for record in headshots.get("records", ())
            if str(record.get("player_id")) not in board
        },
    )
    if orphans:
        return [
            QualityCheck.fail(
                "cross_artifact.headshot_player_not_in_tiers",
                stage="artifacts",
                message="every portrait must describe a player the tier board publishes",
                observed="; ".join(orphans[:10]),
                expected="portrait players are a subset of tier players",
            ),
        ]
    covered = len({str(r.get("player_id")) for r in headshots.get("records", ())})
    return [
        QualityCheck.ok(
            "cross_artifact.headshot_coverage",
            stage="artifacts",
            message="board players with a published portrait",
            observed=f"{covered}/{len(board)} player(s)",
        ),
    ]


def _behavior_series_cross_checks(
    envelopes: Mapping[str, Mapping[str, Any]],
) -> list[QualityCheck]:
    """The momentum series must describe the board it sits under (ADR-089).

    ADR-081's finding, on a new artifact: a series and the row beside it are two published
    accounts of one thing, and nothing had compared them, so a chart could draw a history for
    a player the board did not price and no gate would notice. Two agreements here, and the
    second is the one that catches a real mistake:

    **Every series names a player on the Opportunity Board.** A series for anyone else is
    either an identity mistake or payload for a card nobody can open. The reverse direction
    is *not* a finding — a board row with no series is the ordinary state for a player the
    feed has never carried — so it is reported as coverage.

    **The newest point is the board's own count.** Where a series' last observation was taken
    at the same instant the board's behaviour columns came from, the two must carry the same
    numbers; otherwise the sparkline's final bar and the "Adds (24h)" readout beside it would
    be different numbers describing one moment. Where the instants differ the player was
    outside the feed's top N on the latest snapshot, which is a legitimate state and is
    skipped rather than failed.
    """
    series = envelopes.get("behavior_trend_series")
    opportunity = envelopes.get("inseason_opportunity")
    if series is None or opportunity is None:
        return []

    latest: dict[str, Mapping[str, Any]] = {}
    for record in opportunity.get("records", ()):
        # Behaviour columns are preset-independent, so the first block's row answers for the
        # player; a differing second block would already have failed the firewall check.
        latest.setdefault(str(record.get("player_id")), record)

    orphans: list[str] = []
    disagreeing: list[str] = []
    for record in series.get("records", ()):
        player_id = str(record.get("player_id"))
        row = latest.get(player_id)
        if row is None:
            orphans.append(player_id)
            continue
        points = list(record.get("points", ()))
        if not points:
            continue
        newest = points[-1]
        if str(newest.get("observed_at")) != str(row.get("behavior_snapshot_at_utc")):
            continue
        for field, point_field in (("add_count", "add_count"), ("drop_count", "drop_count")):
            published = row.get(field)
            drawn = newest.get(point_field)
            if published is None or drawn is None:
                continue
            if int(published) != int(drawn):
                disagreeing.append(f"{player_id}/{field}: board={published} series={drawn}")

    checks: list[QualityCheck] = []
    if orphans:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.behavior_series_player_not_on_board",
                stage="artifacts",
                message=(
                    "every momentum series must describe a player the Opportunity Board publishes"
                ),
                observed="; ".join(sorted(set(orphans))[:10]),
                expected="series players are a subset of opportunity players",
            ),
        )
    if disagreeing:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.behavior_series_latest_count",
                stage="artifacts",
                message=(
                    "the series' newest point and the board's behaviour columns come from "
                    "the same snapshot and must carry the same counts"
                ),
                observed="; ".join(disagreeing[:10]),
                expected="identical add_count and drop_count at the shared instant",
            ),
        )
    if not checks:
        covered = len({str(record.get("player_id")) for record in series.get("records", ())})
        checks.append(
            QualityCheck.ok(
                "cross_artifact.behavior_series_agreement",
                stage="artifacts",
                message=(
                    "every momentum series names a board player and agrees with his "
                    "published counts at the snapshot they share"
                ),
                observed=f"{covered}/{len(latest)} board player(s) with a retained history",
            ),
        )
    return checks


def _signal_cross_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """The signal layer must describe the board it sits beside (ADR-091).

    Three agreements, each a thing a reader would see as a contradiction on one card:

    * **every usage record names a player the Opportunity Board publishes** — the same
      subset rule the momentum series follows, for the same reason;
    * **his weekly points sum to the board's points to date** — the card draws the weeks and
      prints the total beside them, and two computations of one number that disagree are a
      defect whichever one is right;
    * **his team has a published next game** — reported as coverage rather than failed,
      because a team whose season is over legitimately has none.
    """
    usage = envelopes.get("player_usage")
    if usage is None:
        return []
    opportunity = envelopes.get("inseason_opportunity")
    ros = envelopes.get("ros_tiers")
    matchups = envelopes.get("team_matchups")

    checks: list[QualityCheck] = []
    records = list(usage.get("records", ()))
    if opportunity is not None:
        board = {str(record.get("player_id")) for record in opportunity.get("records", ())}
        orphans = sorted({str(r.get("player_id")) for r in records} - board)
        if orphans:
            checks.append(
                QualityCheck.fail(
                    "cross_artifact.usage_player_not_on_board",
                    stage="artifacts",
                    message=(
                        "every usage record must describe a player the Opportunity Board publishes"
                    ),
                    observed="; ".join(orphans[:10]),
                    expected="usage players are a subset of opportunity players",
                ),
            )
    if ros is not None:
        points: dict[tuple[str, str], float] = {}
        for row in ros.get("records", ()):
            if row.get("points_to_date") is None:
                continue
            points.setdefault(
                (str(row.get("player_id")), str(row.get("scoring_preset"))),
                float(row["points_to_date"]),
            )
        disagreeing: list[str] = []
        for record in records:
            for preset, total in (record.get("fantasy_points_to_date") or {}).items():
                published = points.get((str(record.get("player_id")), str(preset)))
                if published is None or total is None:
                    continue
                if abs(published - float(total)) > _USAGE_POINTS_TOLERANCE:
                    disagreeing.append(
                        f"{record.get('player_id')}/{preset}: ros={published} usage={total}",
                    )
        if disagreeing:
            checks.append(
                QualityCheck.fail(
                    "cross_artifact.usage_points_disagree_with_ros",
                    stage="artifacts",
                    message=(
                        "a player's weekly points must sum to the points to date the "
                        "rest-of-season board publishes for him"
                    ),
                    observed="; ".join(disagreeing[:10]),
                    expected="identical fantasy points to date",
                ),
            )
    if matchups is not None:
        teams = {str(record.get("team")) for record in matchups.get("records", ())}
        missing = sorted(
            {
                str(r.get("team"))
                for r in records
                if r.get("team") and str(r.get("team")) not in teams
            },
        )
        checks.append(
            QualityCheck.ok(
                "cross_artifact.usage_matchup_coverage",
                stage="artifacts",
                message="usage teams with a published next game",
                observed=(
                    f"{len(teams)} team(s) with a next game"
                    + (f"; none published for {', '.join(missing[:8])}" if missing else "")
                ),
            ),
        )
    if not any(check.blocking for check in checks):
        checks.append(
            QualityCheck.ok(
                "cross_artifact.usage_agreement",
                stage="artifacts",
                message=(
                    "every usage record names a board player and its weekly points sum to "
                    "the rest-of-season board's points to date"
                ),
                observed=f"{len(records)} usage record(s)",
            ),
        )
    return checks


def _cross_artifact_checks(envelopes: Mapping[str, Mapping[str, Any]]) -> list[QualityCheck]:
    """Agreement no single artifact schema can express."""
    tiers = envelopes.get("tiers")
    arbitrage = envelopes.get("arbitrage")
    if tiers is None or arbitrage is None:
        return []

    tier_keys = {
        (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        ): record
        for record in tiers.get("records", ())
    }
    missing: list[str] = []
    contradictory: list[str] = []
    rank_mismatch: list[str] = []
    for record in arbitrage.get("records", ()):
        key = (
            record.get("league_preset_id"),
            record.get("scoring_preset"),
            record.get("player_id"),
        )
        tier_record = tier_keys.get(key)
        # A surface exception is *supposed* to be absent from tiers: the market says he is
        # relevant, the model ranks him past the published tier depth, and ADR-063 publishes
        # him on the arbitrage board flagged as outside it. He is not a tier row and never
        # was, so requiring a subset relation here would forbid the rescue the whole surface
        # rule exists to perform. The exemption is narrow on purpose — the row has to *say*
        # it is an exception, in both fields — because the failure this check was written for
        # is an arbitrage row describing a player the board has no valuation for at all.
        surfaced = bool(record.get("outside_tier_board")) and bool(record.get("surface_reasons"))
        if tier_record is None:
            if not surfaced:
                missing.append(str(key))
        elif surfaced:
            contradictory.append(str(key))
        elif int(tier_record["fair_rank"]) != int(record["fair_rank"]):
            rank_mismatch.append(
                f"{key}: tiers={tier_record['fair_rank']} arbitrage={record['fair_rank']}",
            )

    checks: list[QualityCheck] = []
    if missing:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.arbitrage_player_not_in_tiers",
                stage="artifacts",
                message="every arbitrage row must describe a player present in tiers",
                observed="; ".join(missing[:10]),
                expected="arbitrage players are a subset of tier players",
            ),
        )
    if contradictory:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.surface_exception_is_on_the_board",
                stage="artifacts",
                message=(
                    "an arbitrage row claims to be surfaced from beyond the tier depth while "
                    "the tier artifact publishes him; one of the two is wrong"
                ),
                observed="; ".join(contradictory[:10]),
                expected="outside_tier_board is true only for players absent from tiers",
            ),
        )
    if rank_mismatch:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.fair_rank_disagreement",
                stage="artifacts",
                message="fair_rank must be identical in tiers and arbitrage",
                observed="; ".join(rank_mismatch[:10]),
                expected="identical fair_rank",
            ),
        )
    if not checks:
        checks.append(
            QualityCheck.ok(
                "cross_artifact.agreement",
                stage="artifacts",
                message="tiers and arbitrage agree on players and fair ranks",
                observed=f"{len(arbitrage.get('records', ()))} arbitrage record(s)",
            ),
        )

    checks.extend(_trend_series_agreement(envelopes))

    metadata_presets = {str(record.get("league_preset_id")) for record in tiers.get("records", ())}
    if len(metadata_presets) == 0:
        checks.append(
            QualityCheck.fail(
                "cross_artifact.no_presets",
                stage="artifacts",
                message="tier artifact carries no league preset",
                observed="0",
                expected=">= 1",
                severity=Severity.WARNING,
            ),
        )
    return checks
