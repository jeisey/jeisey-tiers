"""The final holdout, and the seal that keeps it shut.

2025 is the sealed final holdout for the 2026 launch model. The season is chosen, and the
diagnostic slices that will be reported against it are declared, **before** any candidate
is compared, so no result can motivate the definition after the fact.

Why 2025:

* it is the most recent fully labelled season;
* it is the only historical season carrying true timestamped preseason depth observations
  (ADR-015/ADR-018), so its information environment is the closest available analogue of
  what 2026 inference will see;
* for the same reason it is a deliberate domain-shift test: its eligible universe is built
  partly from a mechanism no earlier season has.

The seal is structural rather than conventional. Ordinary development commands never load a
sealed season at all: :func:`assert_seasons_sealed` refuses, and the dataset loader drops
the rows before a model can reach them. Unsealing requires constructing a
:class:`FinalEvalAuthorization` with the exact confirmation token, which the CLI accepts
only from an explicit ``--final-eval --confirm-final-eval <token>`` pair.

Phase 3 must not unseal it. Phase 4 may, once the candidate family, the training window and
the feature set are frozen.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import polars as pl

__all__ = [
    "FINAL_EVAL_CONFIRMATION_TOKEN",
    "FINAL_HOLDOUT_SEASON",
    "FinalEvalAuthorization",
    "HoldoutSealError",
    "HoldoutSliceKind",
    "PREDECLARED_HOLDOUT_SLICES",
    "SEALED_SEASONS",
    "HoldoutSlice",
    "SliceMask",
    "assert_seasons_sealed",
    "final_holdout_policy",
    "is_sealed",
]

#: The sealed season. Everything from here on is out of bounds for development work.
FINAL_HOLDOUT_SEASON = 2025

#: Anything at or after the holdout season is sealed, so a later season added to the dataset
#: inherits the seal instead of quietly becoming a development fold.
SEALED_SEASONS = "season >= 2025"

#: The literal string a caller must produce to unseal. It is deliberately unguessable by
#: accident and deliberately absent from every default.
FINAL_EVAL_CONFIRMATION_TOKEN = "RELEASE-FINAL-HOLDOUT-2025"


class HoldoutSealError(RuntimeError):
    """Raised when sealed-season data is requested without an explicit authorization."""


@dataclass(frozen=True, slots=True)
class FinalEvalAuthorization:
    """Proof that a human deliberately unsealed the final holdout.

    Constructing one is the only way to read a sealed season. The confirmation token is
    checked here rather than at the call site so that every path - CLI, script, notebook -
    goes through the same gate.
    """

    confirmation: str
    reason: str

    def __post_init__(self) -> None:
        if self.confirmation != FINAL_EVAL_CONFIRMATION_TOKEN:
            raise HoldoutSealError(
                "final-holdout evaluation requires the exact confirmation token "
                f"{FINAL_EVAL_CONFIRMATION_TOKEN!r}; refusing to unseal season "
                f"{FINAL_HOLDOUT_SEASON}",
            )
        if not self.reason.strip():
            raise HoldoutSealError(
                "final-holdout evaluation requires a recorded reason; the report has to say "
                "why the holdout was consumed",
            )

    def to_dict(self) -> dict[str, Any]:
        return {"authorized": True, "reason": self.reason}


def is_sealed(season: int) -> bool:
    return season >= FINAL_HOLDOUT_SEASON


def assert_seasons_sealed(
    seasons: Iterable[int],
    *,
    authorization: FinalEvalAuthorization | None = None,
    context: str = "",
) -> None:
    """Refuse any sealed season unless an authorization was supplied.

    ``context`` names the caller so a failure says which stage tried to reach 2025.
    """
    if authorization is not None:
        return
    offending = sorted({season for season in seasons if is_sealed(season)})
    if offending:
        where = f" in {context}" if context else ""
        raise HoldoutSealError(
            f"season(s) {offending} are sealed{where}: {SEALED_SEASONS} is the final holdout "
            "and may not be used for development training, tuning or evaluation. Pass an "
            "explicit FinalEvalAuthorization to run the final evaluation.",
        )


class HoldoutSliceKind(StrEnum):
    """What a predeclared final-holdout slice is for."""

    #: The headline result. Nothing may replace it.
    PRIMARY = "primary"
    #: Diagnostic context that explains a primary result without ever standing in for it.
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True, slots=True)
class HoldoutSlice:
    """One predeclared way the final-holdout result will be sliced.

    ``predicate`` is a Polars expression string evaluated against the joined modelling
    frame. It is stored as text so the declaration is legible in the report and identical
    between the freeze and the eventual Phase-4 evaluation.
    """

    slice_id: str
    kind: HoldoutSliceKind
    description: str
    predicate: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "kind": str(self.kind),
            "description": self.description,
            "predicate": self.predicate,
            "rationale": self.rationale,
        }


#: Declared 2026-08-19, before any candidate comparison, without inspecting 2025 outcomes.
#: Every predicate reads feature-side metadata only - eligibility basis, depth context,
#: rookie status, prior-production availability, position, scoring preset - so none of them
#: could have been chosen to flatter a result.
PREDECLARED_HOLDOUT_SLICES: tuple[HoldoutSlice, ...] = (
    HoldoutSlice(
        slice_id="full_universe",
        kind=HoldoutSliceKind.PRIMARY,
        description="Every eligible 2025 player-season, all positions and scoring presets",
        predicate="true",
        rationale=(
            "The production-realistic result. 2025's universe is what a 2026 draft board "
            "actually has to rank, zero-production players included, so this is the primary "
            "final-holdout metric and nothing may substitute for it."
        ),
    ),
    HoldoutSlice(
        slice_id="era_stable_universe",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description=(
            "2025 rows whose eligibility is supported by the prior-season roster or the "
            "target-season draft class, i.e. discoverable under the pre-snapshot mechanism"
        ),
        predicate=(
            "eligibility_basis.str.contains('prior_season_roster') "
            "or eligibility_basis.str.contains('draft_class')"
        ),
        rationale=(
            "2025 is the first season whose universe can also be established by a "
            "pre-anchor depth snapshot (ADR-022). Restricting to the earlier-era mechanisms "
            "separates 'the model degraded' from 'the universe widened'. Diagnostic only."
        ),
    ),
    HoldoutSlice(
        slice_id="rookie",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="Rows flagged as rookies by prior-existence evidence",
        predicate="rookie_flag",
        rationale="Rookies are the lowest-information population; their error is expected "
        "to be larger and must not be averaged away.",
    ),
    HoldoutSlice(
        slice_id="veteran",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="Rows not flagged as rookies",
        predicate="not rookie_flag",
        rationale="The complement of the rookie slice, reported alongside it so the split "
        "is exhaustive.",
    ),
    HoldoutSlice(
        slice_id="depth_context_state",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="Grouped by ADR-018 depth context: observed, prior-season role, none",
        predicate="group_by(depth_context_state)",
        rationale=(
            "2025 is the only season where all three depth states occur. The Phase-3 core "
            "feature set excludes the snapshot-only depth columns, so this slice measures "
            "whether their absence costs anything on the rows that have them."
        ),
    ),
    HoldoutSlice(
        slice_id="position",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="Grouped by QB/RB/WR/TE",
        predicate="group_by(position)",
        rationale="A positional collapse is invisible in a pooled number; the promotion "
        "gate is defined per position for the same reason.",
    ),
    HoldoutSlice(
        slice_id="scoring_preset",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="Grouped by STD/HALF/PPR",
        predicate="group_by(scoring_preset)",
        rationale="Each preset is a separate model; each gets a separate result.",
    ),
    HoldoutSlice(
        slice_id="information_rich",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description=(
            "Rows with a substantial prior-season workload: prior stats exist and the "
            "player appeared in at least eight games of the previous season"
        ),
        predicate="has_prior_season_stats and prev1_games >= 8",
        rationale=(
            "'Information-rich' is defined from feature availability alone, fixed here "
            "before any outcome is seen. Eight games is half a season under either horizon."
        ),
    ),
    HoldoutSlice(
        slice_id="low_information",
        kind=HoldoutSliceKind.DIAGNOSTIC,
        description="The complement of information_rich",
        predicate="not (has_prior_season_stats and prev1_games >= 8)",
        rationale="Reported with its complement so the split is exhaustive and neither half "
        "can be quietly dropped.",
    ),
)


@dataclass(frozen=True, slots=True)
class SliceMask:
    """One concrete partition of a frame, derived from a predeclared slice."""

    slice_id: str
    kind: HoldoutSliceKind
    label: str
    mask: pl.Expr


def _grouped(
    frame: pl.DataFrame, slice_id: str, column: str, kind: HoldoutSliceKind
) -> list[SliceMask]:
    values = sorted({str(value) for value in frame.get_column(column).to_list()})
    return [SliceMask(slice_id, kind, value, pl.col(column) == value) for value in values]


def slice_masks(frame: pl.DataFrame) -> list[SliceMask]:
    """Turn the predeclared slice declarations into concrete masks over a frame.

    The declarations carry their predicate as text so the report is legible; the executable
    form lives here, keyed by slice id, so nothing ever evaluates a string. Adding a slice
    means adding both, which is the point: a slice that cannot be written as a typed
    expression over feature-side metadata is not a slice this project will report.
    """
    masks: list[SliceMask] = []
    for declaration in PREDECLARED_HOLDOUT_SLICES:
        slice_id, kind = declaration.slice_id, declaration.kind
        if slice_id == "full_universe":
            masks.append(SliceMask(slice_id, kind, "all", pl.lit(True)))
        elif slice_id == "era_stable_universe":
            masks.append(
                SliceMask(
                    slice_id,
                    kind,
                    "prior_roster_or_draft_class",
                    pl.col("eligibility_basis").str.contains("prior_season_roster")
                    | pl.col("eligibility_basis").str.contains("draft_class"),
                ),
            )
        elif slice_id == "rookie":
            masks.append(SliceMask(slice_id, kind, "rookie", pl.col("rookie_flag")))
        elif slice_id == "veteran":
            masks.append(SliceMask(slice_id, kind, "veteran", ~pl.col("rookie_flag")))
        elif slice_id == "depth_context_state":
            masks.extend(_grouped(frame, slice_id, "depth_context_state", kind))
        elif slice_id == "position":
            masks.extend(_grouped(frame, slice_id, "position", kind))
        elif slice_id == "scoring_preset":
            masks.extend(_grouped(frame, slice_id, "scoring_preset", kind))
        elif slice_id in {"information_rich", "low_information"}:
            rich = pl.col("has_prior_season_stats") & (pl.col("prev1_games").fill_null(0) >= 8)
            masks.append(
                SliceMask(
                    slice_id, kind, slice_id, rich if slice_id == "information_rich" else ~rich
                ),
            )
        else:  # pragma: no cover - a declaration without an implementation is a bug
            raise KeyError(f"predeclared slice {slice_id!r} has no executable mask")
    return masks


def final_holdout_policy(*, status: str = "UNTOUCHED / NOT EVALUATED") -> dict[str, Any]:
    """The machine-readable holdout declaration written into every experiment report."""
    return {
        "final_holdout_season": FINAL_HOLDOUT_SEASON,
        "sealed_rule": SEALED_SEASONS,
        "status": status,
        "unseal_requires": [
            "--final-eval",
            f"--confirm-final-eval {FINAL_EVAL_CONFIRMATION_TOKEN}",
        ],
        "primary_result": "full_universe",
        "slices": [slice_.to_dict() for slice_ in PREDECLARED_HOLDOUT_SLICES],
        "declared_before_candidate_comparison": True,
    }


def slice_ids(kind: HoldoutSliceKind | None = None) -> Sequence[str]:
    return tuple(
        slice_.slice_id
        for slice_ in PREDECLARED_HOLDOUT_SLICES
        if kind is None or slice_.kind is kind
    )
