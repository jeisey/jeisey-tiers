"""Record linkage for market sources that publish no id bridge (Phase 10, ADR-061).

MyFantasyLeague resolves by id: its export carries an `espn_id`, the canonical registry
indexes `espn_id`, and :mod:`ffdraft.identity.resolver` joins the two with a second bridge
as a cross-check. That is the standard this project holds production joins to, and
`AGENTS.md` section 6 forbids a production join that depends solely on normalized names.

Fantasy Football Calculator publishes an internal `player_id` that maps to nothing outside
FFC. The id is stable, so the join only has to be made **once**; what this module does is
make that one-time proposal carefully enough that a human can review it, and then get out
of the way. After a row is accepted into the alias file, production capture resolves it by
exact id and never scores a name again — which is why :func:`link_source_rows` reports
`resolution_method` per row and why the alias file is the artifact, not the scorer.

The design constraints, all from `docs/RELEASE2_ROADMAP.md` 10.2:

* **Block on position, exactly.** A QB may never match an RB however similar the names. The
  blocking key is :class:`~ffdraft.contracts.enums.Position`, parsed by the same exact alias
  table the rest of the project uses, so a team-unit token like ``TMWR`` cannot become WR.
* **Do not block on team.** Teams are stale around trades and free agency. Team agreement is
  a tie-break and a diagnostic, never a gate.
* **Refuse on ambiguity rather than guess.** A tie, a thin margin, a name that two canonical
  players share — each is quarantined with a reason. This mirrors the resolver's poisoned
  index: the failure mode being avoided is a confident wrong answer, not a missing one.
* **Report the top-300 tail separately.** A 90% aggregate is not permission to lose a player
  the market drafts in the third round, so unresolved rows inside the source's own top 300
  are surfaced on their own.

Everything here is deterministic: candidate ordering breaks ties on canonical id, scores are
rounded before comparison, and the reports sort by a stable key. Two runs over the same input
produce byte-identical output.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, process

from ffdraft.contracts import CORE_POSITIONS, EntityKind, Position
from ffdraft.identity.names import normalize_name
from ffdraft.identity.registry import CanonicalRegistry

__all__ = [
    "LINKAGE_RULE",
    "linkage_key",
    "REASON_AMBIGUOUS_CANONICAL",
    "REASON_LOW_MARGIN",
    "REASON_LOW_SCORE",
    "REASON_NON_CORE_POSITION",
    "REASON_NO_CANDIDATE",
    "REASON_UNPARSEABLE_POSITION",
    "REASON_UNUSABLE_NAME",
    "AcceptedAlias",
    "Candidate",
    "LinkageReport",
    "LinkageRule",
    "QuarantineRow",
    "SourceRow",
    "link_source_rows",
]


# --------------------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------------------

#: Characters that are *elided* rather than spaced.
#:
#: :func:`ffdraft.identity.names.normalize_name` replaces all punctuation with a space,
#: which is right for the resolver's diagnostics and wrong here: it turns ``De'Andre`` into
#: ``de andre`` while a source spelling it ``DeAndre`` becomes ``deandre``, so two spellings
#: of one man stop being equal and have to be rescued by a similarity score. An apostrophe
#: inside a name carries no word boundary, and neither does the period in a middle initial.
_ELIDED = str.maketrans({"'": "", "\u2019": "", ".": ""})


def linkage_key(raw: str | None) -> str:
    """The comparison key linkage blocks and scores on.

    Built on :func:`~ffdraft.identity.names.normalize_name` rather than replacing it, so the
    two never drift apart on casing, accents or generational suffixes — the difference is
    exactly one rule, applied first: apostrophes and periods are removed instead of being
    turned into word boundaries. Hyphens keep becoming spaces, because a hyphen *is* a word
    boundary and ``Okonkwo-Bell`` and ``Okonkwo Bell`` are the same name written twice.

    Deterministic and total: any input, including ``None``, yields a string.
    """
    return normalize_name((raw or "").translate(_ELIDED))


# --------------------------------------------------------------------------------------
# The frozen rule
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinkageRule:
    """The thresholds an automatic acceptance must clear.

    Calibrated against the hand-checked gold fixture in
    ``tests/fixtures/identity/ffc_linkage_gold.json`` rather than tuned upward until live
    coverage passed. The roadmap is explicit about that ordering: *"Do not choose a
    permissive threshold merely to hit coverage."* The gold set contains the cases these
    numbers exist for — a suffix difference, an apostrophe, two same-position players whose
    names are one edit apart — and the values below are the loosest that still quarantine
    every pair the gold set marks as ambiguous.
    """

    version: str = "phase10_linkage_v1"
    #: A normalized-name equality match is accepted outright when it is collision-free.
    #: Nothing about it is fuzzy: two identical normalized strings at the same position.
    accept_exact: bool = True
    #: Minimum normalized Levenshtein similarity (0-100) for a fuzzy acceptance.
    min_score: float = 92.0
    #: The winner must beat the runner-up by at least this much. A 97 against a 96 is two
    #: plausible people, not one confident answer, however high the absolute score is.
    min_margin: float = 6.0
    #: Below this, a candidate is not even worth retaining as a review suggestion.
    candidate_floor: float = 60.0
    #: How many candidates to retain per row for the review artifact.
    keep_candidates: int = 2
    #: The build-continuation gate (roadmap 10.2).
    min_coverage: float = 0.90
    #: How deep "top 300" reaches when surfacing the unresolved tail separately.
    top_depth: int = 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "accept_exact": self.accept_exact,
            "min_score": self.min_score,
            "min_margin": self.min_margin,
            "candidate_floor": self.candidate_floor,
            "keep_candidates": self.keep_candidates,
            "min_coverage": self.min_coverage,
            "top_depth": self.top_depth,
        }


#: The production rule. Frozen: changing a threshold changes which players the board can
#: price, so it belongs in an ADR and a version bump, not in a caller's keyword argument.
LINKAGE_RULE = LinkageRule()


# --------------------------------------------------------------------------------------
# Reasons
# --------------------------------------------------------------------------------------

REASON_RESOLVED_EXACT = "resolved_exact_name_position"
REASON_RESOLVED_FUZZY = "resolved_high_confidence_fuzzy"
REASON_NON_CORE_POSITION = "excluded_non_core_position"
REASON_UNPARSEABLE_POSITION = "quarantined_unparseable_position"
REASON_UNUSABLE_NAME = "quarantined_unusable_name"
REASON_NO_CANDIDATE = "quarantined_no_candidate_at_position"
REASON_LOW_SCORE = "quarantined_below_min_score"
REASON_LOW_MARGIN = "quarantined_below_min_margin"
REASON_AMBIGUOUS_CANONICAL = "quarantined_ambiguous_canonical_name"


# --------------------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceRow:
    """One row of a source's market population, normalized for linkage."""

    external_player_id: str
    display_name: str
    position: str
    team: str | None = None
    #: The source's own ordering value (ADP). Used only to identify the top-N tail.
    order_key: float | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One canonical player proposed for a source row, with its score."""

    player_id: str
    display_name: str
    team: str | None
    score: float


@dataclass(frozen=True, slots=True)
class AcceptedAlias:
    """A source id mapped to a canonical player, with how it was decided."""

    source_id: str
    external_player_id: str
    player_id: str
    display_name: str
    canonical_name: str
    position: str
    score: float
    margin: float
    team_agrees: bool
    resolution_method: str
    rule_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "external_id": self.external_player_id,
            "player_id": self.player_id,
            "source_name": self.display_name,
            "canonical_name": self.canonical_name,
            "position": self.position,
            "score": round(self.score, 2),
            "margin": round(self.margin, 2),
            "team_agrees": self.team_agrees,
            "resolution_method": self.resolution_method,
            "rule_version": self.rule_version,
        }


@dataclass(frozen=True, slots=True)
class QuarantineRow:
    """A row that did not resolve, and every field a reviewer needs to decide.

    The column list is the roadmap's, verbatim, because a review artifact whose columns are
    chosen by the implementer is a review artifact nobody can diff against the specification.
    """

    source_id: str
    external_player_id: str
    display_name: str
    position: str
    team: str | None
    normalized_name: str
    candidate_1_player_id: str | None
    candidate_1_name: str | None
    candidate_1_score: float | None
    candidate_1_team: str | None
    candidate_2_player_id: str | None
    candidate_2_name: str | None
    candidate_2_score: float | None
    score_margin: float | None
    team_agrees: bool | None
    resolution_method: str
    reason: str
    review_status: str = "unreviewed"
    #: The source's own rank, when it has one. A reviewer triages by this, not by row order.
    rank_hint: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "ffc_player_id": self.external_player_id,
            "ffc_display_name": self.display_name,
            "ffc_position": self.position,
            "ffc_team": self.team,
            "normalized_ffc_name": self.normalized_name,
            "candidate_1_player_id": self.candidate_1_player_id,
            "candidate_1_name": self.candidate_1_name,
            "candidate_1_score": self.candidate_1_score,
            "candidate_1_team": self.candidate_1_team,
            "candidate_2_player_id": self.candidate_2_player_id,
            "candidate_2_name": self.candidate_2_name,
            "candidate_2_score": self.candidate_2_score,
            "score_margin": self.score_margin,
            "team_agrees": self.team_agrees,
            "resolution_method": self.resolution_method,
            "review_status": self.review_status,
            "reason": self.reason,
            "rank_hint": self.rank_hint,
        }


@dataclass
class LinkageReport:
    """What one linkage run decided, and the evidence for every decision."""

    source_id: str
    rule: LinkageRule
    accepted_rows: list[AcceptedAlias] = field(default_factory=list)
    quarantine: list[QuarantineRow] = field(default_factory=list)
    excluded: list[QuarantineRow] = field(default_factory=list)
    total_rows: int = 0

    @property
    def relevant(self) -> int:
        """Rows the coverage gate is measured over: core-position source rows."""
        return len(self.accepted_rows) + len(self.quarantine)

    @property
    def accepted(self) -> int:
        return len(self.accepted_rows)

    @property
    def quarantined(self) -> int:
        return len(self.quarantine)

    @property
    def coverage(self) -> float:
        return self.accepted / self.relevant if self.relevant else 0.0

    @property
    def passes_gate(self) -> bool:
        return self.coverage >= self.rule.min_coverage

    @property
    def top_unresolved(self) -> list[QuarantineRow]:
        """Quarantined rows inside the source's own top ``rule.top_depth`` by order key.

        Kept separate from the aggregate deliberately. A 92% coverage figure that hides
        three second-round picks is worse than an 88% one that does not, and the roadmap
        asks for exactly this split.
        """
        return [
            row
            for row in self.quarantine
            if row.rank_hint is not None and row.rank_hint <= self.rule.top_depth
        ]

    def alias_entries(self, *, reviewed_by: str, reviewed_at: str) -> list[dict[str, Any]]:
        """Accepted rows in the shape :mod:`ffdraft.identity.aliases` loads."""
        return [
            {
                "source_id": alias.source_id,
                "external_id": alias.external_player_id,
                "player_id": alias.player_id,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "note": (
                    f"{alias.resolution_method} under {alias.rule_version}: "
                    f"{alias.display_name} ({alias.position}) -> {alias.canonical_name}, "
                    f"score {alias.score:.1f}, margin {alias.margin:.1f}"
                ),
            }
            for alias in sorted(self.accepted_rows, key=_alias_sort_key)
        ]

    def summary(self) -> dict[str, Any]:
        by_reason: dict[str, int] = {}
        for row in self.quarantine:
            by_reason[row.reason] = by_reason.get(row.reason, 0) + 1
        by_method: dict[str, int] = {}
        for alias in self.accepted_rows:
            by_method[alias.resolution_method] = by_method.get(alias.resolution_method, 0) + 1
        return {
            "source_id": self.source_id,
            "rule": self.rule.to_dict(),
            "total_source_rows": self.total_rows,
            "excluded_non_core": len(self.excluded),
            "relevant_rows": self.relevant,
            "accepted": self.accepted,
            "quarantined": self.quarantined,
            "coverage": round(self.coverage, 6),
            "min_coverage": self.rule.min_coverage,
            "passes_gate": self.passes_gate,
            "accepted_by_method": dict(sorted(by_method.items())),
            "quarantined_by_reason": dict(sorted(by_reason.items())),
            "top_unresolved_depth": self.rule.top_depth,
            "top_unresolved": [row.to_dict() for row in self.top_unresolved],
        }


def _alias_sort_key(alias: AcceptedAlias) -> tuple[int, str]:
    """Numeric ids sort numerically; anything else sorts as text after them."""
    raw = alias.external_player_id
    return (int(raw), "") if raw.isdigit() else (2**62, raw)


# --------------------------------------------------------------------------------------
# Linkage
# --------------------------------------------------------------------------------------


def _canonical_pool(
    registry: CanonicalRegistry,
) -> dict[Position, tuple[tuple[str, str, str | None], ...]]:
    """Canonical players grouped by position: the blocking index.

    Only real players at core positions are poolable. A team unit or a kicker cannot be the
    answer to a QB/RB/WR/TE market row, and excluding them here is cheaper and safer than
    filtering the winner afterwards.
    """
    pool: dict[Position, list[tuple[str, str, str | None]]] = {}
    for player_id in sorted(registry.players):
        player = registry.players[player_id]
        if player.entity_kind is not EntityKind.PLAYER or player.position not in CORE_POSITIONS:
            continue
        pool.setdefault(player.position, []).append(
            (player_id, player.display_name, player.team),
        )
    return {position: tuple(rows) for position, rows in pool.items()}


def _rank_hints(rows: Sequence[SourceRow]) -> dict[str, int]:
    """1-based rank by the source's own order key, ties broken on external id.

    Rows without an order key get no hint rather than an invented one: a missing ADP is not
    rank 1, and a fabricated hint would put a player in or out of the top-300 review list
    for no reason.
    """
    ordered = sorted(
        (row for row in rows if row.order_key is not None),
        key=lambda row: (float(row.order_key or 0.0), row.external_player_id),
    )
    return {row.external_player_id: index + 1 for index, row in enumerate(ordered)}


def link_source_rows(
    rows: Iterable[Mapping[str, Any] | SourceRow],
    *,
    registry: CanonicalRegistry,
    source_id: str,
    rule: LinkageRule = LINKAGE_RULE,
) -> LinkageReport:
    """Propose canonical ids for one source's population.

    Returns a report, never a mutation: the caller decides whether to write an alias file,
    and a human decides whether to keep it. Nothing here resolves a production record on its
    own — an accepted proposal becomes a join only once it is in the reviewed alias file,
    which is the ADR-019 escape hatch this reuses rather than a new authority.
    """
    parsed = [row if isinstance(row, SourceRow) else _as_source_row(row) for row in rows]
    report = LinkageReport(source_id=source_id, rule=rule, total_rows=len(parsed))
    pool = _canonical_pool(registry)
    hints = _rank_hints(parsed)

    for row in sorted(parsed, key=lambda item: item.external_player_id):
        position = Position.parse(row.position)
        hint = hints.get(row.external_player_id)

        if position is None:
            # An unparseable token could be a team unit (`TMWR`, `Def`) or a typo. The two
            # need different handling and cannot be told apart here, so both quarantine:
            # a source row whose position we cannot read is a row we cannot block on.
            report.quarantine.append(
                _quarantined(row, source_id, REASON_UNPARSEABLE_POSITION, (), hint),
            )
            continue
        if position not in CORE_POSITIONS:
            report.excluded.append(
                _quarantined(row, source_id, REASON_NON_CORE_POSITION, (), hint),
            )
            continue

        normalized = linkage_key(row.display_name)
        if not normalized:
            report.quarantine.append(
                _quarantined(row, source_id, REASON_UNUSABLE_NAME, (), hint),
            )
            continue

        block = pool.get(position, ())
        if not block:
            report.quarantine.append(
                _quarantined(row, source_id, REASON_NO_CANDIDATE, (), hint),
            )
            continue

        candidates = _score_block(normalized, block, rule)
        decision, reason = _decide(normalized, candidates, block, rule)
        if decision is None:
            report.quarantine.append(_quarantined(row, source_id, reason, candidates, hint))
            continue

        best = candidates[0]
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        report.accepted_rows.append(
            AcceptedAlias(
                source_id=source_id,
                external_player_id=row.external_player_id,
                player_id=best.player_id,
                display_name=row.display_name,
                canonical_name=best.display_name,
                position=str(position),
                score=best.score,
                margin=round(best.score - runner_up, 4),
                team_agrees=_team_agrees(row.team, best.team),
                resolution_method=decision,
                rule_version=rule.version,
            ),
        )
    return report


def _score_block(
    normalized: str,
    block: Sequence[tuple[str, str, str | None]],
    rule: LinkageRule,
) -> tuple[Candidate, ...]:
    """Top candidates within one position block, deterministically ordered.

    ``fuzz.ratio`` on RapidFuzz is normalized indel similarity on 0-100 — the same family as
    normalized Levenshtein and, unlike a token-set or partial ratio, it does not treat
    "Michael Thomas" and "Thomas" as near-identical. That distinction is the whole point at
    a position where several real players share a surname.
    """
    choices = {index: linkage_key(name) for index, (_, name, _) in enumerate(block)}
    matches = process.extract(
        normalized,
        choices,
        scorer=fuzz.ratio,
        limit=max(rule.keep_candidates, 2) * 4,
        score_cutoff=rule.candidate_floor,
    )
    scored = [
        Candidate(
            player_id=block[index][0],
            display_name=block[index][1],
            team=block[index][2],
            score=round(float(score), 4),
        )
        for _, score, index in matches
    ]
    # RapidFuzz's ordering among equal scores follows iteration order. Sorting on
    # (-score, player_id) makes a tie resolve the same way on every machine and every run,
    # which is what lets `min_margin` mean something stable.
    scored.sort(key=lambda candidate: (-candidate.score, candidate.player_id))
    return tuple(scored[: max(rule.keep_candidates, 2)])


def _decide(
    normalized: str,
    candidates: Sequence[Candidate],
    block: Sequence[tuple[str, str, str | None]],
    rule: LinkageRule,
) -> tuple[str | None, str]:
    """Accept, or refuse with a reason. Never returns a guess."""
    if not candidates:
        return None, REASON_NO_CANDIDATE

    exact = [player_id for player_id, name, _ in block if linkage_key(name) == normalized]
    if len(exact) > 1:
        # Two canonical players normalize to the same name at the same position. Choosing
        # either would be the collapse the roadmap's tests exist to forbid.
        return None, REASON_AMBIGUOUS_CANONICAL
    if len(exact) == 1 and rule.accept_exact:
        if candidates[0].player_id != exact[0]:
            # The scorer and the exact index disagree, which should be impossible: an exact
            # normalized match scores 100. Refuse rather than reconcile.
            return None, REASON_AMBIGUOUS_CANONICAL
        return REASON_RESOLVED_EXACT, ""

    best = candidates[0]
    runner_up = candidates[1].score if len(candidates) > 1 else 0.0
    if best.score < rule.min_score:
        return None, REASON_LOW_SCORE
    if best.score - runner_up < rule.min_margin:
        return None, REASON_LOW_MARGIN
    return REASON_RESOLVED_FUZZY, ""


def _team_agrees(source_team: str | None, canonical_team: str | None) -> bool:
    """A diagnostic and a tie-break, never a gate (roadmap 10.2, rule 3)."""
    if not source_team or not canonical_team:
        return False
    return source_team.strip().upper() == canonical_team.strip().upper()


def _quarantined(
    row: SourceRow,
    source_id: str,
    reason: str,
    candidates: Sequence[Candidate],
    rank_hint: int | None,
) -> QuarantineRow:
    first = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    margin = (
        round(first.score - second.score, 4) if first is not None and second is not None else None
    )
    return QuarantineRow(
        source_id=source_id,
        external_player_id=row.external_player_id,
        display_name=row.display_name,
        position=row.position,
        team=row.team,
        normalized_name=linkage_key(row.display_name),
        candidate_1_player_id=first.player_id if first else None,
        candidate_1_name=first.display_name if first else None,
        candidate_1_score=first.score if first else None,
        candidate_1_team=first.team if first else None,
        candidate_2_player_id=second.player_id if second else None,
        candidate_2_name=second.display_name if second else None,
        candidate_2_score=second.score if second else None,
        score_margin=margin,
        team_agrees=_team_agrees(row.team, first.team) if first else None,
        resolution_method="none",
        reason=reason,
        rank_hint=rank_hint,
    )


def _as_source_row(raw: Mapping[str, Any]) -> SourceRow:
    order = raw.get("order_key")
    return SourceRow(
        external_player_id=str(raw["external_player_id"]).strip(),
        display_name=str(raw.get("display_name") or "").strip(),
        position=str(raw.get("position") or "").strip(),
        team=(str(raw["team"]).strip() or None) if raw.get("team") else None,
        order_key=float(order) if isinstance(order, int | float) else None,
    )
