"""The Phase-3 modelling frame: features joined to labels, with the holdout already gone.

One row per ``(season, player_id, scoring_preset)``, which is the grain every Phase-3 model
is fitted and scored at. Models are position-specific and scoring-specific, so the frame
carries both keys and the experiment slices on them.

The target is the season fantasy-point total over the documented horizon
(`docs/MODELING.md` section 3), i.e. Candidate A's direct-total formulation. Nothing here
selects on the outcome: the evaluation universe is the full leakage-safe eligible universe
Phase 2 built, zero-production players included, because filtering to eventual contributors
would reintroduce exactly the survivorship bias the eligibility rules were written to avoid.

The final holdout is removed at load time rather than at use time. A development run
physically does not have the rows, so no later mistake can reach them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from ffdraft.config import ScoringPreset
from ffdraft.contracts import QualityCheck
from ffdraft.features.dictionary import ALL_CORE_POSITIONS
from ffdraft.modeling.features import FeatureSelection, core_feature_selection
from ffdraft.modeling.folds import Fold
from ffdraft.modeling.holdout import (
    FinalEvalAuthorization,
    assert_seasons_sealed,
    is_sealed,
)

__all__ = [
    "CONTEXT_COLUMNS",
    "KEY_COLUMNS",
    "ModelingDataset",
    "TARGET_COLUMN",
    "build_modeling_frame",
    "group_key",
    "load_modeling_dataset",
]

#: What the models predict: the season fantasy-point total over the documented horizon.
TARGET_COLUMN = "target_points"

KEY_COLUMNS: tuple[str, ...] = ("season", "player_id", "position", "scoring_preset")

#: Carried for slicing, diagnostics and the transparent baseline. None of these is a model
#: input; the model input list is :class:`FeatureSelection`.
CONTEXT_COLUMNS: tuple[str, ...] = (
    "display_name",
    "eligibility_basis",
    "universe_era",
    "depth_context_state",
    "actual_games_played",
    "actual_positional_rank",
    "prior_ppg_matched",
)

_FEATURES_FILE = "features.parquet"
_LABELS_FILE = "labels_fantasy.parquet"
_MANIFEST_FILE = "build_manifest.json"


@dataclass(frozen=True)
class ModelingDataset:
    """The joined modelling frame plus everything the report needs to describe it."""

    frame: pl.DataFrame
    selection: FeatureSelection
    seasons: tuple[int, ...]
    withheld_seasons: tuple[int, ...]
    withheld_rows: int
    #: The same rows carrying the *excluded* columns as well, so the era-stability audit can
    #: re-measure the evidence behind each exclusion. Models never see it: they read
    #: ``frame`` and ``selection.included``.
    audit_frame: pl.DataFrame = field(default_factory=pl.DataFrame)
    dataset_manifest: dict[str, Any] = field(default_factory=dict)
    checks: tuple[QualityCheck, ...] = ()

    @property
    def sealed(self) -> bool:
        """True when no sealed season is present, which is the ordinary development state."""
        return not any(is_sealed(season) for season in self.seasons)

    def fold_frames(self, fold: Fold) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Training and validation rows for one fold, by season alone."""
        train = self.frame.filter(pl.col("season").is_in(list(fold.train_seasons)))
        validate = self.frame.filter(pl.col("season") == fold.validation_season)
        return train, validate

    def describe(self) -> dict[str, Any]:
        counts = (
            self.frame.group_by("season", "position")
            .agg(pl.len().alias("rows"))
            .sort("season", "position")
        )
        return {
            "grain": "season x player_id x scoring_preset",
            "target": TARGET_COLUMN,
            "rows": self.frame.height,
            "seasons": list(self.seasons),
            "withheld_seasons": list(self.withheld_seasons),
            "withheld_rows": self.withheld_rows,
            "rows_by_season_position": counts.to_dicts(),
            "dataset_manifest": self.dataset_manifest,
        }


def group_key(position: str, scoring_preset: str) -> str:
    return f"{position}|{scoring_preset}"


def _prior_ppg_matched() -> pl.Expr:
    """Prior-season points per game in the row's own scoring flavour.

    Phase 2 carries STD and PPR explicitly and records that half-PPR is exactly their mean,
    so this is a restatement of existing leakage-safe columns rather than a new feature. It
    exists for the transparent B0 baseline, which has to compare like with like: a PPR
    baseline built on standard-scoring production would be a different, worse baseline.
    """
    std = pl.col("prev1_fantasy_ppg_std")
    ppr = pl.col("prev1_fantasy_ppg_ppr")
    return (
        pl.when(pl.col("scoring_preset") == str(ScoringPreset.STD))
        .then(std)
        .when(pl.col("scoring_preset") == str(ScoringPreset.PPR))
        .then(ppr)
        .otherwise((std + ppr) / 2.0)
        .alias("prior_ppg_matched")
    )


def build_modeling_frame(
    features: pl.DataFrame,
    labels: pl.DataFrame,
    *,
    selection: FeatureSelection | None = None,
    authorization: FinalEvalAuthorization | None = None,
    scoring_presets: Sequence[str] | None = None,
    positions: Sequence[str] = ALL_CORE_POSITIONS,
) -> ModelingDataset:
    """Join features to labels, drop the sealed seasons and keep only declared columns."""
    chosen = selection or core_feature_selection()

    present_seasons = sorted(set(features["season"].to_list()))
    withheld = tuple(season for season in present_seasons if is_sealed(season))
    withheld_rows = 0
    if authorization is None and withheld:
        sealed = list(withheld)
        withheld_rows = int(labels.filter(pl.col("season").is_in(sealed)).height)
        features = features.filter(~pl.col("season").is_in(sealed))
        labels = labels.filter(~pl.col("season").is_in(sealed))

    label_columns = [
        "season",
        "player_id",
        "scoring_preset",
        "actual_fantasy_points",
        "actual_games_played",
        "actual_positional_rank",
    ]
    joined = (
        features.join(labels.select(label_columns), on=["season", "player_id"], how="inner")
        .filter(pl.col("position").is_in(list(positions)))
        .rename({"actual_fantasy_points": TARGET_COLUMN})
        .with_columns(_prior_ppg_matched())
    )
    if scoring_presets is not None:
        joined = joined.filter(pl.col("scoring_preset").is_in(list(scoring_presets)))

    keep = [
        *KEY_COLUMNS,
        TARGET_COLUMN,
        *(name for name in CONTEXT_COLUMNS if name in joined.columns),
        *(name for name in chosen.included if name not in KEY_COLUMNS),
        # Slice keys the predeclared holdout diagnostics and the fold report read. They are
        # model inputs as well, but the frame carries each column once.
        *(
            name
            for name in ("rookie_flag", "has_prior_season_stats", "prev1_games")
            if name not in chosen.included and name in joined.columns
        ),
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for name in keep:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    sort_keys = ("season", "scoring_preset", "position", "player_id")
    frame = joined.select(ordered).sort(*sort_keys)
    audit_columns = [
        name
        for name in dict.fromkeys(
            ["season", *chosen.included, *(item.name for item in chosen.excluded)],
        )
        if name in joined.columns
    ]
    audit_frame = joined.select(audit_columns).sort("season")

    seasons = tuple(sorted(set(frame["season"].to_list())))
    if authorization is None:
        assert_seasons_sealed(seasons, context="modelling frame")

    checks = [
        QualityCheck.ok(
            "phase3.final_holdout_withheld",
            stage="phase3_dataset",
            message=(
                "sealed seasons were removed before any model saw the frame"
                if authorization is None
                else "FINAL HOLDOUT UNSEALED by explicit authorization"
            ),
            observed=f"withheld={list(withheld)}; retained={list(seasons)}",
        ),
    ]
    return ModelingDataset(
        frame=frame,
        selection=chosen,
        audit_frame=audit_frame,
        seasons=seasons,
        withheld_seasons=withheld if authorization is None else (),
        withheld_rows=withheld_rows,
        checks=tuple(checks),
    )


def load_modeling_dataset(
    directory: Path,
    *,
    selection: FeatureSelection | None = None,
    authorization: FinalEvalAuthorization | None = None,
    scoring_presets: Sequence[str] | None = None,
) -> ModelingDataset:
    """Read a Phase-2 dataset from disk and build the Phase-3 modelling frame."""
    import json

    features_path = directory / _FEATURES_FILE
    labels_path = directory / _LABELS_FILE
    for path in (features_path, labels_path):
        if not path.is_file():
            raise FileNotFoundError(
                f"{path} not found; run `ffdraft build-historical --last-season 2025` first",
            )
    features = pl.read_parquet(features_path)
    labels = pl.read_parquet(labels_path)

    dataset = build_modeling_frame(
        features,
        labels,
        selection=selection,
        authorization=authorization,
        scoring_presets=scoring_presets,
    )
    manifest_path = directory / _MANIFEST_FILE
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return ModelingDataset(
        frame=dataset.frame,
        selection=dataset.selection,
        audit_frame=dataset.audit_frame,
        seasons=dataset.seasons,
        withheld_seasons=dataset.withheld_seasons,
        withheld_rows=dataset.withheld_rows,
        dataset_manifest=manifest,
        checks=dataset.checks,
    )
