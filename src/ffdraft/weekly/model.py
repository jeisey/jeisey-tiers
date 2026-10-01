"""``wc1_quantile_gbm_conformal_v1``: the weekly start/sit candidate, fitted and served.

One LightGBM quantile booster per ``(position, scoring preset, level)`` over the
``weekly_core_v1`` inputs, then two deterministic corrections, both declared in
:mod:`ffdraft.weekly.frozen` before any evidence:

1. **Monotone rearrangement.** Each row's seven quantiles are sorted, so a crossing can never
   reach the page. The raw crossing rate is measured first and reported, so the repair never
   hides the defect it repairs (the repository's rule since Phase 4).
2. **Split-conformal shift.** Quantile boosters on a noisy target are usually too narrow. The
   fit holds out its own last training season, fits on the rest, and measures for each level
   the shift that makes the held-out coverage exact; the final boosters are then refitted on
   every training season and the shift applied. Nothing from the season being scored is ever
   seen: in a development fold the calibration season is the one before the validation
   season.

**Why a driver breakdown is honest here.** LightGBM's TreeSHAP contributions of the *median*
booster sum exactly to its raw prediction, so "recent production +3.1, game environment +0.8,
opponent -0.4" is an additive account of the number printed beside it, not a story told
about it. The conformal shift is reported as its own line, because it is.

**The artifact is not a pickle** (AGENTS.md section 5): every booster is LightGBM's own text
format, gzipped with ``mtime=0`` and digested, and the metadata is JSON.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.preprocessing import design_matrix
from ffdraft.timeutil import isoformat_utc, utc_now
from ffdraft.weekly.dataset import TARGET_COLUMN
from ffdraft.weekly.frozen import (
    FEATURE_FAMILIES,
    WEEKLY_POSITIONS,
    WeeklySpec,
)

__all__ = [
    "WEEKLY_ARTIFACT_SCHEMA",
    "WeeklyArtifactMismatch",
    "WeeklyGroup",
    "WeeklyModel",
    "fit_weekly_model",
    "quantile_columns",
]

WEEKLY_ARTIFACT_SCHEMA = "weekly_model_artifact_v1"
_METADATA_FILE = "metadata.json"
_BOOSTER_DIR = "boosters"

Floats = NDArray[np.float64]


class WeeklyArtifactMismatch(RuntimeError):
    """A weekly artifact that does not match what the code expects to load or serve."""


def quantile_columns(levels: Sequence[float]) -> list[str]:
    return [f"q{round(level * 100):02d}" for level in levels]


def family_map(spec: Any) -> Mapping[str, tuple[str, ...]]:
    """The spec's feature families: ``weekly-startsit-v1``'s seven unless it declares its own.

    A later spec (``weekly-startsit-v2``) carries a ``families`` mapping; v1's frozen spec does
    not, and reading it this way keeps v1's configuration hash exactly what it was.
    """
    families: Mapping[str, tuple[str, ...]] | None = getattr(spec, "families", None)
    return families if families is not None else FEATURE_FAMILIES


@dataclass
class WeeklyGroup:
    """One position x scoring preset: a booster per level plus its conformal shifts."""

    position: str
    scoring_preset: str
    boosters: list[lgb.Booster]
    offsets: list[float]
    training_rows: int
    calibration_rows: int
    raw_crossing_rate: float
    calibration_coverage_before: list[float] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.position}-{self.scoring_preset}"


def _train(
    frame: pl.DataFrame,
    *,
    spec: Any,
    level: float,
    seed: int,
) -> lgb.Booster:
    parameters = {
        **dict(spec.parameters),
        "objective": "quantile",
        "alpha": level,
        "seed": seed,
        "bagging_seed": seed,
        "feature_fraction_seed": seed,
        "data_random_seed": seed,
    }
    dataset = lgb.Dataset(
        design_matrix(frame, spec.features),
        label=frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
        feature_name=list(spec.features),
        free_raw_data=True,
    )
    return lgb.train(parameters, dataset, num_boost_round=spec.num_boost_round)


def _group_seed(spec: Any, position: str, scoring: str, level: float, tag: str) -> int:
    digest = hashlib.sha256(f"{spec.seed}|{position}|{scoring}|{level}|{tag}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 2_000_000_000


def _raw(boosters: Sequence[lgb.Booster], matrix: Floats) -> Floats:
    if matrix.shape[0] == 0:
        return np.zeros((0, len(boosters)), dtype=np.float64)
    return np.column_stack([np.asarray(b.predict(matrix), dtype=np.float64) for b in boosters])


def fit_weekly_model(
    frame: pl.DataFrame,
    *,
    spec: Any = None,
    calibrate: bool = True,
    positions: Sequence[str] = WEEKLY_POSITIONS,
) -> WeeklyModel:
    """Fit every group on ``frame``'s seasons, calibrating on the last one of them.

    ``frame`` is the training window only — the caller has already removed the season being
    scored. With ``calibrate`` the last season in ``frame`` is held out once for the shift and
    then included in the final fit.
    """
    resolved = spec or WeeklySpec()
    seasons = sorted({int(value) for value in frame.get_column("season").unique()})
    if calibrate and len(seasons) < 2:
        raise ValueError("calibration needs at least two training seasons")
    calibration_season = seasons[-1] if calibrate else None
    groups: dict[str, WeeklyGroup] = {}
    for position in positions:
        for scoring in sorted(frame.get_column("scoring_preset").unique().to_list()):
            block = frame.filter(
                (pl.col("position") == position) & (pl.col("scoring_preset") == scoring),
            )
            if block.is_empty():
                continue
            offsets = [0.0] * len(resolved.levels)
            crossing = 0.0
            before: list[float] = []
            calibration_rows = 0
            if calibration_season is not None:
                inner = block.filter(pl.col("season") < calibration_season)
                held = block.filter(pl.col("season") == calibration_season)
                calibration_rows = held.height
                if not inner.is_empty() and not held.is_empty():
                    inner_boosters = [
                        _train(
                            inner,
                            spec=resolved,
                            level=level,
                            seed=_group_seed(resolved, position, scoring, level, "inner"),
                        )
                        for level in resolved.levels
                    ]
                    raw = _raw(inner_boosters, design_matrix(held, resolved.features))
                    crossing = float(np.mean(np.any(np.diff(raw, axis=1) < 0, axis=1)))
                    ordered = np.sort(raw, axis=1)
                    actual = held.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
                    for index, level in enumerate(resolved.levels):
                        residual = actual - ordered[:, index]
                        before.append(float(np.mean(actual <= ordered[:, index])))
                        offsets[index] = float(np.quantile(residual, level, method="linear"))
            boosters = [
                _train(
                    block,
                    spec=resolved,
                    level=level,
                    seed=_group_seed(resolved, position, scoring, level, "final"),
                )
                for level in resolved.levels
            ]
            group = WeeklyGroup(
                position=position,
                scoring_preset=str(scoring),
                boosters=boosters,
                offsets=offsets,
                training_rows=block.height,
                calibration_rows=calibration_rows,
                raw_crossing_rate=crossing,
                calibration_coverage_before=before,
            )
            groups[group.key] = group
    return WeeklyModel(
        spec=resolved,
        groups=groups,
        training_seasons=tuple(seasons),
        calibration_season=calibration_season,
    )


@dataclass
class WeeklyModel:
    #: ``WeeklySpec`` (v1) or ``WeeklySpecV2``: anything with the same fields and digests.
    spec: Any
    groups: dict[str, WeeklyGroup]
    training_seasons: tuple[int, ...]
    calibration_season: int | None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def levels(self) -> tuple[float, ...]:
        return tuple(self.spec.levels)

    def predict(self, frame: pl.DataFrame) -> Floats:
        """``(rows, levels)`` calibrated, monotone quantiles, row order preserved.

        A row whose group was never fitted gets NaN, which callers must treat as "no
        projection" rather than as a number.
        """
        result = np.full((frame.height, len(self.levels)), np.nan, dtype=np.float64)
        if frame.is_empty():
            return result
        indexed = frame.with_row_index("_row")
        for group in self.groups.values():
            block = indexed.filter(
                (pl.col("position") == group.position)
                & (pl.col("scoring_preset") == group.scoring_preset),
            )
            if block.is_empty():
                continue
            raw = _raw(group.boosters, design_matrix(block, self.spec.features))
            shifted = np.sort(raw, axis=1) + np.asarray(group.offsets, dtype=np.float64)
            rows = block.get_column("_row").to_numpy()
            result[rows] = np.sort(shifted, axis=1)
        return result

    def drivers(self, frame: pl.DataFrame) -> list[dict[str, Any] | None]:
        """Grouped TreeSHAP of the median booster, per row.

        ``baseline`` is the booster's expected value, ``families`` the summed contributions
        per feature family, ``calibration`` the median's conformal shift. Their sum is the
        median before the monotone repair; the repair can only move it when quantiles crossed,
        and the difference is reported as ``rearrangement`` so the account still closes.
        """
        output: list[dict[str, Any] | None] = [None] * frame.height
        if frame.is_empty():
            return output
        median_index = self.levels.index(0.5)
        predictions = self.predict(frame)
        indexed = frame.with_row_index("_row")
        mapping = family_map(self.spec)
        families = list(mapping)
        owner = {name: str(family) for family, names in mapping.items() for name in names}
        family_of = [owner[name] for name in self.spec.features]
        for group in self.groups.values():
            block = indexed.filter(
                (pl.col("position") == group.position)
                & (pl.col("scoring_preset") == group.scoring_preset),
            )
            if block.is_empty():
                continue
            matrix = design_matrix(block, self.spec.features)
            contributions = np.asarray(
                group.boosters[median_index].predict(matrix, pred_contrib=True),
                dtype=np.float64,
            )
            rows = block.get_column("_row").to_numpy()
            for local, row in enumerate(rows):
                contribution = contributions[local]
                by_family = dict.fromkeys(families, 0.0)
                for feature_index, family in enumerate(family_of):
                    by_family[family] += float(contribution[feature_index])
                baseline = float(contribution[-1])
                calibration = float(group.offsets[median_index])
                account = baseline + sum(by_family.values()) + calibration
                median = float(predictions[row, median_index])
                output[int(row)] = {
                    "baseline": baseline,
                    "families": by_family,
                    "calibration": calibration,
                    "rearrangement": median - account,
                }
        return output

    # ------------------------------------------------------------------ persistence

    def save(self, directory: Path, *, extra: Mapping[str, Any] | None = None) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        boosters_dir = directory / _BOOSTER_DIR
        boosters_dir.mkdir(exist_ok=True)
        written: list[Path] = []
        groups_meta: list[dict[str, Any]] = []
        for key in sorted(self.groups):
            group = self.groups[key]
            files: list[dict[str, Any]] = []
            for level, booster in zip(self.levels, group.boosters, strict=True):
                name = f"{key}-q{round(level * 100):02d}.txt.gz"
                text = booster.model_to_string().encode("utf-8")
                path = boosters_dir / name
                with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
                    gz.write(text)
                written.append(path)
                files.append(
                    {"level": level, "file": f"{_BOOSTER_DIR}/{name}", "sha256": _digest(text)},
                )
            groups_meta.append(
                {
                    "position": group.position,
                    "scoring_preset": group.scoring_preset,
                    "offsets": group.offsets,
                    "training_rows": group.training_rows,
                    "calibration_rows": group.calibration_rows,
                    "raw_crossing_rate": group.raw_crossing_rate,
                    "calibration_coverage_before": group.calibration_coverage_before,
                    "boosters": files,
                },
            )
        metadata = {
            "artifact_schema": WEEKLY_ARTIFACT_SCHEMA,
            "spec": self.spec.to_dict(),
            "configuration_hash": self.spec.configuration_hash(),
            "feature_set_hash": self.spec.to_dict()["feature_set_hash"],
            "training_seasons": list(self.training_seasons),
            "calibration_season": self.calibration_season,
            "fitted_at_utc": isoformat_utc(utc_now()),
            "groups": groups_meta,
            **dict(extra or {}),
        }
        path = directory / _METADATA_FILE
        path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
        self.metadata = metadata
        return written

    @classmethod
    def load(cls, directory: Path, *, spec: Any = None) -> WeeklyModel:
        """Load and verify an artifact against ``spec`` (v1's frozen spec unless given)."""
        metadata = json.loads((directory / _METADATA_FILE).read_text(encoding="utf-8"))
        if metadata.get("artifact_schema") != WEEKLY_ARTIFACT_SCHEMA:
            raise WeeklyArtifactMismatch(
                f"{directory} is {metadata.get('artifact_schema')!r}, expected "
                f"{WEEKLY_ARTIFACT_SCHEMA!r}",
            )
        spec = spec if spec is not None else WeeklySpec()
        if metadata.get("configuration_hash") != spec.configuration_hash():
            raise WeeklyArtifactMismatch(
                "the weekly artifact was fitted under a different specification "
                f"({metadata.get('configuration_hash')} != {spec.configuration_hash()}); "
                "refusing to serve a model this code did not declare",
            )
        groups: dict[str, WeeklyGroup] = {}
        for entry in metadata["groups"]:
            boosters: list[lgb.Booster] = []
            for item in entry["boosters"]:
                with gzip.open(directory / item["file"], "rb") as handle:
                    payload = handle.read()
                if _digest(payload) != item["sha256"]:
                    raise WeeklyArtifactMismatch(
                        f"{item['file']} does not match its recorded digest; the artifact has "
                        "been altered",
                    )
                boosters.append(lgb.Booster(model_str=payload.decode("utf-8")))
            group = WeeklyGroup(
                position=str(entry["position"]),
                scoring_preset=str(entry["scoring_preset"]),
                boosters=boosters,
                offsets=[float(value) for value in entry["offsets"]],
                training_rows=int(entry["training_rows"]),
                calibration_rows=int(entry["calibration_rows"]),
                raw_crossing_rate=float(entry["raw_crossing_rate"]),
                calibration_coverage_before=[
                    float(value) for value in entry.get("calibration_coverage_before", [])
                ],
            )
            groups[group.key] = group
        model = cls(
            spec=spec,
            groups=groups,
            training_seasons=tuple(int(value) for value in metadata["training_seasons"]),
            calibration_season=metadata.get("calibration_season"),
            metadata=metadata,
        )
        return model


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
