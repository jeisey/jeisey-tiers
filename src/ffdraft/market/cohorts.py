"""MFL cohort catalogue, the frozen sufficiency rule, and cohort selection.

**Boundary module.** Everything here is market data; nothing under an intrinsic feature
package may import it (`docs/ARCHITECTURE.md` 3.1, enforced by
``tests/contract/test_architecture_boundary.py``).

A *cohort* is a request, defined by the filters sent to MFL. A *preset* is a league shape
this project publishes a board for. The two are not the same thing, and ADR-012 exists
because pretending otherwise would serve an unfiltered aggregate as preset-specific ADP.

This module answers one question: **which cohort should serve each preset?** The answer has
to be an evidence-driven measurement, and the risk in an evidence-driven measurement is
that the threshold gets chosen after the numbers are in. So the rule is written here as a
frozen dataclass with a pure evaluator, committed before the measurement runs, exactly as
`ffdraft.modeling.rules` was for Phase 4. ADR-039 records every bound and why it sits there.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ffdraft.contracts import MarketCohort

__all__ = [
    "CANDIDATE_COHORTS",
    "COHORT_RULE_VERSION",
    "COHORT_SUFFICIENCY_RULE",
    "CohortAssignment",
    "CohortMeasurement",
    "CohortSufficiency",
    "CohortSufficiencyRule",
    "assignments_from_report",
    "cohort_by_id",
    "select_cohorts",
    "widest_cohort",
]

#: The frozen rule's version. A change to any bound below is a new version with its own ADR.
COHORT_RULE_VERSION = "phase5_cohort_v1"

#: Flag emitted when a preset is served by a cohort that failed the sufficiency rule.
COHORT_INSUFFICIENT = "cohort_insufficient"
#: Flag emitted whenever a preset's cohort is not exact for it (ADR-012).
COHORT_APPROXIMATE = "cohort_approximate"


# --------------------------------------------------------------------------------------
# The candidate catalogue
# --------------------------------------------------------------------------------------
#
# Phase 0 verified which filters MFL honours: IS_PPR, FCOUNT, IS_MOCK and IS_KEEPER are
# applied; CUTOFF is accepted with no effect at usable thresholds; DAYS is ignored
# (docs/DATA_SOURCES.md 13.5). Only honoured filters appear here, because a candidate built
# on an ignored filter would be a duplicate of the unfiltered aggregate wearing a label.
#
# `scoring_semantics` is what the filter *means*, not what we would like it to mean.
# IS_PPR is a boolean, so it can express PPR and STD and nothing in between: HALF has no
# exact cohort on this source and never will until MFL publishes one (ADR-039).

_UNFILTERED = MarketCohort(
    cohort_id="unfiltered",
    filters={},
    label="all drafts",
)

_SCORING_COHORTS = (
    MarketCohort(
        cohort_id="ppr",
        filters={"IS_PPR": "1"},
        label="PPR drafts",
        scoring_semantics="PPR",
    ),
    MarketCohort(
        cohort_id="std",
        filters={"IS_PPR": "0"},
        label="non-PPR drafts",
        scoring_semantics="STD",
    ),
)

_SIZE_COHORTS = tuple(
    MarketCohort(
        cohort_id=f"fcount{size}",
        filters={"FCOUNT": str(size)},
        label=f"{size}-team drafts",
        league_size_semantics=size,
    )
    for size in (10, 12, 14)
)

_INTERSECTION_COHORTS = tuple(
    MarketCohort(
        cohort_id=f"{scoring.cohort_id}-fcount{size}",
        filters={**scoring.filters, "FCOUNT": str(size)},
        label=f"{scoring.label}, {size} teams",
        scoring_semantics=scoring.scoring_semantics,
        league_size_semantics=size,
    )
    for scoring in _SCORING_COHORTS
    for size in (10, 12, 14)
)

# Draft *format* candidates. Mocks and keeper/dynasty leagues price players differently, and
# Phase 0 measured both filters as honoured. These are measured because "is the aggregate
# polluted, and by which of the two?" is a question the report has to be able to answer -
# and the 2026-08-20 measurement showed it is: 2026 rookies priced three to five times
# earlier in the aggregate than in the non-keeper cohort, while established veterans barely
# moved. That is the signature of dynasty rookie drafts, where only rookies are selectable
# and a rookie's "average pick" is a pick number in a rookie-only draft.
_FORMAT_COHORTS = (
    MarketCohort(
        cohort_id="no-keeper",
        filters={"IS_KEEPER": "N"},
        label="non-keeper drafts",
    ),
    MarketCohort(
        cohort_id="no-mock",
        filters={"IS_MOCK": "0"},
        label="non-mock drafts",
    ),
    MarketCohort(
        cohort_id="no-mock-no-keeper",
        filters={"IS_MOCK": "0", "IS_KEEPER": "N"},
        label="non-mock, non-keeper drafts",
    ),
    MarketCohort(
        cohort_id="ppr-no-keeper",
        filters={"IS_PPR": "1", "IS_KEEPER": "N"},
        label="non-keeper PPR drafts",
        scoring_semantics="PPR",
    ),
)

#: Every cohort the Phase-5 measurement requests, in a stable order.
CANDIDATE_COHORTS: tuple[MarketCohort, ...] = (
    _UNFILTERED,
    *_SCORING_COHORTS,
    *_SIZE_COHORTS,
    *_INTERSECTION_COHORTS,
    *_FORMAT_COHORTS,
)

_BY_ID: Mapping[str, MarketCohort] = {cohort.cohort_id: cohort for cohort in CANDIDATE_COHORTS}


def cohort_by_id(cohort_id: str) -> MarketCohort:
    """Look up a candidate cohort by id."""
    try:
        return _BY_ID[cohort_id]
    except KeyError as exc:  # pragma: no cover - guarded by tests
        raise KeyError(f"unknown cohort {cohort_id!r}; known: {sorted(_BY_ID)}") from exc


def widest_cohort() -> MarketCohort:
    """The unfiltered aggregate - ADR-012's "widest reliable cohort" and the last resort."""
    return _UNFILTERED


# --------------------------------------------------------------------------------------
# The measurement
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortMeasurement:
    """What one cohort looked like in one retained snapshot.

    Every field is an observation, never a judgement. The verdict is
    :class:`CohortSufficiency`, computed from these by the frozen rule.
    """

    cohort_id: str
    filters: Mapping[str, str]
    #: Core-position (QB/RB/WR/TE) rows the cohort priced, before identity resolution.
    #: This is the population every rule clause is written about: the published board is
    #: core-position only, and `docs/DATA_CONTRACTS.md` 12 defines the identity threshold
    #: over "current model-eligible QB/RB/WR/TE players". Kickers, team defences and IDP
    #: rows are counted separately below rather than diluting either denominator.
    priced_players: int
    #: MFL's per-cohort ``totalDrafts``, when the envelope supplied one.
    total_drafts: int | None
    total_picks: int | None
    #: Core-position rows that resolved to a canonical player, and their denominator.
    resolved_players: int
    resolvable_players: int
    ambiguous_players: int
    non_player_entities: int
    #: Share of the published fair board's top N that this cohort prices.
    top100_board_coverage: float
    top150_board_coverage: float
    #: Median ``draftsSelectedIn`` over priced players inside the board's top 150.
    median_top150_sample_size: float | None
    min_pick_available: int
    max_pick_available: int
    adp_min: float | None
    adp_max: float | None
    #: Descriptive counts over the whole cohort payload, core and non-core alike.
    total_rows: int = 0
    non_core_rows: int = 0
    #: Rows the player directory could not position at all. Reported rather than assumed
    #: non-core: an unclassifiable row is a directory gap, and hiding it in the "not our
    #: problem" bucket is how a coverage regression goes unnoticed.
    unclassified_rows: int = 0

    @property
    def identity_coverage(self) -> float:
        return self.resolved_players / self.resolvable_players if self.resolvable_players else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "filters": dict(self.filters),
            "priced_players": self.priced_players,
            "total_drafts": self.total_drafts,
            "total_picks": self.total_picks,
            "resolved_players": self.resolved_players,
            "resolvable_players": self.resolvable_players,
            "ambiguous_players": self.ambiguous_players,
            "non_player_entities": self.non_player_entities,
            "total_rows": self.total_rows,
            "non_core_rows": self.non_core_rows,
            "unclassified_rows": self.unclassified_rows,
            "identity_coverage": round(self.identity_coverage, 4),
            "top100_board_coverage": round(self.top100_board_coverage, 4),
            "top150_board_coverage": round(self.top150_board_coverage, 4),
            "median_top150_sample_size": self.median_top150_sample_size,
            "min_pick_available": self.min_pick_available,
            "max_pick_available": self.max_pick_available,
            "adp_min": self.adp_min,
            "adp_max": self.adp_max,
        }


# --------------------------------------------------------------------------------------
# The frozen rule (ADR-039)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortSufficiency:
    """One cohort's verdict, clause by clause, so a failure names itself."""

    cohort_id: str
    sufficient: bool
    failed_clauses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "sufficient": self.sufficient,
            "failed_clauses": list(self.failed_clauses),
        }


@dataclass(frozen=True, slots=True)
class CohortSufficiencyRule:
    """When a cohort is trustworthy enough to serve a preset.

    Written and committed before the measurement it decides (ADR-039). Every bound is a
    judgement about what would make a market slice *readable*, not a description of what
    the current snapshot happens to score.
    """

    version: str = COHORT_RULE_VERSION
    #: Structural floor. The published board is 300 deep.
    min_priced_players: int = 200
    #: Below the 410-draft aggregate ADR-012 was written against.
    min_total_drafts: int = 300
    #: The top 100 is where a draft is decided.
    min_top100_board_coverage: float = 0.95
    #: The deeper board tolerates more gaps.
    min_top150_board_coverage: float = 0.90
    #: Cohort-level draft counts can be inflated by drafts that touched few players; the
    #: per-player median asks how many drafts actually priced *this* player.
    min_median_top150_sample_size: float = 25.0
    #: The launch identity threshold (`docs/DATA_CONTRACTS.md` 12).
    min_identity_coverage: float = 0.95

    def evaluate(self, measurement: CohortMeasurement) -> CohortSufficiency:
        """Judge one measured cohort. Pure; every clause reports independently."""
        failed: list[str] = []
        if measurement.priced_players < self.min_priced_players:
            failed.append(
                f"priced_players {measurement.priced_players} < {self.min_priced_players}",
            )
        drafts = measurement.total_drafts
        if drafts is None or drafts < self.min_total_drafts:
            failed.append(f"total_drafts {drafts} < {self.min_total_drafts}")
        if measurement.top100_board_coverage < self.min_top100_board_coverage:
            failed.append(
                f"top100_board_coverage {measurement.top100_board_coverage:.3f} "
                f"< {self.min_top100_board_coverage}",
            )
        if measurement.top150_board_coverage < self.min_top150_board_coverage:
            failed.append(
                f"top150_board_coverage {measurement.top150_board_coverage:.3f} "
                f"< {self.min_top150_board_coverage}",
            )
        median = measurement.median_top150_sample_size
        if median is None or median < self.min_median_top150_sample_size:
            failed.append(
                f"median_top150_sample_size {median} < {self.min_median_top150_sample_size}",
            )
        if measurement.identity_coverage < self.min_identity_coverage:
            failed.append(
                f"identity_coverage {measurement.identity_coverage:.3f} "
                f"< {self.min_identity_coverage}",
            )
        return CohortSufficiency(
            cohort_id=measurement.cohort_id,
            sufficient=not failed,
            failed_clauses=tuple(failed),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_version": self.version,
            "min_priced_players": self.min_priced_players,
            "min_total_drafts": self.min_total_drafts,
            "min_top100_board_coverage": self.min_top100_board_coverage,
            "min_top150_board_coverage": self.min_top150_board_coverage,
            "min_median_top150_sample_size": self.min_median_top150_sample_size,
            "min_identity_coverage": self.min_identity_coverage,
        }


#: The production rule. Frozen at ADR-039; edit only through a new version.
COHORT_SUFFICIENCY_RULE = CohortSufficiencyRule()


# --------------------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CohortAssignment:
    """Which cohort serves one (scoring preset, league size), and how honestly."""

    scoring_preset: str
    league_size: int
    cohort: MarketCohort
    exact: bool
    sufficient: bool
    #: Why the winner won, in words a report can print.
    reason: str
    failed_clauses: tuple[str, ...] = field(default=())

    @property
    def approximate(self) -> bool:
        return not self.exact

    @property
    def source_format_detail(self) -> str:
        return self.cohort.source_format_detail(approximate=self.approximate)

    @property
    def quality_flags(self) -> tuple[str, ...]:
        flags: list[str] = []
        if self.approximate:
            flags.append(COHORT_APPROXIMATE)
        if not self.sufficient:
            flags.append(COHORT_INSUFFICIENT)
        return tuple(flags)

    def to_dict(self) -> dict[str, object]:
        return {
            "scoring_preset": self.scoring_preset,
            "league_size": self.league_size,
            "cohort_id": self.cohort.cohort_id,
            "filters": dict(self.cohort.filters),
            "source_format_detail": self.source_format_detail,
            "exact": self.exact,
            "approximate": self.approximate,
            "sufficient": self.sufficient,
            "reason": self.reason,
            "failed_clauses": list(self.failed_clauses),
            "quality_flags": list(self.quality_flags),
        }


def _candidates_for(
    scoring_preset: str,
    league_size: int,
    available: Sequence[MarketCohort],
) -> list[MarketCohort]:
    """Cohorts that may serve this preset, most specific first.

    A cohort qualifies when it does not *contradict* the preset: an unconstrained axis is
    always compatible, a constrained one must match. `IS_PPR=0` therefore never serves a
    PPR league, and a 14-team cohort never serves a 10-team one - approximation is allowed
    to be wide, never wrong.
    """
    qualifying = [
        cohort
        for cohort in available
        if (cohort.scoring_semantics is None or cohort.scoring_semantics == scoring_preset)
        and (cohort.league_size_semantics is None or cohort.league_size_semantics == league_size)
    ]
    return sorted(qualifying, key=lambda cohort: (-cohort.specificity, cohort.cohort_id))


def select_cohorts(
    measurements: Mapping[str, CohortMeasurement],
    *,
    presets: Sequence[tuple[str, int]],
    rule: CohortSufficiencyRule = COHORT_SUFFICIENCY_RULE,
) -> tuple[dict[tuple[str, int], CohortAssignment], dict[str, CohortSufficiency]]:
    """Apply the frozen rule and choose one cohort per preset.

    Returns the assignments and every cohort's verdict, so a report can show the losers as
    well as the winner. Selection is a pure function of the measurements and the rule: it
    never reads the network and never looks at which players a cohort happens to like.
    """
    verdicts = {
        cohort_id: rule.evaluate(measurement)
        for cohort_id, measurement in sorted(measurements.items())
    }
    available = [cohort for cohort in CANDIDATE_COHORTS if cohort.cohort_id in measurements]

    assignments: dict[tuple[str, int], CohortAssignment] = {}
    for scoring_preset, league_size in presets:
        candidates = _candidates_for(scoring_preset, league_size, available)
        chosen: MarketCohort | None = None
        reason = ""
        for cohort in candidates:
            if verdicts[cohort.cohort_id].sufficient:
                chosen = cohort
                reason = (
                    "most specific sufficient candidate"
                    if cohort.specificity
                    else "widest sufficient candidate"
                )
                break
        if chosen is None:
            # Nothing passed. A thin market is still the market; publish it flagged rather
            # than withhold an arbitrage board entirely (ADR-039).
            chosen = widest_cohort() if widest_cohort() in candidates else candidates[-1]
            reason = "no candidate met the sufficiency rule; widest candidate used and flagged"
        verdict = verdicts[chosen.cohort_id]
        assignments[(scoring_preset, league_size)] = CohortAssignment(
            scoring_preset=scoring_preset,
            league_size=league_size,
            cohort=chosen,
            exact=chosen.is_exact_for(scoring_preset, league_size),
            sufficient=verdict.sufficient,
            reason=reason,
            failed_clauses=verdict.failed_clauses,
        )
    return assignments, verdicts


def assignments_from_report(
    payload: Mapping[str, object],
) -> dict[tuple[str, int], CohortAssignment]:
    """Rebuild the selection from a committed cohort report.

    The report is the durable record of a decision the frozen rule made against a specific
    retained snapshot. An arbitrage build reads it rather than re-deriving the selection, so
    the board and the report can never disagree about which cohort served which preset — and
    a reader auditing a board has one file to look at.
    """
    rows = payload.get("assignments", ())
    if not isinstance(rows, Sequence):  # pragma: no cover - malformed report
        raise ValueError("cohort report has no assignments array")
    assignments: dict[tuple[str, int], CohortAssignment] = {}
    for row in rows:
        if not isinstance(row, Mapping):  # pragma: no cover - malformed report
            raise ValueError(f"unreadable cohort assignment: {row!r}")
        scoring = str(row["scoring_preset"])
        league_size = int(row["league_size"])
        assignments[(scoring, league_size)] = CohortAssignment(
            scoring_preset=scoring,
            league_size=league_size,
            cohort=cohort_by_id(str(row["cohort_id"])),
            exact=bool(row["exact"]),
            sufficient=bool(row["sufficient"]),
            reason=str(row.get("reason", "")),
            failed_clauses=tuple(str(item) for item in row.get("failed_clauses", ())),
        )
    return assignments
