"""The production intrinsic model: training it once, storing it, and serving it.

Fold evaluation and production training are different activities and this module is the
second one. :mod:`ffdraft.modeling.estimators` deliberately exposes only ``fit_predict``, so
that no fitted object can outlive a fold and fold isolation is structural rather than
remembered. Production needs the opposite: a fitted object that outlives everything, is
written to disk, and is loaded months later by a build that has no training data at all.

So this module reuses the *low-level* pieces the candidates use - the same LightGBM
configuration, the same calibration, the same copula - and adds what only production needs:

**A serialization format that is not a pickle.** Every booster is stored as LightGBM's own
text representation and every other parameter as JSON. Loading a model therefore reads
numbers and a documented text format, never executes a serialized object graph
(`AGENTS.md` section 5). The artifact is reviewable in a diff.

**A feature-schema contract that fails closed.** The artifact records the Phase-2 feature
schema hash *and* the Phase-3 core feature-set hash, and inference refuses to run against a
frame whose schema disagrees. A model silently consuming a renamed or reordered feature set
is the failure mode this exists to make impossible.

**Everything needed to reproduce the fit**, recorded beside the weights: training seasons,
exact parameters, quantile levels, calibration version, seed, library versions, code SHA and
the historical dataset's content hashes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl
from numpy.typing import NDArray

from ffdraft.modeling.calibration import (
    HorizonNormalizedTarget,
    IdentityTarget,
    MonotoneOnly,
    QuantileShift,
    ResidualShiftCalibration,
    monotone_projection,
    season_array,
)
from ffdraft.modeling.candidates import (
    MAX_DEPENDENCE,
    MINIMUM_DEPENDENCE_ROWS,
    Q1_NUM_BOOST_ROUND,
    Q1_PARAMETERS,
    fit_quantile_boosters,
    horizon_weeks_for,
    predict_quantiles,
    usable_columns,
)
from ffdraft.modeling.dataset import TARGET_COLUMN
from ffdraft.modeling.features import core_feature_selection
from ffdraft.modeling.gaussian import norm_cdf, norm_ppf
from ffdraft.modeling.metrics import QUANTILE_LEVELS
from ffdraft.modeling.preprocessing import design_matrix, inner_chronological_split
from ffdraft.scoring.horizon import fantasy_horizon
from ffdraft.simulation.sampler import DomainBounds, QuantileFunction, normal_draws
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ARTIFACT_SCHEMA",
    "METADATA_FILE",
    "FeatureSchemaMismatch",
    "GroupArtifact",
    "ProductionModel",
    "ProductionSpec",
    "train_production_model",
]

Floats = NDArray[np.float64]

#: The on-disk contract. Bump when the layout changes in a way an older loader cannot read.
ARTIFACT_SCHEMA = "intrinsic_model_artifact_v1"

METADATA_FILE = "metadata.json"
BOOSTER_DIR = "boosters"

#: The two architectures Phase 4 compared. The promoted one is recorded in the artifact.
ARCHITECTURE_DIRECT = "direct_total_quantiles"
ARCHITECTURE_HURDLE = "availability_x_performance"


class FeatureSchemaMismatch(RuntimeError):
    """Raised when a model is asked to predict from a frame it was not built for."""


@dataclass(frozen=True)
class ProductionSpec:
    """The frozen architecture description a production model is trained from."""

    model_version: str
    architecture: str
    calibration_strategy_id: str
    target_scale_id: str
    seed: int
    levels: tuple[float, ...] = QUANTILE_LEVELS
    parameters: Mapping[str, Any] = field(default_factory=lambda: dict(Q1_PARAMETERS))
    num_boost_round: int = Q1_NUM_BOOST_ROUND
    composition_draws: int = 2000

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "architecture": self.architecture,
            "calibration_strategy_id": self.calibration_strategy_id,
            "target_scale_id": self.target_scale_id,
            "seed": self.seed,
            "levels": list(self.levels),
            "parameters": dict(self.parameters),
            "num_boost_round": self.num_boost_round,
            "composition_draws": self.composition_draws,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ProductionSpec:
        return cls(
            model_version=str(payload["model_version"]),
            architecture=str(payload["architecture"]),
            calibration_strategy_id=str(payload["calibration_strategy_id"]),
            target_scale_id=str(payload["target_scale_id"]),
            seed=int(payload["seed"]),
            levels=tuple(float(value) for value in payload["levels"]),
            parameters=dict(payload["parameters"]),
            num_boost_round=int(payload["num_boost_round"]),
            composition_draws=int(payload["composition_draws"]),
        )

    @property
    def is_hurdle(self) -> bool:
        return self.architecture == ARCHITECTURE_HURDLE

    @property
    def calibrates(self) -> bool:
        return self.calibration_strategy_id == ResidualShiftCalibration().strategy_id

    @property
    def normalizes_horizon(self) -> bool:
        return self.target_scale_id == HorizonNormalizedTarget().scale_id


@dataclass
class GroupArtifact:
    """One position x scoring preset's fitted model."""

    position: str
    scoring_preset: str
    features: tuple[str, ...]
    boosters: dict[str, list[lgb.Booster]]
    calibration_shift: QuantileShift | None
    dependence_correlation: float
    dependence_rows: int
    performance_bounds: DomainBounds | None
    point_bounds: DomainBounds
    training_rows: int

    def metadata(self, *, levels: Sequence[float]) -> dict[str, Any]:
        return {
            "position": self.position,
            "scoring_preset": self.scoring_preset,
            "features_used": list(self.features),
            "components": sorted(self.boosters),
            "calibration_shift": (
                self.calibration_shift.describe() if self.calibration_shift else None
            ),
            "dependence_correlation": self.dependence_correlation,
            "dependence_rows": self.dependence_rows,
            "performance_bounds": (
                self.performance_bounds.to_dict() if self.performance_bounds else None
            ),
            "point_bounds": self.point_bounds.to_dict(),
            "training_rows": self.training_rows,
            "levels": list(levels),
        }

    @property
    def key(self) -> str:
        return f"{self.position}-{self.scoring_preset}"


def _group_seed(spec: ProductionSpec, position: str, scoring_preset: str) -> int:
    """Deterministic per-group seed, derived exactly as the fold harness derives its own."""
    combined = spec.seed
    for part in (sum(ord(character) for character in f"{position}{scoring_preset}"),):
        combined = (combined * 1_000_003 + int(part)) % 2_147_483_647
    return combined


def _fit_group(
    frame: pl.DataFrame,
    *,
    spec: ProductionSpec,
    position: str,
    scoring_preset: str,
    features: Sequence[str],
) -> GroupArtifact:
    matrix = design_matrix(frame, features)
    keep, names = usable_columns(matrix, list(features))
    matrix = matrix[:, keep]
    seed = _group_seed(spec, position, scoring_preset)
    points = frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    point_bounds = DomainBounds.from_training(points)

    seasons = sorted(set(frame.get_column("season").to_list()))
    split = inner_chronological_split(seasons)
    inner_mask = pl.col("season").is_in(list(split.fit_seasons))
    inner_fit = frame.filter(inner_mask)
    inner_calibration = frame.filter(~inner_mask)

    boosters: dict[str, list[lgb.Booster]] = {}
    shift: QuantileShift | None = None
    correlation, dependence_rows = 0.0, 0
    performance_bounds: DomainBounds | None = None

    if spec.is_hurdle:
        boosters["availability"], boosters["performance"], performance_bounds = _fit_hurdle(
            frame,
            matrix,
            spec=spec,
            seed=seed,
            names=names,
        )
        if inner_fit.height and inner_calibration.height:
            inner_matrix = design_matrix(inner_fit, features)[:, keep]
            calibration_matrix = design_matrix(inner_calibration, features)[:, keep]
            inner_availability, inner_performance, inner_bounds = _fit_hurdle(
                inner_fit,
                inner_matrix,
                spec=spec,
                seed=seed,
                names=names,
            )
            rate_function, performance_function = _hurdle_functions(
                inner_availability,
                inner_performance,
                calibration_matrix,
                spec=spec,
                performance_bounds=inner_bounds,
            )
            correlation, dependence_rows = _fit_dependence(
                inner_calibration,
                rate_function,
                performance_function,
            )
            if spec.calibrates:
                composed = _compose(
                    inner_calibration,
                    rate_function,
                    performance_function,
                    spec=spec,
                    correlation=correlation,
                    season=int(max(split.residual_seasons)),
                    context_key=f"{position}|{scoring_preset}|inner",
                )
                shift = QuantileShift.fit(
                    inner_calibration.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    composed,
                    spec.levels,
                )
    else:
        target = HorizonNormalizedTarget() if spec.normalizes_horizon else IdentityTarget()
        boosters["total"] = fit_quantile_boosters(
            matrix,
            target.forward(points, season_array(frame)),
            levels=spec.levels,
            seed=seed,
            feature_names=names,
            parameters=dict(spec.parameters),
            num_boost_round=spec.num_boost_round,
        )
        if spec.calibrates and inner_fit.height and inner_calibration.height:
            inner_matrix = design_matrix(inner_fit, features)[:, keep]
            calibration_matrix = design_matrix(inner_calibration, features)[:, keep]
            inner_boosters = fit_quantile_boosters(
                inner_matrix,
                target.forward(
                    inner_fit.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    season_array(inner_fit),
                ),
                levels=spec.levels,
                seed=seed,
                feature_names=names,
                parameters=dict(spec.parameters),
                num_boost_round=spec.num_boost_round,
            )
            shift = QuantileShift.fit(
                target.forward(
                    inner_calibration.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy(),
                    season_array(inner_calibration),
                ),
                predict_quantiles(inner_boosters, calibration_matrix),
                spec.levels,
            )

    return GroupArtifact(
        position=position,
        scoring_preset=scoring_preset,
        features=tuple(names),
        boosters=boosters,
        calibration_shift=shift,
        dependence_correlation=correlation,
        dependence_rows=dependence_rows,
        performance_bounds=performance_bounds,
        point_bounds=point_bounds,
        training_rows=frame.height,
    )


def _fit_hurdle(
    frame: pl.DataFrame,
    matrix: Floats,
    *,
    spec: ProductionSpec,
    seed: int,
    names: Sequence[str],
) -> tuple[list[lgb.Booster], list[lgb.Booster], DomainBounds]:
    games = frame.get_column("actual_games_played").cast(pl.Float64).to_numpy()
    weeks = horizon_weeks_for(frame)
    rate = np.clip(games / weeks, 0.0, 1.0)
    availability = fit_quantile_boosters(
        matrix,
        rate,
        levels=spec.levels,
        seed=seed,
        feature_names=names,
        parameters=dict(spec.parameters),
        num_boost_round=spec.num_boost_round,
    )
    played = games >= 1.0
    points = frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    per_game = np.divide(points, np.where(played, games, 1.0))
    performance = fit_quantile_boosters(
        matrix[played],
        per_game[played],
        levels=spec.levels,
        seed=seed + 1,
        feature_names=names,
        parameters=dict(spec.parameters),
        num_boost_round=spec.num_boost_round,
    )
    return availability, performance, DomainBounds.from_training(per_game[played])


def _hurdle_functions(
    availability: Sequence[lgb.Booster],
    performance: Sequence[lgb.Booster],
    matrix: Floats,
    *,
    spec: ProductionSpec,
    performance_bounds: DomainBounds,
) -> tuple[QuantileFunction, QuantileFunction]:
    rate = monotone_projection(predict_quantiles(availability, matrix))
    per_game = monotone_projection(predict_quantiles(performance, matrix))
    return (
        QuantileFunction(tuple(spec.levels), rate, DomainBounds(0.0, 1.0)),
        QuantileFunction(tuple(spec.levels), per_game, performance_bounds),
    )


def _fit_dependence(
    frame: pl.DataFrame,
    rate_function: QuantileFunction,
    performance_function: QuantileFunction,
) -> tuple[float, int]:
    games = frame.get_column("actual_games_played").cast(pl.Float64).to_numpy()
    weeks = horizon_weeks_for(frame)
    played = games >= 1.0
    if int(np.count_nonzero(played)) < MINIMUM_DEPENDENCE_ROWS:
        return 0.0, int(np.count_nonzero(played))
    points = frame.get_column(TARGET_COLUMN).cast(pl.Float64).to_numpy()
    per_game = np.divide(points, np.where(played, games, 1.0))
    u_rate = rate_function.probability_integral_transform(np.clip(games / weeks, 0.0, 1.0))
    u_performance = performance_function.probability_integral_transform(per_game)
    z_rate = norm_ppf(u_rate[played])
    z_performance = norm_ppf(u_performance[played])
    if float(np.std(z_rate)) < 1e-9 or float(np.std(z_performance)) < 1e-9:
        return 0.0, int(np.count_nonzero(played))
    correlation = float(np.corrcoef(z_rate, z_performance)[0, 1])
    if correlation != correlation:
        correlation = 0.0
    return float(np.clip(correlation, -MAX_DEPENDENCE, MAX_DEPENDENCE)), int(
        np.count_nonzero(played),
    )


def _compose(
    frame: pl.DataFrame,
    rate_function: QuantileFunction,
    performance_function: QuantileFunction,
    *,
    spec: ProductionSpec,
    correlation: float,
    season: int,
    context_key: str,
) -> Floats:
    weeks = float(fantasy_horizon(season).week_count)
    streams = normal_draws(
        frame.get_column("player_id").to_list(),
        spec.composition_draws,
        seed_material=(spec.model_version, "hurdle_composition", context_key, season),
        streams=2,
    )
    z_rate = streams[0]
    z_performance = correlation * z_rate + np.sqrt(1.0 - correlation**2) * streams[1]
    games = np.clip(np.rint(rate_function.evaluate(norm_cdf(z_rate)) * weeks), 0.0, weeks)
    per_game = performance_function.evaluate(norm_cdf(z_performance))
    totals = np.where(games > 0.0, games * per_game, 0.0)
    return np.quantile(totals, list(spec.levels), axis=1).T.astype(np.float64)


@dataclass
class ProductionModel:
    """A trained, versioned intrinsic model that can be written and read back."""

    spec: ProductionSpec
    groups: dict[str, GroupArtifact]
    training_seasons: tuple[int, ...]
    feature_set_version: str
    feature_set_hash: str
    feature_schema_version: str
    feature_schema_hash: str
    features: tuple[str, ...]
    dataset_manifest: Mapping[str, Any] = field(default_factory=dict)
    git_sha: str = "unknown"
    generated_at_utc: str = ""

    # -- serialization -------------------------------------------------------------------

    def metadata(self) -> dict[str, Any]:
        return {
            "artifact_schema": ARTIFACT_SCHEMA,
            "model_version": self.spec.model_version,
            "spec": self.spec.to_dict(),
            "training_seasons": list(self.training_seasons),
            "feature_set_version": self.feature_set_version,
            "feature_set_hash": self.feature_set_hash,
            "feature_schema_version": self.feature_schema_version,
            "feature_schema_hash": self.feature_schema_hash,
            "features": list(self.features),
            "dataset_manifest": dict(self.dataset_manifest),
            "library": {"lightgbm": lgb.__version__, "numpy": np.__version__},
            "git_sha": self.git_sha,
            "generated_at_utc": self.generated_at_utc,
            "groups": [
                artifact.metadata(levels=self.spec.levels)
                for artifact in sorted(self.groups.values(), key=lambda item: item.key)
            ],
        }

    def save(self, directory: Path) -> list[Path]:
        """Write the artifact: one text booster per model, one JSON metadata file."""
        directory.mkdir(parents=True, exist_ok=True)
        booster_dir = directory / BOOSTER_DIR
        booster_dir.mkdir(exist_ok=True)
        written: list[Path] = []
        for artifact in sorted(self.groups.values(), key=lambda item: item.key):
            for component, boosters in sorted(artifact.boosters.items()):
                for index, booster in enumerate(boosters):
                    level = int(self.spec.levels[index] * 100)
                    path = booster_dir / f"{artifact.key}-{component}-q{level:02d}.txt"
                    path.write_text(booster.model_to_string(), encoding="utf-8")
                    written.append(path)
        metadata_path = directory / METADATA_FILE
        metadata_path.write_text(
            json.dumps(self.metadata(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(metadata_path)
        return written

    @classmethod
    def load(cls, directory: Path) -> ProductionModel:
        metadata_path = directory / METADATA_FILE
        if not metadata_path.is_file():
            raise FileNotFoundError(f"{metadata_path} not found; is this a model directory?")
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if payload.get("artifact_schema") != ARTIFACT_SCHEMA:
            raise FeatureSchemaMismatch(
                f"model artifact schema {payload.get('artifact_schema')!r} is not "
                f"{ARTIFACT_SCHEMA!r}",
            )
        spec = ProductionSpec.from_dict(payload["spec"])
        booster_dir = directory / BOOSTER_DIR
        groups: dict[str, GroupArtifact] = {}
        for group in payload["groups"]:
            key = f"{group['position']}-{group['scoring_preset']}"
            boosters: dict[str, list[lgb.Booster]] = {}
            for component in group["components"]:
                boosters[component] = [
                    lgb.Booster(
                        model_str=(
                            booster_dir / f"{key}-{component}-q{int(level * 100):02d}.txt"
                        ).read_text(encoding="utf-8"),
                    )
                    for level in spec.levels
                ]
            shift_payload = group.get("calibration_shift")
            shift = (
                QuantileShift(
                    tuple(spec.levels),
                    np.asarray(shift_payload["shifts"], dtype=np.float64),
                    int(shift_payload["calibration_rows"]),
                    bool(shift_payload["fitted"]),
                )
                if shift_payload
                else None
            )
            performance = group.get("performance_bounds")
            groups[key] = GroupArtifact(
                position=str(group["position"]),
                scoring_preset=str(group["scoring_preset"]),
                features=tuple(group["features_used"]),
                boosters=boosters,
                calibration_shift=shift,
                dependence_correlation=float(group["dependence_correlation"]),
                dependence_rows=int(group["dependence_rows"]),
                performance_bounds=(
                    DomainBounds(float(performance["lower"]), float(performance["upper"]))
                    if performance
                    else None
                ),
                point_bounds=DomainBounds(
                    float(group["point_bounds"]["lower"]),
                    float(group["point_bounds"]["upper"]),
                ),
                training_rows=int(group["training_rows"]),
            )
        return cls(
            spec=spec,
            groups=groups,
            training_seasons=tuple(int(value) for value in payload["training_seasons"]),
            feature_set_version=str(payload["feature_set_version"]),
            feature_set_hash=str(payload["feature_set_hash"]),
            feature_schema_version=str(payload["feature_schema_version"]),
            feature_schema_hash=str(payload["feature_schema_hash"]),
            features=tuple(payload["features"]),
            dataset_manifest=dict(payload.get("dataset_manifest", {})),
            git_sha=str(payload.get("git_sha", "unknown")),
            generated_at_utc=str(payload.get("generated_at_utc", "")),
        )

    # -- inference -----------------------------------------------------------------------

    def assert_compatible(self, *, feature_set_hash: str, feature_schema_hash: str) -> None:
        """Refuse to serve a frame built under a different feature contract."""
        if feature_set_hash != self.feature_set_hash:
            raise FeatureSchemaMismatch(
                f"model {self.spec.model_version} was trained on feature set "
                f"{self.feature_set_version} ({self.feature_set_hash}); the inference frame "
                f"declares {feature_set_hash}",
            )
        if feature_schema_hash != self.feature_schema_hash:
            raise FeatureSchemaMismatch(
                f"model {self.spec.model_version} was trained against feature schema "
                f"{self.feature_schema_version} ({self.feature_schema_hash}); the inference "
                f"frame declares {feature_schema_hash}",
            )

    def point_bounds(self) -> dict[str, dict[str, DomainBounds]]:
        """Sampling guard rails per scoring preset and position, from training data only."""
        bounds: dict[str, dict[str, DomainBounds]] = {}
        for artifact in self.groups.values():
            bounds.setdefault(artifact.scoring_preset, {})[artifact.position] = (
                artifact.point_bounds
            )
        return bounds

    def predict(self, frame: pl.DataFrame, *, season: int) -> pl.DataFrame:
        """Predictive quantiles for every row, on the fantasy-point scale.

        The frame must carry ``player_id``, ``position``, ``scoring_preset`` and the model's
        features. Rows whose position and scoring preset have no fitted group are refused
        rather than silently dropped.
        """
        missing = sorted(
            {
                f"{position}-{preset}"
                for position, preset in zip(
                    frame.get_column("position").to_list(),
                    frame.get_column("scoring_preset").to_list(),
                    strict=True,
                )
            }
            - set(self.groups),
        )
        if missing:
            raise FeatureSchemaMismatch(f"no fitted model for group(s) {missing}")

        blocks: list[pl.DataFrame] = []
        for key, artifact in sorted(self.groups.items()):
            block = frame.filter(
                (pl.col("position") == artifact.position)
                & (pl.col("scoring_preset") == artifact.scoring_preset),
            ).sort("player_id")
            if block.height == 0:
                continue
            quantiles = self._predict_group(block, artifact, season=season, key=key)
            blocks.append(
                block.select("player_id", "position", "scoring_preset").with_columns(
                    *[
                        pl.Series(
                            f"p{int(level * 100):02d}_points",
                            quantiles[:, index],
                            dtype=pl.Float64,
                        )
                        for index, level in enumerate(self.spec.levels)
                    ],
                ),
            )
        return pl.concat(blocks).sort("scoring_preset", "player_id") if blocks else pl.DataFrame()

    def _predict_group(
        self,
        block: pl.DataFrame,
        artifact: GroupArtifact,
        *,
        season: int,
        key: str,
    ) -> Floats:
        matrix = design_matrix(block, artifact.features)
        if artifact.boosters.get("availability"):
            rate_function, performance_function = _hurdle_functions(
                artifact.boosters["availability"],
                artifact.boosters["performance"],
                matrix,
                spec=self.spec,
                performance_bounds=artifact.performance_bounds
                or DomainBounds(float("-inf"), float("inf")),
            )
            raw = _compose(
                block,
                rate_function,
                performance_function,
                spec=self.spec,
                correlation=artifact.dependence_correlation,
                season=season,
                context_key=key,
            )
        else:
            raw = predict_quantiles(artifact.boosters["total"], matrix)
            if self.spec.normalizes_horizon:
                raw = raw * float(fantasy_horizon(season).week_count)
        strategy = ResidualShiftCalibration() if self.spec.calibrates else MonotoneOnly()
        return strategy.calibrate(raw, shift=artifact.calibration_shift)


def train_production_model(
    frame: pl.DataFrame,
    *,
    spec: ProductionSpec,
    features: Sequence[str] | None = None,
    dataset_manifest: Mapping[str, Any] | None = None,
    git_sha: str = "unknown",
    generated_at: datetime | None = None,
) -> ProductionModel:
    """Train the frozen architecture on every row of ``frame``.

    ``frame`` is the modelling frame - one row per season, player and scoring preset - and
    every season in it is a training season. There is no held-out fold here by design:
    validation happened during development and on the final holdout, and a production model
    trained on less than everything it is allowed to see would be a worse model for no
    reason.
    """
    selection = core_feature_selection()
    chosen = tuple(features) if features is not None else tuple(selection.included)
    seasons = tuple(sorted(set(frame.get_column("season").to_list())))
    groups: dict[str, GroupArtifact] = {}
    for position in sorted(set(frame.get_column("position").to_list())):
        for preset in sorted(set(frame.get_column("scoring_preset").to_list())):
            block = frame.filter(
                (pl.col("position") == position) & (pl.col("scoring_preset") == preset),
            )
            if block.height == 0:
                continue
            artifact = _fit_group(
                block,
                spec=spec,
                position=position,
                scoring_preset=preset,
                features=chosen,
            )
            groups[artifact.key] = artifact
    return ProductionModel(
        spec=spec,
        groups=groups,
        training_seasons=seasons,
        feature_set_version=selection.version,
        feature_set_hash=selection.fingerprint(),
        feature_schema_version=selection.source_schema_version,
        feature_schema_hash=selection.source_schema_hash,
        features=chosen,
        dataset_manifest=dict(dataset_manifest or {}),
        git_sha=git_sha,
        generated_at_utc=isoformat_utc(generated_at or utc_now()),
    )
