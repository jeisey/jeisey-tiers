"""The rest-of-season production model: fitting it once, storing it, and serving it.

The counterpart of :mod:`ffdraft.modeling.production`, for the rest-of-season architecture,
and it exists for the same reason: fold evaluation and production fitting are different
activities, and :mod:`ffdraft.ros.estimators` deliberately exposes no fitted object so that
fold isolation is structural rather than remembered. Production needs the opposite — an
object that outlives everything, is written to disk, and is loaded weeks later by a build
that has no training data at all.

**This is a refit of an accepted architecture, not a new model** (ADR-078). The fitting is
performed by :class:`~ffdraft.ros.candidates.RosHurdleCandidate` itself, not by a
reimplementation: :meth:`RosProductionModel.predict` calls the same
``quantile_functions``/``compose_draws`` the evaluated candidate composes with — the second
of which is literally the body of ``_compose`` — so "the same code path" is a property of the
call graph rather than a claim in a comment. What a refit may
vary is the labelled rows it sees; :meth:`RosProductionSpec.configuration_hash` is written
into the artifact so anything else is detectable.

Three rules the format enforces:

**Not a pickle.** Every booster is stored as LightGBM's own text representation, gzipped with
``mtime=0`` so two fits of the same model produce identical bytes, and every booster's
SHA-256 is recorded. Loading reads numbers and a documented text format; it never executes a
serialized object graph (`AGENTS.md` section 5).

**A feature contract that fails closed.** The artifact records the `ros_core_v1` feature-set
hash and the `ros_features_v1` schema hash, and inference refuses a frame that declares
anything else.

**A training window that cannot silently widen.** The sealed-season rule
(``season >= 2025``) still applies, so including 2025 needs the same explicit authorization
the final evaluation needed, and a season at or after the serving season is refused outright.
Two independent barriers, because training on the season being predicted is the one error
that cannot be detected from the output.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import polars as pl

from ffdraft.modeling.estimators import repair_monotonicity
from ffdraft.modeling.preprocessing import design_matrix
from ffdraft.ros.candidates import RosHurdleCandidate
from ffdraft.ros.dictionary import ros_feature_selection
from ffdraft.ros.estimators import ROS_TARGET_COLUMN, RosFitContext
from ffdraft.ros.folds import RosFold, RosFoldKind
from ffdraft.ros.frozen import (
    ROS_PRODUCTION_FIRST_TRAINING_SEASON,
    ROS_PRODUCTION_FIT_RULE_VERSION,
    ROS_PRODUCTION_LAST_TRAINING_SEASON,
    ROS_PRODUCTION_SPEC,
    RosProductionSpec,
    RosRefitReason,
)
from ffdraft.ros.holdout import RosFinalEvalAuthorization, is_ros_sealed
from ffdraft.simulation.sampler import DomainBounds
from ffdraft.timeutil import isoformat_utc, utc_now

__all__ = [
    "ROS_ARTIFACT_SCHEMA",
    "ROS_METADATA_FILE",
    "RosFeatureSchemaMismatch",
    "RosGroupArtifact",
    "RosProductionModel",
    "production_fold",
    "train_ros_production_model",
]

#: The on-disk contract. Bump when the layout changes in a way an older loader cannot read.
ROS_ARTIFACT_SCHEMA = "ros_model_artifact_v1"

ROS_METADATA_FILE = "metadata.json"
_BOOSTER_DIR = "boosters"
_BOOSTER_SUFFIX = ".txt.gz"

#: Both hurdle components, in the order the artifact lists them.
_COMPONENTS = ("availability", "performance")


class RosFeatureSchemaMismatch(RuntimeError):
    """Raised when a ROS model is asked to predict from a frame it was not built for."""


def production_fold(
    *,
    first_season: int = ROS_PRODUCTION_FIRST_TRAINING_SEASON,
    last_season: int = ROS_PRODUCTION_LAST_TRAINING_SEASON,
    serving_season: int,
) -> RosFold:
    """The production fit's fold: train through ``last_season``, serve ``serving_season``.

    A fold rather than a bare season list, because the candidate's per-group seed and Monte
    Carlo stream key are derived from one — so the production fit is seeded by exactly the
    mechanism every evaluated fold was, and a build is reproducible from the fold id alone.
    """
    return RosFold(
        train_start_season=first_season,
        train_end_season=last_season,
        validation_season=serving_season,
        kind=RosFoldKind.PRODUCTION,
    )


def _read_booster(path: Path, *, expected_sha256: str | None = None) -> str:
    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    if expected_sha256 is not None:
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected_sha256:
            raise RosFeatureSchemaMismatch(
                f"{path.name} does not match the digest recorded in the model metadata "
                f"({actual} != {expected_sha256}); the artifact has been altered",
            )
    return payload.decode("utf-8")


@dataclass
class RosGroupArtifact:
    """One position x scoring preset's fitted hurdle, plus what it was fitted on."""

    position: str
    scoring_preset: str
    features: tuple[str, ...]
    boosters: dict[str, list[lgb.Booster]]
    performance_bounds: DomainBounds
    point_bounds: DomainBounds
    dependence_correlation: float
    dependence_rows: int
    training_rows: int
    training_rows_with_remaining_games: int

    @property
    def key(self) -> str:
        return f"{self.position}-{self.scoring_preset}"

    def metadata(self, *, levels: Sequence[float]) -> dict[str, Any]:
        return {
            "position": self.position,
            "scoring_preset": self.scoring_preset,
            "features_used": list(self.features),
            "components": list(_COMPONENTS),
            "performance_bounds": self.performance_bounds.to_dict(),
            "point_bounds": self.point_bounds.to_dict(),
            "dependence_correlation": self.dependence_correlation,
            "dependence_rows": self.dependence_rows,
            "training_rows": self.training_rows,
            "training_rows_with_remaining_games": self.training_rows_with_remaining_games,
            "levels": list(levels),
        }


@dataclass
class RosProductionModel:
    """A fitted, versioned rest-of-season model that can be written and read back."""

    spec: RosProductionSpec
    groups: dict[str, RosGroupArtifact]
    fold: RosFold
    training_seasons: tuple[int, ...]
    training_rows: int
    feature_set_version: str
    feature_set_hash: str
    feature_schema_version: str
    feature_schema_hash: str
    features: tuple[str, ...]
    cutoff_rule_version: str
    label_version: str
    refit_reason: str = RosRefitReason.INITIAL_PRODUCTION_FIT.value
    sealed_season_authorization: Mapping[str, Any] | None = None
    dataset_manifest: Mapping[str, Any] = field(default_factory=dict)
    git_sha: str = "unknown"
    generated_at_utc: str = ""

    # -- serialization -------------------------------------------------------------------

    @property
    def serving_season(self) -> int:
        return self.fold.validation_season

    def metadata(self) -> dict[str, Any]:
        return {
            "artifact_schema": ROS_ARTIFACT_SCHEMA,
            "model_version": self.spec.model_version,
            "production_fit_rule_version": ROS_PRODUCTION_FIT_RULE_VERSION,
            "configuration_hash": self.spec.configuration_hash(),
            "spec": self.spec.to_dict(),
            "fold": self.fold.to_dict(),
            "serving_season": self.serving_season,
            "training_seasons": list(self.training_seasons),
            "training_rows": self.training_rows,
            "refit_reason": self.refit_reason,
            "sealed_season_authorization": (
                dict(self.sealed_season_authorization)
                if self.sealed_season_authorization is not None
                else None
            ),
            "feature_set_version": self.feature_set_version,
            "feature_set_hash": self.feature_set_hash,
            "feature_schema_version": self.feature_schema_version,
            "feature_schema_hash": self.feature_schema_hash,
            "features": list(self.features),
            "cutoff_rule_version": self.cutoff_rule_version,
            "label_version": self.label_version,
            "dataset_manifest": dict(self.dataset_manifest),
            "library": {"lightgbm": lgb.__version__, "numpy": np.__version__},
            "git_sha": self.git_sha,
            "generated_at_utc": self.generated_at_utc,
            "groups": [
                artifact.metadata(levels=self.spec.levels)
                for artifact in sorted(self.groups.values(), key=lambda item: item.key)
            ],
            "notes": [
                "A production refit of an architecture accepted in Phase 11 (ADR-077, "
                "ADR-078). It carries no performance claim of its own: it was scored on "
                "nothing, and every measured number lives in the Phase-11 evidence.",
                "The sealed 2025 season is not re-scored by this fit and is not re-opened "
                "as evaluation evidence.",
            ],
        }

    def save(self, directory: Path) -> list[Path]:
        """Write the artifact: one gzipped text booster per model, one JSON metadata file."""
        directory.mkdir(parents=True, exist_ok=True)
        booster_dir = directory / _BOOSTER_DIR
        booster_dir.mkdir(exist_ok=True)
        written: list[Path] = []
        digests: dict[str, str] = {}
        for artifact in sorted(self.groups.values(), key=lambda item: item.key):
            for component in _COMPONENTS:
                for index, booster in enumerate(artifact.boosters[component]):
                    name = self._booster_name(artifact.key, component, index)
                    payload = booster.model_to_string().encode("utf-8")
                    digests[name] = hashlib.sha256(payload).hexdigest()
                    path = booster_dir / name
                    with gzip.GzipFile(path, "wb", compresslevel=9, mtime=0) as handle:
                        handle.write(payload)
                    written.append(path)
        metadata_path = directory / ROS_METADATA_FILE
        metadata_path.write_text(
            json.dumps({**self.metadata(), "booster_sha256": digests}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        written.append(metadata_path)
        return written

    def _booster_name(self, key: str, component: str, index: int) -> str:
        return f"{key}-{component}-q{int(self.spec.levels[index] * 100):02d}{_BOOSTER_SUFFIX}"

    @classmethod
    def load(cls, directory: Path) -> RosProductionModel:
        metadata_path = directory / ROS_METADATA_FILE
        if not metadata_path.is_file():
            raise FileNotFoundError(
                f"{metadata_path} not found; run `ffdraft train-ros-production` first",
            )
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if payload.get("artifact_schema") != ROS_ARTIFACT_SCHEMA:
            raise RosFeatureSchemaMismatch(
                f"ROS model artifact schema {payload.get('artifact_schema')!r} is not "
                f"{ROS_ARTIFACT_SCHEMA!r}",
            )
        spec = RosProductionSpec.from_dict(payload["spec"])
        declared = str(payload.get("configuration_hash", ""))
        if declared != spec.configuration_hash():
            raise RosFeatureSchemaMismatch(
                "the stored configuration hash does not describe the stored specification "
                f"({declared} != {spec.configuration_hash()}); the artifact has been altered",
            )
        digests: Mapping[str, str] = payload.get("booster_sha256", {})
        booster_dir = directory / _BOOSTER_DIR
        groups: dict[str, RosGroupArtifact] = {}
        for group in payload["groups"]:
            key = f"{group['position']}-{group['scoring_preset']}"
            boosters = {
                component: [
                    lgb.Booster(
                        model_str=_read_booster(
                            booster_dir / _name,
                            expected_sha256=digests.get(_name),
                        ),
                    )
                    for _name in (
                        f"{key}-{component}-q{int(level * 100):02d}{_BOOSTER_SUFFIX}"
                        for level in spec.levels
                    )
                ]
                for component in _COMPONENTS
            }
            groups[key] = RosGroupArtifact(
                position=str(group["position"]),
                scoring_preset=str(group["scoring_preset"]),
                features=tuple(group["features_used"]),
                boosters=boosters,
                performance_bounds=DomainBounds(
                    float(group["performance_bounds"]["lower"]),
                    float(group["performance_bounds"]["upper"]),
                ),
                point_bounds=DomainBounds(
                    float(group["point_bounds"]["lower"]),
                    float(group["point_bounds"]["upper"]),
                ),
                dependence_correlation=float(group["dependence_correlation"]),
                dependence_rows=int(group["dependence_rows"]),
                training_rows=int(group["training_rows"]),
                training_rows_with_remaining_games=int(
                    group["training_rows_with_remaining_games"],
                ),
            )
        fold_payload = payload["fold"]
        authorization = payload.get("sealed_season_authorization")
        return cls(
            spec=spec,
            groups=groups,
            fold=RosFold(
                train_start_season=int(fold_payload["train_start_season"]),
                train_end_season=int(fold_payload["train_end_season"]),
                validation_season=int(fold_payload["validation_season"]),
                kind=RosFoldKind(str(fold_payload["kind"])),
            ),
            training_seasons=tuple(int(value) for value in payload["training_seasons"]),
            training_rows=int(payload["training_rows"]),
            feature_set_version=str(payload["feature_set_version"]),
            feature_set_hash=str(payload["feature_set_hash"]),
            feature_schema_version=str(payload["feature_schema_version"]),
            feature_schema_hash=str(payload["feature_schema_hash"]),
            features=tuple(payload["features"]),
            cutoff_rule_version=str(payload["cutoff_rule_version"]),
            label_version=str(payload["label_version"]),
            refit_reason=str(payload.get("refit_reason", "")),
            sealed_season_authorization=dict(authorization) if authorization else None,
            dataset_manifest=dict(payload.get("dataset_manifest", {})),
            git_sha=str(payload.get("git_sha", "unknown")),
            generated_at_utc=str(payload.get("generated_at_utc", "")),
        )

    # -- inference -----------------------------------------------------------------------

    def assert_compatible(self, *, feature_set_hash: str, feature_schema_hash: str) -> None:
        """Refuse to serve a frame built under a different feature contract."""
        if feature_set_hash != self.feature_set_hash:
            raise RosFeatureSchemaMismatch(
                f"model {self.spec.model_version} was fitted on feature set "
                f"{self.feature_set_version} ({self.feature_set_hash}); the inference frame "
                f"declares {feature_set_hash}",
            )
        if feature_schema_hash != self.feature_schema_hash:
            raise RosFeatureSchemaMismatch(
                f"model {self.spec.model_version} was fitted against feature schema "
                f"{self.feature_schema_version} ({self.feature_schema_hash}); the inference "
                f"frame declares {feature_schema_hash}",
            )

    def assert_serving_season(self, season: int) -> None:
        """Refuse to serve a season the fit was allowed to train on."""
        if season <= self.fold.train_end_season:
            raise RosFeatureSchemaMismatch(
                f"model {self.spec.model_version} trained through {self.fold.train_end_season}; "
                f"serving season {season} would be scored by a model that saw its outcomes",
            )

    def point_bounds(self) -> dict[str, dict[str, DomainBounds]]:
        """Sampling guard rails per scoring preset and position, from training rows only."""
        bounds: dict[str, dict[str, DomainBounds]] = {}
        for artifact in self.groups.values():
            bounds.setdefault(artifact.scoring_preset, {})[artifact.position] = (
                artifact.point_bounds
            )
        return bounds

    def _candidate(self) -> RosHurdleCandidate:
        """The evaluated candidate class, configured from the frozen spec.

        Composition therefore runs through exactly the code Phase 11 evaluated rather than
        through a production copy of it (ADR-078).
        """
        return RosHurdleCandidate(
            parameters=dict(self.spec.parameters),
            num_boost_round=self.spec.num_boost_round,
            composition_draws=self.spec.composition_draws,
            seed_material=self.spec.composition_seed_material,
        )

    def predict(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Predictive remaining-point quantiles for every row.

        The frame must carry ``player_id``, ``through_week``, ``position``,
        ``scoring_preset`` and the model's features. A row whose group has no fitted model
        is refused rather than silently dropped.
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
            raise RosFeatureSchemaMismatch(f"no fitted ROS model for group(s) {missing}")

        candidate = self._candidate()
        columns = [f"q{int(level * 100):02d}" for level in self.spec.levels]
        blocks: list[pl.DataFrame] = []
        for key, artifact in sorted(self.groups.items()):
            block = frame.filter(
                (pl.col("position") == artifact.position)
                & (pl.col("scoring_preset") == artifact.scoring_preset),
            ).sort("player_id")
            if block.height == 0:
                continue
            matrix = design_matrix(block, list(artifact.features))
            rate_function, performance_function = candidate.quantile_functions(
                artifact.boosters["availability"],
                artifact.boosters["performance"],
                matrix,
                levels=self.spec.levels,
                performance_bounds=artifact.performance_bounds,
            )
            games, totals = candidate.compose_draws(
                block,
                rate_function,
                performance_function,
                correlation=artifact.dependence_correlation,
                context_key=f"{self.fold.fold_id}|{key}",
            )
            raw = np.quantile(totals, list(self.spec.levels), axis=1).T.astype(np.float64)
            quantiles = repair_monotonicity(raw)
            game_quantiles = np.quantile(games, list(self.spec.levels), axis=1).T
            keys = block.select("player_id", "through_week", "position", "scoring_preset")
            blocks.append(
                keys.with_columns(
                    *[
                        pl.Series(name, quantiles[:, index], dtype=pl.Float64)
                        for index, name in enumerate(columns)
                    ],
                    # The availability half of the hurdle, published rather than discarded:
                    # "how many appearances are left" is a quantity a reader asks for
                    # directly, and it comes from the same draws the totals do.
                    pl.Series(
                        "expected_remaining_games",
                        games.mean(axis=1),
                        dtype=pl.Float64,
                    ),
                    *[
                        pl.Series(
                            f"remaining_games_{name}",
                            game_quantiles[:, index],
                            dtype=pl.Float64,
                        )
                        for index, name in enumerate(columns)
                    ],
                ),
            )
        if not blocks:
            return pl.DataFrame()
        return pl.concat(blocks).sort("scoring_preset", "player_id")


def train_ros_production_model(
    frame: pl.DataFrame,
    *,
    serving_season: int,
    spec: RosProductionSpec = ROS_PRODUCTION_SPEC,
    features: Sequence[str] | None = None,
    refit_reason: RosRefitReason = RosRefitReason.INITIAL_PRODUCTION_FIT,
    authorization: RosFinalEvalAuthorization | None = None,
    dataset_manifest: Mapping[str, Any] | None = None,
    cutoff_rule_version: str = "",
    label_version: str = "",
    git_sha: str = "unknown",
    generated_at: datetime | None = None,
) -> RosProductionModel:
    """Fit the accepted architecture on every row of ``frame`` (ADR-078).

    ``frame`` is the rest-of-season snapshot table — one row per season, cutoff week, player
    and scoring preset — and every season in it is a training season. There is no held-out
    fold here by design: validation happened in Phase 11's five chronological folds and once
    on the sealed season, and a production model fitted on less than everything it is
    allowed to see would be a worse model for no reason.

    Two refusals are structural rather than advisory:

    * a training season at or after ``serving_season`` is rejected, because a model that saw
      the outcomes of the season it predicts is not a forecaster;
    * a sealed training season without an explicit :class:`RosFinalEvalAuthorization` is
      rejected, so the window cannot widen by accident.
    """
    seasons = tuple(sorted({int(value) for value in frame.get_column("season").to_list()}))
    if not seasons:
        raise ValueError("the production fit was handed no training rows")

    future = [season for season in seasons if season >= serving_season]
    if future:
        raise ValueError(
            f"refusing to fit on season(s) {future} at or after the serving season "
            f"{serving_season}: a rest-of-season model may never see the outcomes of the "
            "season it predicts (ADR-078)",
        )
    sealed = [season for season in seasons if is_ros_sealed(season)]
    if sealed and authorization is None:
        raise ValueError(
            f"season(s) {sealed} are sealed; a production fit that includes them requires "
            "the same explicit final-evaluation authorization the sealed evaluation "
            "required (ADR-078 step 3)",
        )

    selection = ros_feature_selection()
    chosen = tuple(features) if features is not None else tuple(selection.included)
    usable_features = tuple(name for name in chosen if name in frame.columns)
    fold = production_fold(
        first_season=min(seasons),
        last_season=max(seasons),
        serving_season=serving_season,
    )
    candidate = RosHurdleCandidate(
        parameters=dict(spec.parameters),
        num_boost_round=spec.num_boost_round,
        composition_draws=spec.composition_draws,
        seed_material=spec.composition_seed_material,
    )

    groups: dict[str, RosGroupArtifact] = {}
    for position in sorted({str(value) for value in frame.get_column("position").to_list()}):
        for preset in sorted({str(v) for v in frame.get_column("scoring_preset").to_list()}):
            block = frame.filter(
                (pl.col("position") == position) & (pl.col("scoring_preset") == preset),
            )
            if block.height == 0:
                continue
            context = RosFitContext(
                fold=fold,
                position=position,
                scoring_preset=preset,
                features=usable_features,
                seed=spec.seed,
                levels=spec.levels,
            )
            fitted = candidate.fit_components(block, context)
            correlation, dependence_rows = candidate.fit_production_dependence(block, fitted)
            games = block.get_column("actual_remaining_games").cast(pl.Float64).to_numpy()
            points = block.get_column(ROS_TARGET_COLUMN).cast(pl.Float64).to_numpy()
            artifact = RosGroupArtifact(
                position=position,
                scoring_preset=preset,
                features=fitted.features,
                boosters={
                    "availability": list(fitted.availability),
                    "performance": list(fitted.performance),
                },
                performance_bounds=fitted.bounds,
                point_bounds=DomainBounds.from_training(points),
                dependence_correlation=correlation,
                dependence_rows=dependence_rows,
                training_rows=block.height,
                training_rows_with_remaining_games=int(np.count_nonzero(games >= 1.0)),
            )
            groups[artifact.key] = artifact

    return RosProductionModel(
        spec=spec,
        groups=groups,
        fold=fold,
        training_seasons=seasons,
        training_rows=frame.height,
        feature_set_version=selection.version,
        feature_set_hash=selection.fingerprint(),
        feature_schema_version=selection.schema_version,
        feature_schema_hash=selection.schema_hash,
        features=usable_features,
        cutoff_rule_version=cutoff_rule_version,
        label_version=label_version,
        refit_reason=refit_reason.value,
        sealed_season_authorization=(
            {**authorization.to_dict(), "sealed_training_seasons": sealed}
            if authorization is not None and sealed
            else None
        ),
        dataset_manifest=dict(dataset_manifest or {}),
        git_sha=git_sha,
        generated_at_utc=isoformat_utc(generated_at or utc_now()),
    )
