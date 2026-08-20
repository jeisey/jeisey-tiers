"""The Phase-5 cohort measurement, run offline against a retained snapshot.

**Boundary module.** Market data only.

ADR-012's amendment requires the cohort mix to be re-measured at the start of Phase 5,
because the original 2026-08-17 counts came from only 410 aggregated drafts. ADR-039 froze
the rule that decides what the measurement means, before the measurement existed.

The measurement reads a **retained snapshot** rather than the network. That makes it
reproducible — the same snapshot always produces the same report — and it makes the report
diffable against the evidence commit that produced it, which a live re-run could never be.

Board coverage is measured conservatively. A cohort's `top100_board_coverage` is the
*minimum* over the launch scoring presets of the share of that preset's top 100 the cohort
prices, so a cohort cannot pass by covering one scoring preset well and another badly. The
per-preset numbers are all reported.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ffdraft.contracts import CORE_POSITIONS, EntityKind, Position
from ffdraft.market.cohorts import (
    COHORT_RULE_VERSION,
    COHORT_SUFFICIENCY_RULE,
    CohortAssignment,
    CohortMeasurement,
    CohortSufficiency,
    CohortSufficiencyRule,
    select_cohorts,
)
from ffdraft.market.snapshot import MarketSnapshot
from ffdraft.timeutil import isoformat_utc

__all__ = [
    "BoardIndex",
    "CohortReport",
    "board_from_tier_records",
    "measure_cohorts",
    "report_markdown",
]

TOP_100 = 100
TOP_150 = 150


@dataclass(frozen=True, slots=True)
class BoardIndex:
    """The published fair board, as ordered canonical ids per scoring preset."""

    league_preset_id: str
    by_scoring: Mapping[str, tuple[str, ...]]

    def top(self, scoring_preset: str, depth: int) -> tuple[str, ...]:
        return self.by_scoring.get(scoring_preset, ())[:depth]

    def union_top(self, depth: int) -> frozenset[str]:
        return frozenset(
            player_id for scoring in self.by_scoring for player_id in self.top(scoring, depth)
        )

    @property
    def scoring_presets(self) -> tuple[str, ...]:
        return tuple(sorted(self.by_scoring))


def board_from_tier_records(
    records: Sequence[Mapping[str, Any]],
    *,
    league_preset_id: str,
) -> BoardIndex:
    """Build the reference board from a tier artifact's records."""
    ordered: dict[str, list[tuple[int, str]]] = {}
    for record in records:
        if str(record.get("league_preset_id")) != league_preset_id:
            continue
        scoring = str(record["scoring_preset"])
        ordered.setdefault(scoring, []).append(
            (int(record["fair_rank"]), str(record["player_id"])),
        )
    return BoardIndex(
        league_preset_id=league_preset_id,
        by_scoring={
            scoring: tuple(player_id for _, player_id in sorted(rows))
            for scoring, rows in sorted(ordered.items())
        },
    )


@dataclass
class CohortReport:
    """Everything the cohort study measured, judged and selected."""

    season: int
    source_id: str
    snapshot_key: str
    snapshot_at_utc: str
    generated_at_utc: str
    rule: Mapping[str, Any]
    board_league_preset_id: str
    board_depths: Mapping[str, int]
    measurements: dict[str, CohortMeasurement] = field(default_factory=dict)
    verdicts: dict[str, CohortSufficiency] = field(default_factory=dict)
    assignments: dict[tuple[str, int], CohortAssignment] = field(default_factory=dict)
    per_scoring_coverage: dict[str, dict[str, float]] = field(default_factory=dict)
    git_sha: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": "1.0",
            "rule_version": COHORT_RULE_VERSION,
            "season": self.season,
            "source_id": self.source_id,
            "snapshot_key": self.snapshot_key,
            "snapshot_at_utc": self.snapshot_at_utc,
            "generated_at_utc": self.generated_at_utc,
            "git_sha": self.git_sha,
            "board": {
                "league_preset_id": self.board_league_preset_id,
                "depths": dict(self.board_depths),
            },
            "rule": dict(self.rule),
            "cohorts": [
                {
                    **self.measurements[cohort_id].to_dict(),
                    "verdict": self.verdicts[cohort_id].to_dict(),
                    "per_scoring_top100_coverage": self.per_scoring_coverage.get(cohort_id, {}),
                }
                for cohort_id in sorted(self.measurements)
            ],
            "assignments": [
                assignment.to_dict() for _, assignment in sorted(self.assignments.items())
            ],
        }


def _core_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], int, int]:
    """Split player rows into core-position, non-core and unclassifiable.

    Position comes from the MFL player directory's raw token, which is available whether or
    not the row resolved - so an unresolved quarterback still counts in the identity
    denominator, which is the whole point of measuring coverage. ``Position.parse`` matches
    exactly, so MFL's team aggregates can never be read as a player position (AGENTS.md
    section 6).
    """
    core: list[Mapping[str, Any]] = []
    non_core = 0
    unclassified = 0
    for row in rows:
        raw = row.get("raw_position") or row.get("position")
        position = Position.parse(str(raw)) if raw else None
        if position is None:
            unclassified += 1
        elif position in CORE_POSITIONS:
            core.append(row)
        else:
            non_core += 1
    return core, non_core, unclassified


def _coverage(priced: frozenset[str], board: Sequence[str]) -> float:
    if not board:
        return 0.0
    return sum(1 for player_id in board if player_id in priced) / len(board)


def measure_cohorts(
    snapshot: MarketSnapshot,
    *,
    board: BoardIndex,
    presets: Sequence[tuple[str, int]],
    generated_at: Any,
    rule: CohortSufficiencyRule = COHORT_SUFFICIENCY_RULE,
    git_sha: str | None = None,
) -> CohortReport:
    """Measure every cohort in a retained snapshot, judge it, and select per preset."""
    manifest = snapshot.manifest
    measurements: dict[str, CohortMeasurement] = {}
    per_scoring: dict[str, dict[str, float]] = {}
    union_top150 = board.union_top(TOP_150)

    for capture in manifest.cohorts:
        all_rows = list(snapshot.rows_for(capture.cohort_id))
        player_rows = [
            row for row in all_rows if str(row.get("entity_kind")) == str(EntityKind.PLAYER)
        ]
        rows, non_core, unclassified = _core_rows(player_rows)
        priced_ids = frozenset(str(row["player_id"]) for row in rows if row.get("player_id"))
        top100 = {
            scoring: _coverage(priced_ids, board.top(scoring, TOP_100))
            for scoring in board.scoring_presets
        }
        top150 = {
            scoring: _coverage(priced_ids, board.top(scoring, TOP_150))
            for scoring in board.scoring_presets
        }
        per_scoring[capture.cohort_id] = {k: round(v, 4) for k, v in top100.items()}

        samples = [
            int(row["sample_size"])
            for row in rows
            if row.get("sample_size") is not None
            and row.get("player_id")
            and str(row["player_id"]) in union_top150
        ]
        prices = [float(row["average_pick"]) for row in rows if row.get("average_pick")]
        measurements[capture.cohort_id] = CohortMeasurement(
            cohort_id=capture.cohort_id,
            filters=dict(capture.filters),
            priced_players=len(rows),
            total_drafts=capture.total_drafts,
            total_picks=capture.total_picks,
            resolved_players=len(priced_ids),
            resolvable_players=len(rows),
            ambiguous_players=capture.ambiguous_players,
            non_player_entities=capture.non_player_entities,
            total_rows=len(all_rows),
            non_core_rows=non_core,
            unclassified_rows=unclassified,
            top100_board_coverage=min(top100.values()) if top100 else 0.0,
            top150_board_coverage=min(top150.values()) if top150 else 0.0,
            median_top150_sample_size=(float(statistics.median(samples)) if samples else None),
            min_pick_available=sum(1 for row in rows if row.get("min_pick") is not None),
            max_pick_available=sum(1 for row in rows if row.get("max_pick") is not None),
            adp_min=min(prices) if prices else None,
            adp_max=max(prices) if prices else None,
        )

    assignments, verdicts = select_cohorts(measurements, presets=presets, rule=rule)
    return CohortReport(
        season=manifest.season,
        source_id=manifest.source_id,
        snapshot_key=manifest.snapshot_key,
        snapshot_at_utc=manifest.retrieved_at_utc,
        generated_at_utc=isoformat_utc(generated_at),
        rule=rule.to_dict(),
        board_league_preset_id=board.league_preset_id,
        board_depths={scoring: len(board.by_scoring[scoring]) for scoring in board.scoring_presets},
        measurements=measurements,
        verdicts=verdicts,
        assignments=assignments,
        per_scoring_coverage=per_scoring,
        git_sha=git_sha,
    )


def report_markdown(report: CohortReport) -> str:
    """Render the human-readable half of the study. Generated, never hand-edited."""
    lines: list[str] = [
        f"# MFL cohort measurement — {report.season}",
        "",
        f"Snapshot `{report.snapshot_key}` retrieved {report.snapshot_at_utc}, "
        f"source `{report.source_id}`. Rule `{report.rule['rule_version']}` (ADR-039), "
        f"frozen before this measurement existed.",
        "",
        f"Board coverage is measured against the `{report.board_league_preset_id}` fair board "
        "and reported as the minimum over the launch scoring presets, so a cohort cannot pass "
        "by covering one preset well and another badly.",
        "",
        "## Cohorts",
        "",
        "| cohort | filters | priced | drafts | top-100 | top-150 | median sample "
        "| identity | verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for cohort_id in sorted(report.measurements):
        m = report.measurements[cohort_id]
        v = report.verdicts[cohort_id]
        filters = "&".join(f"{k}={val}" for k, val in sorted(m.filters.items())) or "—"
        median = (
            "—" if m.median_top150_sample_size is None else f"{m.median_top150_sample_size:.0f}"
        )
        drafts = "—" if m.total_drafts is None else str(m.total_drafts)
        lines.append(
            f"| `{cohort_id}` | `{filters}` | {m.priced_players} | {drafts} | "
            f"{m.top100_board_coverage:.3f} | {m.top150_board_coverage:.3f} | {median} | "
            f"{m.identity_coverage:.3f} | {'**sufficient**' if v.sufficient else 'insufficient'} |",
        )

    lines += ["", "## Why each cohort failed", ""]
    failures = [
        (cohort_id, verdict)
        for cohort_id, verdict in sorted(report.verdicts.items())
        if not verdict.sufficient
    ]
    if failures:
        for cohort_id, verdict in failures:
            lines.append(f"- `{cohort_id}`: " + "; ".join(verdict.failed_clauses))
    else:
        lines.append("Every measured cohort met the rule.")

    lines += [
        "",
        "## Selection",
        "",
        "| scoring | teams | cohort | filters | exact | sufficient | reason |",
        "|---|---:|---|---|---|---|---|",
    ]
    for _, assignment in sorted(report.assignments.items()):
        filters = "&".join(f"{k}={v}" for k, v in sorted(assignment.cohort.filters.items())) or "—"
        lines.append(
            f"| {assignment.scoring_preset} | {assignment.league_size} | "
            f"`{assignment.cohort.cohort_id}` | `{filters}` | "
            f"{'yes' if assignment.exact else 'no'} | "
            f"{'yes' if assignment.sufficient else 'no'} | {assignment.reason} |",
        )
    lines += [
        "",
        "HALF-PPR can never be exact on this source: MFL exposes `IS_PPR` as a boolean and "
        "publishes no half-PPR filter (ADR-039).",
        "",
    ]
    return "\n".join(lines)
